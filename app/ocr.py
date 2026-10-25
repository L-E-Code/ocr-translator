import abc
import os
import re
import time
import logging
import threading
import hashlib
import unicodedata
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from difflib import SequenceMatcher
from PIL import Image
import cv2
import numpy as np
import torch
from dotenv import load_dotenv
from deep_translator import MyMemoryTranslator, GoogleTranslator
from manga_ocr.ocr import post_process as manga_ocr_post_process
from translation_cache import PersistentTranslationCache
from device import resolve_device
from glossary import Glossary
from circuit_breaker import CircuitBreaker
import secrets_store
from paths import root_path
from languages import language, easyocr_languages, has_script
from name_memory import NameMemory
from ssl_fallback import with_certificate_fallback

load_dotenv(root_path(".env"))

from logger_config import get_logger
logger = get_logger("OCR")

# Hide internal warnings
logging.getLogger("easyocr").setLevel(logging.ERROR)


def compute_text_similarity(text1, text2):
    """
    Computes the similarity (0.0 to 1.0) between two screen readings,
    ignoring spaces and punctuation, to tell whether it is still
    the same line of dialogue.
    """
    if not text1 or not text2:
        return 0.0
    t1 = re.sub(r'[\s\W_]+', '', text1)
    t2 = re.sub(r'[\s\W_]+', '', text2)
    if not t1 or not t2:
        return 0.0
    if t1 == t2:
        return 1.0
    return SequenceMatcher(None, t1, t2).ratio()

def contains_japanese(text):
    """
    Checks whether the text contains Japanese characters (Hiragana, Katakana or Kanji).
    """
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]', text))

def is_meaningful_text(text, source_lang='ja'):
    """
    Filters out empty noise and content-less text.
    """
    cleaned = re.sub(r'[\s\W_]+', '', text)
    if len(cleaned) < 2:
        return False
    return has_script(cleaned, source_lang)

# MangaOCR's CRAFT detector: maximum resolution and magnification (lower = faster)
DETECT_CANVAS_SIZE = 1280
DETECT_MAG_RATIO = 1.0

# Regions with a height from this value (px) up are not upscaled
UPSCALE_MAX_HEIGHT = 200

def preprocess_for_ocr(image):
    """
    Applies computer vision to text boxes, dialogues and titles on screen (for interfaces, documents and games):
    - 2.0x upscale (cubic interpolation) only when the region is small (height < UPSCALE_MAX_HEIGHT);
      captures that are already sharp/large keep their native resolution
    - Converts to sharp grayscale without creating destructive blur
    """
    if isinstance(image, str):
        if not os.path.exists(image):
            return None, 1.0
        image = cv2.imread(image)
        if image is None:
            return None, 1.0
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)

    # 1. Conditional upscale
    if h >= UPSCALE_MAX_HEIGHT:
        return gray, 1.0

    scale_factor = 2.0
    gray = cv2.resize(gray, (int(w * scale_factor), int(h * scale_factor)), interpolation=cv2.INTER_CUBIC)
    
    return gray, scale_factor

def clean_character_name(text):
    """
    Sanitizes names and titles read by OCR:
    - Normalizes symbols, special characters and spurious spaces
    """
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r'^[@＠][ョ]', 'ショ', text)
    text = re.sub(r'^[ツッ][司ョ]', 'ショ', text)
    text = re.sub(r'^[cC]+(?=[A-Z])', '', text)
    text = re.sub(r'^[・\s\W_]+|[・\s\W_]+$', '', text)
    return text.strip()

def clean_ocr_punctuation(text):
    """
    Sanitizes punctuation and corrupted characters common in stylized on-screen fonts and visual media (including games):
    - Normalizes opening quotes and the fusion of '「' with 'い' (e.g. 『っしゃ / っしゃ -> 「いらっしゃ)
    - Converts '@' or '＠' in dialogues to '！'
    - Fixes classic katakana and kanji confusions
    - Cleans corrupted tails of music notes or visual symbols (e.g. '一守め」', '古一)d」' -> '」')
    """
    if not text:
        return ""
        
    text = text.strip()
        
    # 1. Normalizes opening quotes and common fusions with the first letter
    text = re.sub(r'^[『「]?[さうっ]しゃいませ', '「いらっしゃいませ', text)
    text = re.sub(r'^[『「]?[っ]しゃ', '「いらっしゃ', text)
    text = re.sub(r'^[『「][っ]', '「っ', text)
    text = re.sub(r'^[『]', '「', text)
    
    # 2. Converts @ to ! in dialogues and removes isolated Latin letters
    text = re.sub(r'[@＠]', '！', text)
    text = re.sub(r'\s+[a-zA-Z]\s+', ' ', text)
    
    # 3. Fixes common greetings and farewells (e.g. いま世 / いま笹 -> いませ！)
    text = re.sub(r'いま[世笹]', 'いませ！', text)
    
    # 4. Common grammar patterns (〜になりまして / になります)
    text = re.sub(r'こちら[暖医尼隈厄]*[なゆり]+まし[てで]', 'こちらになりまして', text)

    
    # 5. Fixes katakana with crossed strokes
    text = re.sub(r'オスス[次女・]', 'オススメ', text)
    
    # 6. Frequent vocabulary in interfaces and menus (看板 = menu board/sign)
    text = re.sub(r'(^|\s)[包母ほ]ちら', r'\1こちら', text)
    text = re.sub(r'看[楓根]', '看板', text)

    
    # 7. Removes stray closing quotes right after an exclamation mark
    text = re.sub(r'！\s*[』」]+', '！ ', text)
    
    # 8. Removes corrupted tails at the end of lines (caused by ♪, ♥ or icons)
    text = re.sub(r'[-~]?[宙空]+」?$', '」', text)
    text = re.sub(r'[旭古一\-~]*[守恋]?[-~]?[0-9oO]?[めdD)）]+」?$', '」', text)
    text = re.sub(r'\[$', 'た。', text)
    text = re.sub(r'V$', '」', text)
    
    # If the line started with 「 but did not close
    if '「' in text and not text.endswith('」'):
        text = text + '」'
        
    return text.strip()

# ==========================================
# 1. HYBRID ARCHITECTURE (STRATEGY PATTERN)
#           EasyOCR + MangaOCR
# ==========================================

class BaseOCREngine(abc.ABC):
    @abc.abstractmethod
    def extract_text_boxes(self, image_np, offset_x=0, offset_y=0):
        pass

    def warm_up(self):
        """Runs a throwaway inference so the first real read does not pay for the initialization."""
        pass

HUD_KEYWORDS = {
    'auto', 'skip', 'save', 'load', 'q.save', 'q.load', 'qsave', 'qload',
    'config', 'log', 'back', 'next', 'menu', 'voice', 'system', 'history',
    'rewind', 'fast', 'stop', 'play', 'window', 'full'
}

def is_hud_element(text):
    """
    Identifies whether an isolated text is an interface/HUD button of an application or game.
    """
    cleaned = re.sub(r'[\s\W_]+', '', text).lower()
    return cleaned in HUD_KEYWORDS


def calculate_dominant_font_height(items):
    """
    Computes the weighted median of the text boxes' height.
    Since the dialogue holds the vast majority of the characters on screen,
    the median weighted by character count finds the exact height
    of the main reading font, regardless of resolution (1080p, 4K, etc.).
    """
    if not items:
        return 0.0
    weighted_heights = []
    for it in items:
        h = it['h']
        weight = max(1, len(it['txt']))
        weighted_heights.extend([h] * weight)
    return float(np.median(weighted_heights))

def cluster_dialogue_lines(candidates, h_ref):
    """
    Groups dialogue text boxes that share spatial proximity
    and continuous vertical flow, discarding isolated scenery text.
    """
    if len(candidates) <= 1:
        return candidates
        
    # Sorts top to bottom
    sorted_candidates = sorted(candidates, key=lambda c: c['y1'])
    
    clusters = []
    current_cluster = [sorted_candidates[0]]
    
    for prev, curr in zip(sorted_candidates[:-1], sorted_candidates[1:]):
        # Maximum expected vertical distance between consecutive lines of the same dialogue
        max_vertical_gap = max(2.5 * h_ref, 25.0)
        gap_y = curr['y1'] - prev['y2']
        
        if gap_y <= max_vertical_gap:
            current_cluster.append(curr)
        else:
            clusters.append(current_cluster)
            current_cluster = [curr]
            
    if current_cluster:
        clusters.append(current_cluster)
        
    # Selects the dominant cluster (with the largest total character volume)
    best_cluster = max(clusters, key=lambda cl: sum(len(c['txt']) for c in cl))
    return best_cluster

class _CPUSequenceModel(torch.nn.Module):
    """Runs the recognizer's BiLSTM on the CPU and hands the result back to the GPU."""
    def __init__(self, inner, device):
        super().__init__()
        self.inner = inner.to('cpu')
        self.device = device

    def forward(self, x):
        return self.inner(x.float().cpu()).to(self.device, x.dtype)

def try_cpu_lstm(reader):
    """
    EasyOCR reads one box at a time, and on some GPUs (Intel XPU) its small LSTM is much slower than on the processor
    (about 45% of the recognition time in tests). Moves it to the CPU only if that is clearly faster on this machine
    and reads the same text on a test image.
    """
    model = getattr(reader, 'recognizer', None)
    seq = getattr(model, 'SequenceModeling', None)
    if seq is None:
        return
    probe = np.zeros((64, 900), dtype=np.uint8)
    cv2.putText(probe, "HELLO WORLD 123 TEST", (10, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.4, 255, 3)
    boxes = [[0, 900, 0, 64], [0, 450, 0, 64], [0, 200, 0, 64]]

    def timed():
        reader.recognize(probe, horizontal_list=boxes, free_list=[], batch_size=1)  # compiles the shapes first
        t0 = time.perf_counter()
        for _ in range(3):
            out = reader.recognize(probe, horizontal_list=boxes, free_list=[], batch_size=1)
        return time.perf_counter() - t0, [r[1] for r in out]

    try:
        gpu_time, expected = timed()
        model.SequenceModeling = _CPUSequenceModel(seq, reader.device)
        cpu_time, got = timed()
        if got != expected:
            raise RuntimeError("CPU LSTM reads differently")
        if cpu_time > 0.85 * gpu_time:
            raise RuntimeError(f"not faster ({cpu_time * 1000:.0f} vs {gpu_time * 1000:.0f} ms)")
        logger.info(f"EasyOCR recognizer LSTM running on the CPU ({gpu_time / cpu_time:.1f}x faster recognition).")
    except Exception as e:
        logger.info(f"EasyOCR recognizer LSTM kept on '{reader.device}' ({e}).")
        model.SequenceModeling = seq.to(reader.device)

def create_easyocr_reader(langs, device):
    """
    Creates the EasyOCR reader on the requested device ('cpu', 'cuda', 'xpu', 'mps').
    Runs a warm-up read to validate the GPU; if it fails, falls back to the CPU.
    Returns (reader, effective_device).
    """
    import easyocr
    if device != 'cpu':
        try:
            reader = with_certificate_fallback(easyocr.Reader, langs, gpu=device)
            # EasyOCR wraps the models in DataParallel, which only knows how to split batches between
            # CUDA GPUs; with a single device it is enough to use the inner module
            for attr in ('detector', 'recognizer'):
                model = getattr(reader, attr, None)
                if isinstance(model, torch.nn.DataParallel):
                    setattr(reader, attr, model.module)
            reader.readtext(np.zeros((64, 256, 3), dtype=np.uint8))
            try_cpu_lstm(reader)
            return reader, device
        except Exception as e:
            logger.warning(f"EasyOCR did not work on '{device}' ({e}). Using the CPU.")
    return with_certificate_fallback(easyocr.Reader, langs, gpu=False), 'cpu'

class EasyOCREngine(BaseOCREngine):
    """
    Default engine for common/Latin-alphabet languages.
    """
    def __init__(self, lang='ja', device='cpu'):
        logger.info("Loading EasyOCR...")
        langs = ['ja', 'en'] if lang == 'ja' else easyocr_languages(lang)
        self.reader, self.device = create_easyocr_reader(langs, device)
        self.lang = lang
        logger.info("EasyOCR engine loaded successfully!")

    def warm_up(self):
        self.reader.readtext(np.zeros((64, 256, 3), dtype=np.uint8))

    def extract_text_boxes(self, image_np, offset_x=0, offset_y=0):
        if image_np is None or image_np.size == 0:
            return []
            
        img_h, img_w = image_np.shape[:2]
        processed_img, scale = preprocess_for_ocr(image_np)
        
        raw_res = self.reader.readtext(
            processed_img, 
            paragraph=False, 
            contrast_ths=0.1, 
            adjust_contrast=0.5,
            link_threshold=0.4,
            low_text=0.4,
            text_threshold=0.7,
            mag_ratio=1.2
        )
        
        if not raw_res:
            return []
            
        # 1. Initial legibility filter and HUD button discard
        parsed_items = []
        for item in raw_res:
            box, txt, score = item[0], item[1].strip(), item[2] if len(item) > 2 else 0.95
            
            # Cleans leading/trailing punctuation noise
            txt = re.sub(r'^[・\s\W_]+', '', txt).strip()
            if not is_meaningful_text(txt, source_lang=self.lang):
                continue
            
            # Discards obvious interface buttons
            if is_hud_element(txt):
                continue
                
            # Discards boxes with a negligible score and very short ones
            if score < 0.1 and len(txt) <= 2:
                continue
                
            x1 = int(min(pt[0] for pt in box) / scale)
            y1 = int(min(pt[1] for pt in box) / scale)
            x2 = int(max(pt[0] for pt in box) / scale)
            y2 = int(max(pt[1] for pt in box) / scale)
            
            w = max(1, x2 - x1)
            h = max(1, y2 - y1)
            
            parsed_items.append({
                'box': box,
                'txt': txt,
                'score': score,
                'x1': x1, 'y1': y1,
                'x2': x2, 'y2': y2,
                'w': w, 'h': h
            })
            
        if not parsed_items:
            return []
            
        # 2. Weighted Median of the Dominant Font Height (H_ref)
        h_ref = calculate_dominant_font_height(parsed_items)
        
        # Scale filter: discards texts that are less than 55% of the main font height
        if h_ref > 8.0:
            parsed_items = [it for it in parsed_items if it['h'] >= (0.55 * h_ref)]
            
        if not parsed_items:
            return []
            
        # 3. Adaptive Separation: Speaker Name/Title vs Main Text
        name_candidates = []
        dialogue_candidates = []
        
        for it in parsed_items:
            # It is a name candidate if:
            # - It is in the top third of the relative ROI (y1 <= 0.35 * img_h)
            # - It is not a long line (w <= 0.38 * img_w)
            # - It contains no dialogue punctuation
            # - It has a reasonable name length
            is_in_top_region = it['y1'] <= (0.35 * img_h)
            is_compact_width = it['w'] <= (0.38 * img_w)
            has_no_sentence_punct = not any(q in it['txt'] for q in ['「', '『', '。', '、', '！', '？', '!', '?'])
            has_name_length = 1 <= len(it['txt']) <= 16
            
            if is_in_top_region and is_compact_width and has_no_sentence_punct and has_name_length:
                name_candidates.append(it)
            else:
                dialogue_candidates.append(it)
                
        results = []
        
        # 4. Speaker name/title (if found)
        if name_candidates:
            for it in name_candidates:
                cleaned_name = clean_character_name(it['txt']) if self.lang == 'ja' else it['txt'].strip()
                adj_box = [[int(pt[0] / scale) + offset_x, int(pt[1] / scale) + offset_y] for pt in it['box']]
                results.append((adj_box, cleaned_name, it['score'], True))

                
        # 5. Spatial grouping of the dialogue lines (removes peripheral scenery text)
        if dialogue_candidates:
            clustered_dialogue = cluster_dialogue_lines(dialogue_candidates, h_ref)
            
            # Sorts dialogue in natural reading order: line by line (quantized Y), left to right (X)
            def get_sort_key(d):
                row_h = max(12.0, 0.6 * h_ref)
                line_row = round(d['y1'] / row_h)
                return (line_row, d['x1'])

            clustered_dialogue = sorted(clustered_dialogue, key=get_sort_key)
            joined_txt = " ".join([d['txt'] for d in clustered_dialogue])
            
            if self.lang == 'ja':
                joined_txt = clean_ocr_punctuation(joined_txt)
                
            all_boxes = [d['box'] for d in clustered_dialogue]
            min_x = min(min(pt[0] for pt in b) for b in all_boxes)
            min_y = min(min(pt[1] for pt in b) for b in all_boxes)
            max_x = max(max(pt[0] for pt in b) for b in all_boxes)
            max_y = max(max(pt[1] for pt in b) for b in all_boxes)
            
            d_box = [
                [int(min_x / scale) + offset_x, int(min_y / scale) + offset_y],
                [int(max_x / scale) + offset_x, int(min_y / scale) + offset_y],
                [int(max_x / scale) + offset_x, int(max_y / scale) + offset_y],
                [int(min_x / scale) + offset_x, int(max_y / scale) + offset_y]
            ]
            results.append((d_box, joined_txt, 0.95, False))
            
        return results

def stitch_ocr_chunks(texts):
    """
    Stitches together pieces of Japanese text read with overlap (sliding window).
    """
    if not texts:
        return ''
    result = texts[0]
    for nxt in texts[1:]:
        if not nxt:
            continue
        sm = SequenceMatcher(None, result, nxt)
        match = sm.find_longest_match(max(0, len(result) - 15), len(result), 0, min(15, len(nxt)))
        # The window overlap is small: only stitches if the repeated piece is
        # at the end of the previous text and at the start of the next (otherwise a repeated "だったり" in
        # another part of the sentence would erase the middle of it)
        at_tail = len(result) - (match.a + match.size) <= 2
        at_head = match.b <= 2
        if match.size >= 2 and at_tail and at_head:
            result = result[:match.a] + nxt[match.b:]
        else:
            result += nxt
    return result

# Boxes much taller than wide are vertical text columns (tate-gaki)
VERTICAL_RATIO = 1.8

def is_vertical_box(w, h):
    return h > VERTICAL_RATIO * w

def order_dialogue_items(items, h_ref):
    """
    Natural reading order: horizontal text top to bottom and left to right;
    vertical text in columns, right to left and top to bottom within each column.
    """
    vertical = [d for d in items if d.get('vertical')]
    if vertical and len(vertical) * 2 > len(items):
        col_w = max(12.0, 0.6 * float(np.median([d['w'] for d in vertical])))
        return sorted(items, key=lambda d: (-round(((d['x1'] + d['x2']) / 2) / col_w), d['y1']))
    row_h = max(12.0, 0.6 * h_ref) if h_ref > 0 else 20.0
    return sorted(items, key=lambda d: (round(d['y1'] / row_h), d['x1']))

SENTENCE_END = '。！？!?」』'
# Dots, ellipses and commas that stylized fonts make the OCR append to short labels
TRAILING_NOISE = '．.・…、，, 　'
# A group of short lines without sentence punctuation is a menu, not a dialogue
MENU_MAX_CHARS = 12
# Regions at least this large (px) are a whole screen: speaker names only exist in dialogue boxes
FULL_SCREEN_MIN_SIZE = (900, 600)

def group_dialogue_blocks(items):
    """
    Splits the text boxes into separate blocks of text: lines close to each other (same dialogue box, same
    paragraph) stay together; distant ones (buttons, labels, other boxes) become their own block.
    A cluster of short lines with no sentence punctuation (menu options) is split into one block per line.
    Returns a list of (items, is_menu_line).
    """
    if not items:
        return []
    font = float(np.median([min(d['w'], d['h']) for d in items]))
    max_gap = 1.2 * font

    parent = list(range(len(items)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(items):
        for j in range(i + 1, len(items)):
            b = items[j]
            gap_x = max(0, a['x1'] - b['x2'], b['x1'] - a['x2'])
            gap_y = max(0, a['y1'] - b['y2'], b['y1'] - a['y2'])
            if gap_x <= max_gap and gap_y <= max_gap:
                parent[find(i)] = find(j)

    clusters = {}
    for i, it in enumerate(items):
        clusters.setdefault(find(i), []).append(it)

    blocks = []
    for cluster in clusters.values():
        is_menu = (len(cluster) >= 2
                   and not any(d.get('vertical') for d in cluster)
                   and all(len(d['txt']) <= MENU_MAX_CHARS and d['txt'].rstrip(TRAILING_NOISE)[-1:] not in SENTENCE_END
                           for d in cluster))
        if is_menu:
            blocks.extend(([d], True) for d in cluster)
        else:
            blocks.append((cluster, False))
    return sorted(blocks, key=lambda b: (min(d['y1'] for d in b[0]), min(d['x1'] for d in b[0])))

def drop_furigana(items):
    """
    Discards small furigana boxes (reading kana) attached to a larger text box:
    in horizontal lines they sit above it; in vertical columns, to its right. They confuse the
    OCR of the main text and would only show up as extra subtitles in the translation.
    """
    def is_furigana_of(small, big):
        if small is big or small.get('is_in_name_pos') or big.get('is_in_name_pos'):
            return False
        if big.get('vertical'):
            # The detector tends to break the furigana column into short (non-vertical) pieces
            if small['w'] >= 0.6 * big['w'] or small['h'] > big['h']:
                return False
            near_right = small['x1'] >= big['x2'] - 0.4 * big['w'] and small['x1'] - big['x2'] < big['w']
            overlap = min(small['y2'], big['y2']) - max(small['y1'], big['y1'])
            return near_right and overlap >= 0.5 * small['h']
        if small.get('vertical') or small['h'] >= 0.6 * big['h'] or small['w'] > big['w']:
            return False
        above = small['y2'] <= big['y1'] + 0.4 * big['h'] and big['y1'] - small['y2'] < big['h']
        inside = small['x1'] >= big['x1'] - 0.5 * big['h'] and small['x2'] <= big['x2'] + 0.5 * big['h']
        return above and inside

    return [s for s in items if not any(is_furigana_of(s, b) for b in items)]

def split_vertical_columns(pil_img):
    """
    Splits a vertical text box into columns (right to left) using the ink gaps
    between them. Very narrow columns next to a main column are treated
    as furigana and discarded. If it does not find more than one column, returns the original image.
    """
    gray = np.array(pil_img.convert("L"), dtype=np.uint8)
    h, w = gray.shape
    if w < 12:
        return [pil_img]

    # Ink = pixels that stand apart from the background (works for light or dark text)
    dev = np.abs(gray.astype(np.int16) - int(np.median(gray))).astype(np.uint8)
    _, ink = cv2.threshold(dev, 0, 1, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    profile = ink.sum(axis=0) / float(h)
    has_ink = profile > 0.02

    segments = []
    start = None
    for x in range(w):
        if has_ink[x] and start is None:
            start = x
        elif not has_ink[x] and start is not None:
            segments.append([start, x])
            start = None
    if start is not None:
        segments.append([start, w])
    if len(segments) < 2:
        return [pil_img]

    # Joins pieces separated by tiny gaps (spaces inside the same character)
    widest = max(b - a for a, b in segments)
    merged = [segments[0]]
    for a, b in segments[1:]:
        if a - merged[-1][1] < 0.15 * widest:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    if len(merged) < 2:
        return [pil_img]

    # Discards narrow columns (furigana or noise)
    widest = max(b - a for a, b in merged)
    merged = [(a, b) for a, b in merged if (b - a) >= 0.45 * widest]
    if len(merged) < 2 and merged and (merged[0][1] - merged[0][0]) >= w * 0.9:
        return [pil_img]

    columns = []
    for a, b in sorted(merged, key=lambda s: -s[0]):  # right to left
        columns.append(pil_img.crop((max(0, a - 4), 0, min(w, b + 4), h)))
    return columns

def _is_jp_char(c):
    return unicodedata.name(c, '').startswith(('HIRAGANA', 'KATAKANA', 'CJK'))

def _script_counts(text):
    """(Latin letters, Japanese characters) of a text, ignoring full-width forms."""
    norm = unicodedata.normalize('NFKC', text)
    latin = sum(1 for c in norm if c.isascii() and c.isalpha())
    jp = sum(1 for c in norm if _is_jp_char(c))
    return latin, jp

def pick_name_text(easy_txt, manga_txt, padded_txt=None):
    """
    Chooses the speaker name reading between EasyOCR and MangaOCR according to the script.
    MangaOCR only knows Japanese and "hallucinates" a kana in the middle of Latin names,
    so the decision is by proportion. For Latin names, EasyOCR wins, with no Japanese leftovers.
    """
    easy = (padded_txt or easy_txt or '').strip()
    e_lat, e_jp = _script_counts(easy)
    m_lat, m_jp = _script_counts(manga_txt)

    if e_jp == 0 and e_lat >= 3:
        return clean_character_name(easy)  # EasyOCR read only Latin letters
    if m_jp >= 2 and m_jp > m_lat:
        return clean_character_name(manga_txt)  # Japanese name
    if e_lat >= 2 and e_lat > e_jp:
        return clean_character_name(''.join(c for c in easy if not _is_jp_char(c)))  # Latin name
    if m_jp >= 1:
        return clean_character_name(manga_txt)
    norm_m = unicodedata.normalize('NFKC', manga_txt).strip()
    return clean_character_name(easy if len(easy) >= 2 else norm_m)

def strip_latin_runs(text):
    """
    Removes English leftovers inside a Japanese dialogue box (e.g. the end of an English
    subtitle that stayed glued to the same box and was "read" by MangaOCR as Latin letters).
    Only acts on long runs of Latin letters; short acronyms such as HP or OK remain.
    """
    latin = 'A-Za-zＡ-Ｚａ-ｚ'
    cleaned = re.sub(f"[{latin}][{latin}．，！？’'-]{{5,}}", '', text)
    return cleaned.strip() if contains_japanese(cleaned) else text

def is_english_subtitle(easy_txt, manga_txt):
    """
    Identifies whether the box is a subtitle or English text that must be ignored in the JP translation.
    """
    jp_pattern = r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]'

    # 1. MangaOCR returned predominantly Latin letters (e.g. ｔｈｅｎｅｘｔ... in full width).
    # MangaOCR only knows Japanese: when reading English it "hallucinates" garbage with one or another
    # Japanese letter left over, so what matters is the proportion, not the total absence of Japanese characters.
    norm_manga = unicodedata.normalize('NFKC', manga_txt).strip()
    latin_chars_manga = sum(1 for c in norm_manga if c.isascii() and c.isalpha())
    jp_chars_manga = len(re.findall(jp_pattern, norm_manga))
    if latin_chars_manga >= 4 and latin_chars_manga > jp_chars_manga:
        return True

    # 2. EasyOCR saw only Latin letters in the box
    latin_chars_easy = sum(1 for c in easy_txt if c.isascii() and c.isalpha())
    jp_chars_easy = len(re.findall(jp_pattern, easy_txt))
    if latin_chars_easy >= 6 and jp_chars_easy == 0:
        return True
    if latin_chars_easy >= 4 and jp_chars_easy <= 1 and not contains_japanese(manga_txt):
        return True

    return False

class MangaOCREngine(BaseOCREngine):
    """
    Default engine for the Japanese script.
    Also uses EasyOCR.
    """
    def __init__(self, device='cpu'):
        import manga_ocr
        logger.info("Loading MangaOCR + CRAFT Detector...")
        self.detector, self.device = create_easyocr_reader(['ja', 'en'], device)
        # Always loads on the CPU and moves to the chosen device (includes Intel XPU,
        # which manga_ocr does not select on its own)
        self.mocr = manga_ocr.MangaOcr(force_cpu=True)
        self.crop_cache = OrderedDict()
        self.last_timings = {}
        if self.device != 'cpu':
            try:
                self.mocr.model.to(self.device)
                self._recognize_batch([Image.new("RGB", (120, 48), "white")])  # warm-up
                self._try_half_precision()
                self._try_half_detector()
            except Exception as e:
                logger.warning(f"MangaOCR did not work on '{self.device}' ({e}). Using the CPU.")
                self.mocr.model.to('cpu')
                self.device = 'cpu'
        logger.info("Japanese MangaOCR engine loaded successfully!")


    BATCH_SIZE = 16
    CROP_CACHE_SIZE = 256

    def _try_half_precision(self):
        """
        fp16 on the GPU cuts the autoregressive decoding time (about 25% on small batches, which is the usual case)
        with identical readings in tests; falls back to fp32 if the device does not handle it.
        """
        if self.device not in ('cuda', 'xpu'):
            return
        model = self.mocr.model
        probe = Image.new("RGB", (240, 48), "white")
        try:
            expected = self._recognize_batch([probe])
            model.half()
            if self._recognize_batch([probe]) != expected:
                raise RuntimeError("fp16 reading differs from fp32")
            logger.info("MangaOCR running in half precision (fp16).")
        except Exception as e:
            logger.warning(f"fp16 not usable on '{self.device}' ({e}); keeping fp32.")
            model.float()

    def _try_half_detector(self):
        """
        CRAFT in fp16: about 30% faster detection. Kept only if it finds the same boxes as fp32 on a test image.
        """
        craft = getattr(self.detector, 'detector', None)
        if craft is None or self.device not in ('cuda', 'xpu'):
            return
        probe = np.zeros((128, 512, 3), dtype=np.uint8)
        cv2.putText(probe, "HELLO WORLD 123", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 4)

        def to_float(out):
            if torch.is_tensor(out):
                return out.float()
            return type(out)(to_float(o) for o in out) if isinstance(out, (tuple, list)) else out

        handles = []
        try:
            expected = [np.array(box) for box, *_ in self.detector.readtext(probe)]
            craft.half()
            handles.append(craft.register_forward_pre_hook(
                lambda m, args: tuple(a.half() if torch.is_tensor(a) and a.is_floating_point() else a for a in args)))
            handles.append(craft.register_forward_hook(lambda m, args, out: to_float(out)))
            got = [np.array(box) for box, *_ in self.detector.readtext(probe)]
            if len(got) != len(expected) or any(np.abs(a - b).max() > 3 for a, b in zip(got, expected)):
                raise RuntimeError("fp16 boxes differ from fp32")
            logger.info("CRAFT detector running in half precision (fp16).")
        except Exception as e:
            logger.warning(f"fp16 detector not usable on '{self.device}' ({e}); keeping fp32.")
            for h in handles:
                h.remove()
            craft.float()

    # Sample dialogue for the shape warm-up: lengths vary so the recognizer sees many box widths and batch sizes
    WARMUP_TEXT = "今日はとても良い天気ですね本当にそれでいいのですか私はまだ迷っていますでもあなたがそう言うなら信じます"
    WARMUP_MAX_RATIO = 24
    WARMUP_FONTS = ("YuGothB.ttc", "meiryo.ttc", "msgothic.ttc")

    def warm_up(self, shapes=None):
        """
        Loads the models and, given the (width, height) of the capture regions, pre-compiles the GPU kernels for those
        sizes: each new input shape costs seconds on the first use (detector for a new frame size, recognizer for each new
        box width), and that used to land on the user's first dialogues.
        """
        self.detector.readtext(np.zeros((128, 512, 3), dtype=np.uint8))
        with torch.inference_mode():
            self._recognize_batch([Image.new("RGB", (240, 48), "white")])
        if self.device == 'cpu':
            return
        for i, (w, h) in enumerate(shapes or []):
            try:
                self._warm_shape(int(w), int(h), full=(i == 0))
            except Exception as e:
                logger.debug(f"Shape warm-up {w}x{h} failed: {e}")
        self.crop_cache.clear()

    def _warm_shape(self, width, height, full):
        """Compiles the kernels for a region size: detector (frame size), recognizer (box width x batch) and MangaOCR (batch)."""
        from PIL import ImageDraw, ImageFont
        if width < 64 or height < 48:
            return
        self.extract_text_boxes(np.full((height, width, 3), 30, np.uint8))  # frame-size kernels of the detector
        if not full:  # recognizer and MangaOCR shapes do not depend on the region: the first one is enough
            return
        # Recognizer: each box is read on its own and resized to a height of 64, so the only shape that varies is
        # ceil(width / height); with several boxes per batch the combinations would be too many to pre-compile
        box_h = 40
        for ratio in range(1, min(self.WARMUP_MAX_RATIO, width // 8) + 1):
            gray = np.zeros((box_h + 10, box_h * ratio + 10), np.uint8)
            self.detector.recognize(gray, horizontal_list=[[0, box_h * ratio, 0, box_h]], free_list=[], batch_size=1)
        # MangaOCR: one model pass per batch size, decoding a realistic number of tokens
        size = 40
        font = None
        for name in self.WARMUP_FONTS:
            try:
                font = ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name), size)
                break
            except OSError:
                continue
        if font is None:
            font = ImageFont.load_default(size)
        crops = []
        for chars in (8, 20, 50):
            crop = Image.new("RGB", (size * chars, size + 16), (30, 30, 50))
            ImageDraw.Draw(crop).text((8, 6), self.WARMUP_TEXT[:chars], font=font, fill=(255, 255, 255))
            crops.append(crop)
        with torch.inference_mode():
            for count in range(1, 9):
                self._recognize_batch([crops[i % len(crops)] for i in range(count)])
            self._recognize_batch(crops[-1:])

    @staticmethod
    def _strip_windows(length):
        """Reading windows (start, end) of a strip with the given length (width or height)."""
        if length <= 360:
            return [(0, length)]
        windows = []
        for start in range(0, length, 260):
            end = min(length, start + 340)
            windows.append((start, end))
            if end == length:
                break
        return windows

    def _recognize_batch(self, pil_imgs):
        """Runs MangaOCR in batches (one model pass per BATCH_SIZE crops)."""
        mocr = self.mocr
        texts = []
        for i in range(0, len(pil_imgs), self.BATCH_SIZE):
            group = pil_imgs[i:i + self.BATCH_SIZE]
            pixels = torch.stack([mocr._preprocess(im.convert("L").convert("RGB")) for im in group])
            out = mocr.model.generate(pixels.to(mocr.model.device, mocr.model.dtype), max_length=300).cpu()
            for ids in out:
                texts.append(manga_ocr_post_process(mocr.tokenizer.decode(ids, skip_special_tokens=True)))
        return texts

    def _read_strips(self, pil_imgs, vertical=None):
        """
        Reads several strips in a single batch, applying the stitching of the sliding windows.
        `vertical` says, for each strip, whether it is vertical text (by default, decided by the aspect ratio).
        """
        if vertical is None:
            vertical = [is_vertical_box(*img.size) for img in pil_imgs]
        # Strips identical to ones already read (e.g. earlier lines while typing) come from the cache
        keys = [self._crop_key(img) + (bool(v),) for img, v in zip(pil_imgs, vertical)]
        todo = [i for i, k in enumerate(keys) if k not in self.crop_cache]
        if todo:
            fresh = self._read_strips_uncached([pil_imgs[i] for i in todo], [vertical[i] for i in todo])
            for i, text in zip(todo, fresh):
                self.crop_cache[keys[i]] = text
                if len(self.crop_cache) > self.CROP_CACHE_SIZE:
                    self.crop_cache.popitem(last=False)
        for k in keys:
            self.crop_cache.move_to_end(k)
        return [self.crop_cache[k] for k in keys]

    @staticmethod
    def _crop_key(img):
        return (img.size, hashlib.blake2b(img.tobytes(), digest_size=16).digest())

    def _read_strips_uncached(self, pil_imgs, vertical):
        # Vertical boxes become one unit per column (read right to left)
        units = []
        for i, (img, is_vert) in enumerate(zip(pil_imgs, vertical)):
            parts = split_vertical_columns(img) if is_vert else [img]
            units.extend((i, part) for part in parts)

        crops, spans = [], []
        for _, img in units:
            w, h = img.size
            start = len(crops)
            vertical = is_vertical_box(w, h)
            length = h if vertical else w
            for a, b in self._strip_windows(length):
                if length <= 360:
                    crops.append(img)
                elif vertical:
                    crops.append(img.crop((0, a, w, b)))
                else:
                    crops.append(img.crop((a, 0, b, h)))
            spans.append((start, len(crops)))

        with torch.inference_mode():
            texts = [t.strip() for t in self._recognize_batch(crops)]

        results = []
        for start, end in spans:
            chunk_texts = texts[start:end]
            if len(chunk_texts) == 1:
                results.append(chunk_texts[0])
                continue
            chunks = []
            for t in chunk_texts:
                if t and t not in ['...', '…', '‥']:
                    chunks.append(t)
                if t and t.endswith('」'):
                    break
            results.append(stitch_ocr_chunks(chunks))

        merged = [""] * len(pil_imgs)
        for (i, _), text in zip(units, results):
            merged[i] += text
        return merged

    def _read_name_padded(self, gray, x1, y1, x2, y2, tight_txt):
        """
        Re-reads the name with a side margin: the detector's tight box sometimes cuts off the first
        or the last letter. Returns None if there is no better reading.
        """
        try:
            img_h, img_w = gray.shape[:2]
            pad_x = max(8, int(0.5 * (y2 - y1)))
            pad_y = 3
            region = [max(0, x1 - pad_x), min(img_w, x2 + pad_x), max(0, y1 - pad_y), min(img_h, y2 + pad_y)]
            result = self.detector.recognize(gray, horizontal_list=[region], free_list=[])
            if result:
                text = result[0][1].strip()
                if len(text) >= len(tight_txt.strip()):
                    return text
        except Exception as e:
            logger.debug(f"Name re-read with margin failed: {e}")
        return None

    def extract_text_boxes(self, image_np, offset_x=0, offset_y=0):
        if image_np is None or image_np.size == 0:
            return []
            
        img_h, img_w = image_np.shape[:2]
        pil_img = Image.fromarray(image_np)
        
        # 1. Geometric box detection with CRAFT, then EasyOCR's quick reading of each box (what readtext does,
        # split so each step is timed and the grayscale frame is reused for the name re-read)
        from easyocr.utils import reformat_input
        t0 = time.perf_counter()
        img, gray = reformat_input(image_np)
        horizontal, free = self.detector.detect(
            img,
            link_threshold=0.4,
            low_text=0.4,
            text_threshold=0.7,
            mag_ratio=DETECT_MAG_RATIO,
            canvas_size=DETECT_CANVAS_SIZE,
            reformat=False,
        )
        t1 = time.perf_counter()
        raw_res = self.detector.recognize(
            gray, horizontal[0], free[0],
            paragraph=False,
            contrast_ths=0.1,
            adjust_contrast=0.5,
            batch_size=1,  # one box at a time: batching makes every new box count/width combination a slow GPU recompile
            reformat=False,
        )
        self.last_timings['detect'] = t1 - t0
        self.last_timings['recognize'] = time.perf_counter() - t1
        
        if not raw_res:
            return []
            
        # Phase 1: filters the detected boxes and prepares the crops
        pending = []
        
        for item in raw_res:
            box, easy_txt, score = item[0], item[1].strip(), item[2] if len(item) > 2 else 0.95
            
            # HUD button filter
            if is_hud_element(easy_txt):
                continue
                
            x1 = max(0, int(min(pt[0] for pt in box)))
            y1 = max(0, int(min(pt[1] for pt in box)))
            x2 = min(img_w, int(max(pt[0] for pt in box)))
            y2 = min(img_h, int(max(pt[1] for pt in box)))
            
            w = max(1, x2 - x1)
            h = max(1, y2 - y1)
            
            # Discards microscopic noise
            if w < 8 or h < 8:
                continue


            # 1. Name/Title or Speaker identification (label anchored to the top-left corner)
            vertical = is_vertical_box(w, h)
            if not vertical and h > 0.9 * w and w >= 40:
                # A nearly square box may be a block of several vertical columns
                columns = split_vertical_columns(pil_img.crop((x1, y1, x2, y2)))
                vertical = len(columns) >= 2 and all(c.height > 2.0 * c.width for c in columns)
            full_screen = img_w >= FULL_SCREEN_MIN_SIZE[0] and img_h >= FULL_SCREEN_MIN_SIZE[1]
            is_in_name_pos = (not full_screen) and (not vertical) and (x1 <= 0.15 * img_w) and (y1 <= 0.30 * img_h) and (h >= 22) and ((w / max(1, h)) <= 5.0)

            
            # 2. Ultra-fast pre-filter for English subtitles (0.00ms) BEFORE running MangaOCR:
            if not is_in_name_pos:
                ascii_letters = sum(1 for c in easy_txt if c.isascii() and c.isalpha())
                jp_chars = len(re.findall(r'[぀-ゟ゠-ヿ一-龯]', easy_txt))
                if score >= 0.20 and ((ascii_letters >= 4 and jp_chars <= 1) or (ascii_letters >= 2 and jp_chars == 0)):
                    # Secondary subtitle discarded instantly, saving heavy inference!
                    continue
            
            # Slight margin to read without cutting off the edges
            pad_x1 = max(0, x1 - 4)
            pad_y1 = max(0, y1 - 4)
            pad_x2 = min(img_w, x2 + 4)
            pad_y2 = min(img_h, y2 + 4)
            
            pending.append({
                'crop': pil_img.crop((pad_x1, pad_y1, pad_x2, pad_y2)),
                'box': box, 'easy_txt': easy_txt, 'score': score,
                'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2, 'w': w, 'h': h,
                'is_in_name_pos': is_in_name_pos, 'vertical': vertical
            })

        # Furigana attached to the main text does not need (and must not) be read
        pending = drop_furigana(pending)

        if not pending:
            return []

        # Phase 2: reads all the crops in a batch
        t0 = time.perf_counter()
        read_texts = self._read_strips([p['crop'] for p in pending], [p['vertical'] for p in pending])
        self.last_timings['ocr'] = time.perf_counter() - t0

        # Phase 3: classification into name / dialogue
        name_candidates = []
        dialogue_items = []

        for p, manga_txt in zip(pending, read_texts):
            box, easy_txt, score = p['box'], p['easy_txt'], p['score']
            x1, y1, x2, y2, w, h = p['x1'], p['y1'], p['x2'], p['y2'], p['w'], p['h']
            is_in_name_pos = p['is_in_name_pos']

            if is_in_name_pos:
                # Names can be Western or Japanese
                padded_txt = self._read_name_padded(gray, x1, y1, x2, y2, easy_txt)
                final_name = pick_name_text(easy_txt, manga_txt, padded_txt)

                if final_name:
                    name_box = [
                        [x1 + offset_x, y1 + offset_y],
                        [x2 + offset_x, y1 + offset_y],
                        [x2 + offset_x, y2 + offset_y],
                        [x1 + offset_x, y2 + offset_y]
                    ]
                    name_candidates.append((name_box, final_name, score, True))
                continue
                
            # Secondary filter in case it got past the pre-filter
            if is_english_subtitle(easy_txt, manga_txt):
                continue
                
            manga_txt = strip_latin_runs(manga_txt)
            # Version numbers, counters and other text that is not Japanese is not worth translating
            if not contains_japanese(manga_txt):
                continue
            if manga_txt and manga_txt not in ['...', '…', '‥']:
                dialogue_items.append({
                    'box': box,
                    'txt': manga_txt,
                    'score': score,
                    'x1': x1, 'y1': y1,
                    'x2': x2, 'y2': y2,
                    'w': w, 'h': h,
                    'vertical': p['vertical']
                })
                
        results = []
        if name_candidates:
            # Selects the most confident / leftmost name
            best_name = min(name_candidates, key=lambda n: n[0][0][0])
            results.append(best_name)
            
        # Each separate block of text (dialogue box, button, label) is its own result
        for block, is_menu in group_dialogue_blocks(dialogue_items):
            h_ref = calculate_dominant_font_height(block)
            block = order_dialogue_items(block, h_ref)

            full_txt = " ".join([d['txt'] for d in block])
            if is_menu:
                full_txt = full_txt.rstrip(TRAILING_NOISE) or full_txt
            else:
                full_txt = clean_ocr_punctuation(full_txt)

            all_boxes = [d['box'] for d in block]
            min_x = min(min(pt[0] for pt in b) for b in all_boxes)
            min_y = min(min(pt[1] for pt in b) for b in all_boxes)
            max_x = max(max(pt[0] for pt in b) for b in all_boxes)
            max_y = max(max(pt[1] for pt in b) for b in all_boxes)

            d_box = [
                [int(min_x) + offset_x, int(min_y) + offset_y],
                [int(max_x) + offset_x, int(min_y) + offset_y],
                [int(max_x) + offset_x, int(max_y) + offset_y],
                [int(min_x) + offset_x, int(max_y) + offset_y]
            ]
            results.append((d_box, full_txt, 0.98, False))

        return results

# ==========================================
# 2. TRANSLATION ENGINE AND MANAGER (FACTORY)
# ==========================================

class TranslationEngine:
    """
    Translation engine:
    1. Primary: Groq AI (Qwen-2.5 27B) - contextual OCR self-correction and natural language for general content (interfaces, documents, videos and games)
    2. Secondary: classic fallback to MyMemory / Google Translate if offline or without a key
    """
    DEFAULT_GROQ_MODELS = ["qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
    # A request that hangs must fail quickly so the line goes to the backup translators (the circuit breaker handles repeats)
    GROQ_TIMEOUT = 5.0
    # deep_translator sends its requests without a timeout: a backup that hangs is abandoned after this long
    FALLBACK_TIMEOUT = 6.0

    def __init__(self, source='ja', target='pt', groq_models=None):
        # List of Groq models in order of preference (e.g. ["llama-3.1-8b-instant"] for low latency)
        if isinstance(groq_models, str):
            groq_models = [groq_models]
        self.groq_models = list(groq_models) if groq_models else list(self.DEFAULT_GROQ_MODELS)
        self.source = source[:2].lower()
        self.target = target[:2].lower()
        self.glossary = Glossary(self.source, self.target)
        
        # 1. Tries to initialize the Groq client
        self.groq_client = None
        # Stops trying Groq for a while after a rate limit or repeated failures (the lines then go straight to the backup)
        self.groq_breaker = CircuitBreaker("Groq")
        self.refresh_groq_client()

                
        # 2. Instantiates traditional fallback providers
        src_tag = language(self.source).mymemory
        tgt_tag = language(self.target).mymemory
        
        try:
            self.mymemory = MyMemoryTranslator(source=src_tag, target=tgt_tag)
        except Exception:
            self.mymemory = None
            
        try:
            self.google = GoogleTranslator(source=language(self.source).google, target=language(self.target).google)
        except Exception:
            self.google = None
        self._fallback_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="fallback")
        
    def refresh_groq_client(self):
        """(Re)creates the Groq client from the saved key; without a key, only the classic translators are used."""
        self.groq_client = None
        groq_key = secrets_store.groq_key()
        if groq_key:
            try:
                from groq import Groq
                self.groq_client = Groq(api_key=groq_key, timeout=self.GROQ_TIMEOUT, max_retries=0)
                self.groq_breaker.record_success()  # a new key deserves a fresh start
                logger.info("AI Translation Engine enabled (Groq - Qwen)!")
            except Exception as e:
                logger.warning(f"Warning while initializing Groq ({type(e).__name__}). Using traditional mode.")

    def warm_up(self):
        """Opens the HTTPS connection to Groq (DNS + TLS) without spending tokens, so the first translation comes out faster."""
        if self.groq_client:
            try:
                self.groq_client.models.list()
            except Exception as e:
                logger.debug(f"Groq pre-connection failed: {e}")

    def translate(self, text, is_name=False):
        return self.translate_with_info(text, is_name)[0]

    @staticmethod
    def _is_rate_limit(error):
        return getattr(error, "status_code", None) == 429 or "rate limit" in str(error).lower()

    @staticmethod
    def _retry_after(error):
        """Seconds the service asked to wait (Retry-After header), or None."""
        try:
            return float(error.response.headers.get("retry-after"))
        except Exception:
            return None

    @staticmethod
    def _context_prompt(context):
        """Prompt section with the previous lines and the current speaker (empty if there is no context)."""
        if not context:
            return ""
        lines = []
        for speaker, original, translated in context.get('history', []):
            who = f"{speaker}: " if speaker else ""
            lines.append(f"- {who}{original[:120]} → {translated[:120]}")
        text = ""
        if lines:
            text += (
                "\nConversation context (previous lines, already translated):\n" + "\n".join(lines) +
                "\nThe line to translate continues this conversation. If the original omits the subject, work out who or "
                "what is being talked about from the previous lines and agree gender and number in the translation (he/she, etc.). "
                "Translate only the current line; never repeat the previous ones."
            )
        if context.get('speaker'):
            text += f"\nWho is speaking now: {context['speaker']}"
        return text

    def _fallback(self, translator, text):
        """Calls a backup translator with a time limit; None if it fails, hangs or returns an error page."""
        try:
            res = self._fallback_pool.submit(translator.translate, text).result(timeout=self.FALLBACK_TIMEOUT)
        except FutureTimeout:
            logger.debug(f"{type(translator).__name__} took more than {self.FALLBACK_TIMEOUT:.0f} s; skipped.")
            return None
        except Exception:
            return None
        if res and not any(err in res.lower() for err in ["error 500", "server error", "please try again"]):
            return res.strip()
        return None

    def translate_with_info(self, text, is_name=False, context=None, terms=None):
        """
        Translates and reports who answered: (text, {'engine': 'Groq'|'MyMemory'|'Google'|'failed',
        'ms': latency, 'limited': True if Groq refused because of a request rate limit}).
        `context` ({'history': [(speaker, original, translation)], 'speaker': name}) only applies to the AI and to dialogue lines.
        `terms` are the glossary matches, when the caller already has them.
        """
        t0 = time.time()
        limited = False

        def info(engine):
            return {'engine': engine, 'ms': (time.time() - t0) * 1000, 'limited': limited}

        text = text.strip()
        if not text:
            return "", info('cache')

        # Fixed glossary terms that appear in this text
        if terms is None:
            terms = self.glossary.matches(text)
            
        # Attempt 1: Translation with Contextual AI (Groq), unless the circuit is open
        use_groq = self.groq_client is not None and self.groq_breaker.allow()
        if self.groq_client is not None and not use_groq:
            limited = self.groq_breaker.rate_limited  # keeps the rate limit warning while the circuit is open
        if use_groq:
            source_name = language(self.source).prompt
            target_name = language(self.target).prompt
            
            if is_name:
                system_prompt = (
                    f"You are a general translator and a high-precision localization specialist ({source_name} to {target_name}). "
                    f"You can translate any kind of content shown on screen (software interfaces, documents, visual media and video games).\n"
                    f"The provided text is the name of a person, interlocutor, author or character captured via real-time screen OCR, and may contain small character distortions caused by stylized fonts or visual compression.\n"
                    f"Rules:\n"
                    f"1. If it is a proper name of a person or character (real or fictional), deduce the established spelling and keep it without translating it literally (e.g. Cloud, Arthur, Tanaka, etc.).\n"
                    f"2. If it is a job title, profession, title or role description (e.g. 'Guard', 'Blacksmith', 'Director', 'Elder'), translate it naturally into {target_name}.\n"
                    f"3. Return EXCLUSIVELY the final name, with no quotes and no additional explanations."
                )
            else:
                system_prompt = (
                    f"You are a general translator and a high-precision localization specialist ({source_name} to {target_name}). "
                    f"You can translate any content shown on screen in real time, including interfaces, systems, documents, subtitles, videos and video games.\n"
                    f"The provided text was captured by real-time screen OCR. Because of stylized fonts, visual effects or background elements, the OCR may contain small visual character swaps or imperfect punctuation.\n"
                    f"Guidelines:\n"
                    f"1. Identify the intended text or line in the overall context of the screen, interface or narrative (including game dialogue when applicable), silently correcting any character swaps or noise caused by the OCR.\n"
                    f"2. Produce a fluent, precise and natural translation into {target_name}, faithfully preserving the tone, meaning and style of the original text.\n"
                    f"3. Return EXCLUSIVELY the direct final translation, with no quotes, no explanatory notes and no additional comments."
                )

                
            if not is_name:
                system_prompt += self._context_prompt(context)

            if terms:
                system_prompt += (
                    "\nMandatory glossary (use exactly these translations for these terms):\n"
                    + "\n".join(f"- {k} → {v}" for k, v in terms.items())
                )

            errors, retry_after = 0, None
            for model_candidate in self.groq_models:
                try:
                    res = self.groq_client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": text}
                        ],
                        model=model_candidate,
                        max_tokens=150,
                        temperature=0.1,
                        # gpt-oss reasons before answering: without this, the reasoning eats the token budget and cuts the line
                        **({"reasoning_effort": "low"} if model_candidate.startswith("openai/gpt-oss") else {}),
                    )
                    translated = res.choices[0].message.content.strip()
                    # Removes quotes if the AI added them
                    if (translated.startswith('"') and translated.endswith('"')) or (translated.startswith('「') and translated.endswith('」')):
                        translated = translated[1:-1].strip()
                    if translated:
                        self.groq_breaker.record_success()
                        return translated, info('Groq')
                except Exception as e:
                    errors += 1
                    limited = limited or self._is_rate_limit(e)
                    retry_after = retry_after or self._retry_after(e)
                    logger.debug(f"Groq ({model_candidate}) failed: {e}")
                    continue

            # No model answered: errors count against the circuit; an empty reply still means the service is up
            if errors:
                self.groq_breaker.record_failure(rate_limited=limited, retry_after=retry_after)
            else:
                self.groq_breaker.record_success()
                    
        # Classic translators do not accept instructions: applies the glossary by swapping the terms in the text
        fallback_text = text
        for k, v in terms.items():
            fallback_text = fallback_text.replace(k, v)

        # Attempt 2: Fallback to MyMemory
        if self.mymemory:
            res = self._fallback(self.mymemory, fallback_text)
            if res:
                return res, info('MyMemory')

        # Attempt 3: Fallback to Google
        if self.google:
            res = self._fallback(self.google, fallback_text)
            if res:
                return res, info('Google')

        return "[Translating...]", info('failed')

class OCRTranslator:
    """
    System facade / manager:
    Creates the ideal engine and handles the cache and the translation.
    - source_lang == 'ja': Uses MangaOCREngine (MangaOCR + CRAFT Detector that drops EN subtitles)
    - source_lang != 'ja': Uses EasyOCREngine (engine for Latin-alphabet languages)
    """
    def __init__(self, source_lang='ja', target_lang='en', device_preference='auto', groq_models=None,
                 context_lines=3, warm_shapes=None):
        device, device_label = resolve_device(device_preference)
        logger.info(f"Initializing Translator... (device: {device_label})")
        
        self.source_lang = source_lang
        self.target_lang = target_lang
        
        if source_lang == 'ja':
            self.engine = MangaOCREngine(device=device)
        else:
            self.engine = EasyOCREngine(lang=source_lang, device=device)

        # The engine may have gone back to the CPU if the GPU failed
        self.device = self.engine.device
        self.device_label = device_label if self.device == device else resolve_device('cpu')[1]
            
        self.translator = TranslationEngine(source=source_lang, target=target_lang, groq_models=groq_models)
        
        self.translation_cache = {}
        self.name_memory = NameMemory()
        self.disk_cache = PersistentTranslationCache()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="translate")
        # Background translation jobs; separate from the request pool, so a job never waits for a slot it holds
        self._jobs = ThreadPoolExecutor(max_workers=2, thread_name_prefix="translate-job")
        # Guards the region state and the context shared with those jobs
        self._lock = threading.Lock()
        # Scene stability state per capture region (None = single region)
        self._region_state = {}
        # Previous lines already translated, per region, sent to the AI as context (0 disables)
        self.context_lines = max(0, int(context_lines))
        self._context = {}
        self.last_translation_info = None

        self.warm_up(warm_shapes)
        
        logger.info(f"Translator ready to use! (Target: {target_lang.upper()}, device: {self.device_label})")


    def set_glossary_file(self, filename=None):
        """Uses a dedicated glossary (file at the project root) or goes back to the default glossary.json."""
        from glossary import GLOSSARY_FILE
        path = GLOSSARY_FILE
        if filename:
            path = os.path.join(os.path.dirname(GLOSSARY_FILE), os.path.basename(filename))
        self.translator.glossary = Glossary(self.translator.source, self.translator.target, path)

    def warm_up(self, shapes=None):
        """Warms up OCR and the API connection in parallel; failures here never prevent use."""
        t0 = time.time()
        net = self._pool.submit(self.translator.warm_up)
        try:
            if shapes and isinstance(self.engine, MangaOCREngine):
                self.engine.warm_up(shapes)
            else:
                self.engine.warm_up()
        except Exception as e:
            logger.warning(f"OCR warm-up failed ({e}); the first read will be slower.")
        net.result()
        logger.info(f"Warm-up finished in {time.time() - t0:.1f}s")

    # Short lines ("はい", "そう") depend on context: their cache takes the previous lines into account
    SHORT_LINE_CHARS = 8

    def _build_context(self, region_key, current_text, speaker):
        """Previous lines of the region (without the continuation of the current line) to give the AI context."""
        if self.context_lines <= 0:
            return None
        history = [h for h in self._context.get(region_key, ())
                   if compute_text_similarity(h[1], current_text) < 0.7][-self.context_lines:]
        if not history and not speaker:
            return None
        return {'history': history, 'speaker': speaker}

    def _remember_line(self, region_key, speaker, original, translated):
        """Stores the translated line; the continuation of the same line (typewriter effect) replaces the previous one."""
        if self.context_lines <= 0 or not original or not translated or translated.startswith("["):
            return
        lines = self._context.setdefault(region_key, deque(maxlen=self.context_lines + 2))
        entry = (speaker, original, translated)
        if lines and compute_text_similarity(lines[-1][1], original) >= 0.7:
            lines[-1] = entry
        else:
            lines.append(entry)

    @staticmethod
    def _context_tag(context):
        if not context or not context['history']:
            return ""
        raw = "|".join(h[1] for h in context['history'])
        return "@" + hashlib.blake2b(raw.encode("utf-8"), digest_size=4).hexdigest()

    def _summarize_translation(self, outcomes):
        """Summarizes the cycle's translations: the engine that answered, the highest latency and whether it fell back to the backup."""
        if not outcomes:
            return {'engine': 'cache', 'ms': 0.0, 'fallback': False, 'limited': False}
        infos = [info for _, info in outcomes]
        engines = {i['engine'] for i in infos}
        # When mixed, shows the worst case (which signals a problem with the AI)
        engine = next((e for e in ('failed', 'Google', 'MyMemory', 'Groq') if e in engines), 'cache')
        return {
            'engine': engine,
            'ms': max(i['ms'] for i in infos),
            'fallback': self.translator.groq_client is not None and engine != 'Groq',
            'limited': any(i['limited'] for i in infos),
        }

    def _new_generation(self, st, results=None, translating=False):
        """Marks a new reading of the region: translations still running for an older reading are dropped when they arrive."""
        with self._lock:
            st['gen'] += 1
            st['translating'] = translating
            if results is not None:
                st['results'] = results
            return st['gen']

    def process_image(self, image_data, offset_x=0, offset_y=0, on_intermediate=None, force_reload=False,
                      should_abort_translation=None, region_key=None, on_translated=None):
        """
        Reads the image and translates what is new. Returns the results, [] when there is no text, or None when there is
        nothing final yet: the translation was deferred (text still being typed) or, given `on_translated`, it runs in the
        background and arrives as on_translated(results, info), so the caller can go on reading the screen meanwhile.
        """
        st = self._region_state.setdefault(region_key, {'raw': "", 'results': [], 'gen': 0, 'translating': False})
        self.last_translation_info = None

        if isinstance(image_data, str):
            if not os.path.exists(image_data):
                return []
            image_data = cv2.imread(image_data)
            if image_data is None:
                return []
            image_data = cv2.cvtColor(image_data, cv2.COLOR_BGR2RGB)

        if force_reload:
            st['raw'] = ""
            self._new_generation(st, [])
            self.translation_cache.clear()

        start_time = time.time()

        boxes = self.engine.extract_text_boxes(image_data, offset_x=offset_x, offset_y=offset_y)
        t_engine = time.time() - start_time

        if not boxes:
            st['raw'] = ""
            self._new_generation(st, [])
            return []

        all_texts = " | ".join([item[1] for item in boxes])

        # Scene Stability Lock (Fuzzy Match / Anti-Jitter)
        # If the current text is similar to the previous frame (>= 65%), the player is still in the same scene!
        if not force_reload and st['raw'] and st['results']:
            similarity = compute_text_similarity(all_texts, st['raw'])
            if similarity >= 0.65:
                is_significant_expansion = len(all_texts) > (len(st['raw']) + 3)
                if not is_significant_expansion:
                    with self._lock:
                        # Same text whose translation is still on its way: it arrives through on_translated
                        return None if st['translating'] else st['results']

        st['raw'] = all_texts
        self._new_generation(st)

        # 1. Filters valid items
        valid_items = []
        for item in boxes:
            box, txt, score = item[0], item[1], item[2]
            is_name = item[3] if len(item) > 3 else False

            cleaned_txt = txt.strip()
            if is_name:
                if len(cleaned_txt) < 2:
                    continue
                # Fixes reading variations of the same name
                self.name_memory.seed(self.translator.glossary.latin_terms())
                cleaned_txt = self.name_memory.canonical(cleaned_txt)
            else:
                if not is_meaningful_text(cleaned_txt, source_lang=self.source_lang):
                    continue
            valid_items.append((box, cleaned_txt, score, is_name))

        if not valid_items:
            return []

        t_translate_start = time.time()

        dialogue_text = " ".join(txt for _, txt, _, is_name in valid_items if not is_name)
        speaker = next((txt for _, txt, _, is_name in valid_items if is_name), "")
        with self._lock:
            context = self._build_context(region_key, dialogue_text, speaker)
        context_tag = self._context_tag(context)

        # 2. Resolves what is already cached (memory and disk); force_reload ignores both to retranslate
        lang_pair = (self.source_lang, self.target_lang)
        entries = []
        for box, cleaned_txt, score, is_name in valid_items:
            # The set of glossary terms goes into the key: editing the glossary invalidates the cache
            terms = self.translator.glossary.matches(cleaned_txt)
            fingerprint = Glossary.fingerprint(terms)
            kind = ('N' if is_name else 'D') + (f"+{fingerprint}" if fingerprint else "")
            if not is_name and len(cleaned_txt) < self.SHORT_LINE_CHARS:
                kind += context_tag
            cache_key = f"{kind}:{cleaned_txt}"
            translation = self.translation_cache.get(cache_key)
            if translation is None and not force_reload:
                translation = self.disk_cache.get(*lang_pair, kind, cleaned_txt)
                if translation is not None:
                    self.translation_cache[cache_key] = translation
            entries.append({
                'original': cleaned_txt,
                'translation': translation,
                'box': box,
                'confidence': score,
                'is_name': is_name,
                'cache_key': cache_key,
                'kind': kind,
                'terms': terms,
            })

        pending = [e for e in entries if e['translation'] is None]

        # 3. Immediate visual feedback: texts not yet translated show up as '[Translating with AI...]'
        preliminary = [
            {k: e[k] for k in ('original', 'box', 'confidence', 'is_name')}
            | {'translation': e['translation'] if e['translation'] is not None else "[Translating with AI...]"}
            for e in entries
        ]
        if on_intermediate and pending:
            try:
                on_intermediate(preliminary)
            except Exception:
                pass

        # If the screen changed during OCR (text still being typed), does not spend a translation on
        # incomplete text: returns None and lets the next cycle read the final version
        if pending and should_abort_translation and should_abort_translation():
            st['raw'] = ""
            logger.info("Text still being typed: translation deferred.")
            return None

        engine_detail = " ".join(
            f"{k}={v * 1000:.0f}ms" if isinstance(v, float) else f"{k}={v}"
            for k, v in getattr(self.engine, 'last_timings', {}).items()
        )
        timing = (start_time, t_engine, t_translate_start, engine_detail)

        # 4. Translates in the background: the caller goes back to reading the screen while the API answers.
        # Until then the region keeps the preliminary results, so the same text is not sent again
        if pending and on_translated is not None:
            gen = self._new_generation(st, preliminary, translating=True)
            self._jobs.submit(self._translate_in_background, st, gen, region_key, speaker, context, entries, pending,
                              timing, on_translated)
            return None

        outcomes = self._translate_entries(pending, context)
        self.last_translation_info = self._store_translations(pending, outcomes)
        final_results = self._final_results(entries)
        with self._lock:
            st['results'] = final_results
            self._remember_entries(region_key, speaker, entries)
        self._log_cycle(timing, len(final_results))
        return final_results

    def _translate_entries(self, pending, context):
        """Translates the missing entries; the name and the line go in simultaneous requests."""
        def translate(e):
            return self.translator.translate_with_info(e['original'], e['is_name'],
                                                       None if e['is_name'] else context, e['terms'])
        if len(pending) > 1:
            futures = [self._pool.submit(translate, e) for e in pending]
            return [f.result() for f in futures]
        return [translate(e) for e in pending]

    def _store_translations(self, pending, outcomes):
        """Fills the entries with their translations, caches the good ones and returns the cycle's summary."""
        lang_pair = (self.source_lang, self.target_lang)
        for e, (translation, _) in zip(pending, outcomes):
            e['translation'] = translation
            if translation and not translation.startswith("["):
                self.translation_cache[e['cache_key']] = translation
                self.disk_cache.put(*lang_pair, e['kind'], e['original'], translation)
        return self._summarize_translation(outcomes)

    @staticmethod
    def _final_results(entries):
        return [{k: e[k] for k in ('original', 'translation', 'box', 'confidence', 'is_name')} for e in entries]

    def _remember_entries(self, region_key, speaker, entries):
        self._remember_line(
            region_key, speaker,
            " ".join(e['original'] for e in entries if not e['is_name']),
            " ".join(e['translation'] for e in entries if not e['is_name'] and e['translation']),
        )

    def _translate_in_background(self, st, gen, region_key, speaker, context, entries, pending, timing, on_translated):
        try:
            outcomes = self._translate_entries(pending, context)
            info = self._store_translations(pending, outcomes)
            final_results = self._final_results(entries)
            with self._lock:
                if st['gen'] != gen:
                    logger.info("The text changed before the translation arrived: result discarded (kept in the cache).")
                    return
                st['results'] = final_results
                st['translating'] = False
                self._remember_entries(region_key, speaker, entries)
                # Delivered under the lock: a newer reading of the region cannot reach the screen before this one
                on_translated(final_results, info)
            self._log_cycle(timing, len(final_results))
        except Exception as e:
            logger.error(f"Background translation failed: {e}", exc_info=True)
            with self._lock:
                if st['gen'] == gen:
                    st['translating'] = False
                    st['raw'] = ""  # the next reading of this text tries again

    @staticmethod
    def _log_cycle(timing, count):
        start_time, t_engine, t_translate_start, engine_detail = timing
        logger.info(
            f"Cycle finished in {time.time() - start_time:.2f}s ({count} items) | "
            f"engine={t_engine * 1000:.0f}ms {engine_detail} | translation={(time.time() - t_translate_start) * 1000:.0f}ms"
        )
