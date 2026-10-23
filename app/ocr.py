import abc
import os
import re
import ssl
import time
import logging
import hashlib
import unicodedata
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
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
from languages import language, easyocr_languages, has_script
from name_memory import NameMemory

# Desativa verificacao restrita de SSL do urllib para permitir o download
# automatico dos modelos do EasyOCR em maquinas com certificados locais desatualizados
# Necessário para testar na VM
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass

load_dotenv()

from logger_config import get_logger
logger = get_logger("OCR")

# Ocultar avisos internos
logging.getLogger("easyocr").setLevel(logging.ERROR)


def compute_text_similarity(text1, text2):
    """
    Calcula o grau de similaridade entre duas leituras de tela (0.0 a 1.0)
    ignorando variações de espaços e pontuações, para identificar se ainda
    está na mesma fala de diálogo.
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
    Verifica se o texto contém caracteres japoneses (Hiragana, Katakana ou Kanji).
    """
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]', text))

def is_meaningful_text(text, source_lang='ja'):
    """
    Filtra ruídos vazios ou sem conteúdo real.
    """
    cleaned = re.sub(r'[\s\W_]+', '', text)
    if len(cleaned) < 2:
        return False
    return has_script(cleaned, source_lang)

# Detector CRAFT do MangaOCR: resolução máxima e ampliação (menores = mais rápido)
DETECT_CANVAS_SIZE = 1280
DETECT_MAG_RATIO = 1.0

# Regiões com altura a partir deste valor (px) não passam por upscale
UPSCALE_MAX_HEIGHT = 200

def preprocess_for_ocr(image):
    """
    Aplica visão computacional para caixas de texto, diálogos e títulos na tela (para interfaces, documentos e jogos):
    - Upscale de 2.0x (interpolação cúbica) somente quando a região é pequena (altura < UPSCALE_MAX_HEIGHT);
      capturas já nítidas/grandes mantêm a resolução nativa
    - Converte para escala de cinza nítida sem criar desfoque destrutivo
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

    # 1. Upscale condicional
    if h >= UPSCALE_MAX_HEIGHT:
        return gray, 1.0

    scale_factor = 2.0
    gray = cv2.resize(gray, (int(w * scale_factor), int(h * scale_factor)), interpolation=cv2.INTER_CUBIC)
    
    return gray, scale_factor

def clean_character_name(text):
    """
    Higieniza nomes e títulos lidos por OCR:
    - Normaliza símbolos, caracteres especiais e espaços espúrios
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
    Higieniza pontuação e caracteres corrompidos comuns em fontes estilizadas de tela e mídias visuais (incluindo jogos):
    - Normaliza aspas de abertura e fusão de '「' com 'い' (ex: 『っしゃ / っしゃ -> 「いらっしゃ)
    - Converte '@' ou '＠' em diálogos para '！'
    - Corrige confusões clássicas de katakana e kanji
    - Limpa caudas corrompidas de notas musicais ou símbolos visuais (ex: '一守め」', '古一)d」' -> '」')
    """
    if not text:
        return ""
        
    text = text.strip()
        
    # 1. Normaliza aspas iniciais e fusões comuns com primeira letra
    text = re.sub(r'^[『「]?[さうっ]しゃいませ', '「いらっしゃいませ', text)
    text = re.sub(r'^[『「]?[っ]しゃ', '「いらっしゃ', text)
    text = re.sub(r'^[『「][っ]', '「っ', text)
    text = re.sub(r'^[『]', '「', text)
    
    # 2. Converte @ para ! em diálogos e remove letras latinas isoladas
    text = re.sub(r'[@＠]', '！', text)
    text = re.sub(r'\s+[a-zA-Z]\s+', ' ', text)
    
    # 3. Corrige saudações e saídas comuns (ex: いま世 / いま笹 -> いませ！)
    text = re.sub(r'いま[世笹]', 'いませ！', text)
    
    # 4. Padrões comuns de gramática (〜になりまして / になります)
    text = re.sub(r'こちら[暖医尼隈厄]*[なゆり]+まし[てで]', 'こちらになりまして', text)

    
    # 5. Corrige katakanas com traços cruzados
    text = re.sub(r'オスス[次女・]', 'オススメ', text)
    
    # 6. Vocabulário frequente em interfaces e menus (看板 = placa/lousa de menu/aviso)
    text = re.sub(r'(^|\s)[包母ほ]ちら', r'\1こちら', text)
    text = re.sub(r'看[楓根]', '看板', text)

    
    # 7. Remove aspas de fechamento soltas logo após exclamação
    text = re.sub(r'！\s*[』」]+', '！ ', text)
    
    # 8. Remove caudas corrompidas no final de falas (decorrentes de ♪, ♥ ou ícones)
    text = re.sub(r'[-~]?[宙空]+」?$', '」', text)
    text = re.sub(r'[旭古一\-~]*[守恋]?[-~]?[0-9oO]?[めdD)）]+」?$', '」', text)
    text = re.sub(r'\[$', 'た。', text)
    text = re.sub(r'V$', '」', text)
    
    # Se a fala começou com 「 mas não fechou
    if '「' in text and not text.endswith('」'):
        text = text + '」'
        
    return text.strip()

# ==========================================
# 1. ARQUITETURA HÍBRIDA (PADRÃO STRATEGY)
#           EasyOCR + MangaOCR
# ==========================================

class BaseOCREngine(abc.ABC):
    @abc.abstractmethod
    def extract_text_boxes(self, image_np, offset_x=0, offset_y=0):
        pass

    def warm_up(self):
        """Roda uma inferência descartável para que a primeira leitura real não pague a inicialização."""
        pass

HUD_KEYWORDS = {
    'auto', 'skip', 'save', 'load', 'q.save', 'q.load', 'qsave', 'qload',
    'config', 'log', 'back', 'next', 'menu', 'voice', 'system', 'history',
    'rewind', 'fast', 'stop', 'play', 'window', 'full'
}

def is_hud_element(text):
    """
    Identifica se um texto isolado é um botão de interface/HUD de aplicativos ou jogos.
    """
    cleaned = re.sub(r'[\s\W_]+', '', text).lower()
    return cleaned in HUD_KEYWORDS


def calculate_dominant_font_height(items):
    """
    Calcula a mediana ponderada da altura das caixas de texto.
    Como o diálogo contém a grande maioria dos caracteres da tela,
    a mediana ponderada por número de caracteres encontra a altura exata
    da fonte de leitura principal, independente da resolução (1080p, 4K, etc.).
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
    Agrupa caixas de texto de diálogo que compartilham proximidade espacial
    e fluxo vertical contínuo, descartando textos isolados de cenário.
    """
    if len(candidates) <= 1:
        return candidates
        
    # Ordena de cima para baixo
    sorted_candidates = sorted(candidates, key=lambda c: c['y1'])
    
    clusters = []
    current_cluster = [sorted_candidates[0]]
    
    for prev, curr in zip(sorted_candidates[:-1], sorted_candidates[1:]):
        # Distância vertical máxima esperada entre linhas consecutivas de um mesmo diálogo
        max_vertical_gap = max(2.5 * h_ref, 25.0)
        gap_y = curr['y1'] - prev['y2']
        
        if gap_y <= max_vertical_gap:
            current_cluster.append(curr)
        else:
            clusters.append(current_cluster)
            current_cluster = [curr]
            
    if current_cluster:
        clusters.append(current_cluster)
        
    # Seleciona o cluster dominante (com maior volume total de caracteres)
    best_cluster = max(clusters, key=lambda cl: sum(len(c['txt']) for c in cl))
    return best_cluster

def create_easyocr_reader(langs, device):
    """
    Cria o leitor do EasyOCR no dispositivo pedido ('cpu', 'cuda', 'xpu', 'mps').
    Faz uma leitura de aquecimento para validar a GPU; se falhar, volta para a CPU.
    Retorna (reader, dispositivo_efetivo).
    """
    import easyocr
    if device != 'cpu':
        try:
            reader = easyocr.Reader(langs, gpu=device)
            # O EasyOCR embrulha os modelos em DataParallel, que só sabe dividir lotes entre
            # GPUs CUDA; com um único dispositivo basta usar o módulo interno
            for attr in ('detector', 'recognizer'):
                model = getattr(reader, attr, None)
                if isinstance(model, torch.nn.DataParallel):
                    setattr(reader, attr, model.module)
            reader.readtext(np.zeros((64, 256, 3), dtype=np.uint8))
            return reader, device
        except Exception as e:
            logger.warning(f"EasyOCR não funcionou em '{device}' ({e}). Usando a CPU.")
    return easyocr.Reader(langs, gpu=False), 'cpu'

class EasyOCREngine(BaseOCREngine):
    """
    Motor padrão para idiomas de alfabeto comum/latino.
    """
    def __init__(self, lang='ja', device='cpu'):
        logger.info("Carregando EasyOCR...")
        langs = ['ja', 'en'] if lang == 'ja' else easyocr_languages(lang)
        self.reader, self.device = create_easyocr_reader(langs, device)
        self.lang = lang
        logger.info("Motor EasyOCR carregado com sucesso!")

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
            
        # 1. Filtro inicial de legibilidade e descarte de botões HUD
        parsed_items = []
        for item in raw_res:
            box, txt, score = item[0], item[1].strip(), item[2] if len(item) > 2 else 0.95
            
            # Limpeza de ruído de pontuação inicial/final
            txt = re.sub(r'^[・\s\W_]+', '', txt).strip()
            if not is_meaningful_text(txt, source_lang=self.lang):
                continue
            
            # Descarta botões óbvios de interface
            if is_hud_element(txt):
                continue
                
            # Descarta caixas com score desprezível e muito curtas
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
            
        # 2. Mediana Ponderada da Altura Dominante de Fonte (H_ref)
        h_ref = calculate_dominant_font_height(parsed_items)
        
        # Filtro de escala: descarta textos que tenham menos de 55% da altura da fonte principal
        if h_ref > 8.0:
            parsed_items = [it for it in parsed_items if it['h'] >= (0.55 * h_ref)]
            
        if not parsed_items:
            return []
            
        # 3. Separação Adaptativa: Nome/Título do Locutor vs Texto Principal
        name_candidates = []
        dialogue_candidates = []
        
        for it in parsed_items:
            # É candidato a nome se:
            # - Está no terço superior da ROI relativa (y1 <= 0.35 * img_h)
            # - Não é uma linha longa (w <= 0.38 * img_w)
            # - Não contém pontuação de diálogo
            # - Tem tamanho de nome razoável
            is_in_top_region = it['y1'] <= (0.35 * img_h)
            is_compact_width = it['w'] <= (0.38 * img_w)
            has_no_sentence_punct = not any(q in it['txt'] for q in ['「', '『', '。', '、', '！', '？', '!', '?'])
            has_name_length = 1 <= len(it['txt']) <= 16
            
            if is_in_top_region and is_compact_width and has_no_sentence_punct and has_name_length:
                name_candidates.append(it)
            else:
                dialogue_candidates.append(it)
                
        results = []
        
        # 4. Nome/Título do locutor (se encontrado)
        if name_candidates:
            for it in name_candidates:
                cleaned_name = clean_character_name(it['txt']) if self.lang == 'ja' else it['txt'].strip()
                adj_box = [[int(pt[0] / scale) + offset_x, int(pt[1] / scale) + offset_y] for pt in it['box']]
                results.append((adj_box, cleaned_name, it['score'], True))

                
        # 5. Agrupamento espacial das linhas de diálogo (elimina textos de cenário periféricos)
        if dialogue_candidates:
            clustered_dialogue = cluster_dialogue_lines(dialogue_candidates, h_ref)
            
            # Ordena diálogo em ordem natural de leitura: linha por linha (Y quantizado), da esquerda para a direita (X)
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
    Costura pedaços de texto japonês lidos com sobreposição (sliding window).
    """
    if not texts:
        return ''
    result = texts[0]
    for nxt in texts[1:]:
        if not nxt:
            continue
        sm = SequenceMatcher(None, result, nxt)
        match = sm.find_longest_match(max(0, len(result) - 15), len(result), 0, min(15, len(nxt)))
        # A sobreposição das janelas é pequena: só costura se o trecho repetido estiver
        # no fim do texto anterior e no começo do próximo (senão "だったり" repetido em
        # outra parte da frase apagaria o meio dela)
        at_tail = len(result) - (match.a + match.size) <= 2
        at_head = match.b <= 2
        if match.size >= 2 and at_tail and at_head:
            result = result[:match.a] + nxt[match.b:]
        else:
            result += nxt
    return result

# Caixas bem mais altas do que largas são colunas de texto vertical (tate-gaki)
VERTICAL_RATIO = 1.8

def is_vertical_box(w, h):
    return h > VERTICAL_RATIO * w

def order_dialogue_items(items, h_ref):
    """
    Ordem natural de leitura: texto horizontal de cima para baixo e da esquerda para a direita;
    texto vertical em colunas, da direita para a esquerda e de cima para baixo em cada coluna.
    """
    vertical = [d for d in items if d.get('vertical')]
    if vertical and len(vertical) * 2 > len(items):
        col_w = max(12.0, 0.6 * float(np.median([d['w'] for d in vertical])))
        return sorted(items, key=lambda d: (-round(((d['x1'] + d['x2']) / 2) / col_w), d['y1']))
    row_h = max(12.0, 0.6 * h_ref) if h_ref > 0 else 20.0
    return sorted(items, key=lambda d: (round(d['y1'] / row_h), d['x1']))

def drop_furigana(items):
    """
    Descarta caixas pequenas de furigana (kana de leitura) coladas a uma caixa de texto maior:
    em linhas horizontais ficam acima dela; em colunas verticais, à direita. Elas confundem o
    OCR do texto principal e só se pareceriam com legenda extra na tradução.
    """
    def is_furigana_of(small, big):
        if small is big or small.get('is_in_name_pos') or big.get('is_in_name_pos'):
            return False
        if big.get('vertical'):
            # O detector costuma quebrar a coluna de furigana em pedaços curtos (não verticais)
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
    Separa uma caixa de texto vertical em colunas (da direita para a esquerda) pelos vãos
    de tinta entre elas. Colunas muito estreitas ao lado de uma coluna principal são tratadas
    como furigana e descartadas. Se não achar mais de uma coluna, devolve a imagem original.
    """
    gray = np.array(pil_img.convert("L"), dtype=np.uint8)
    h, w = gray.shape
    if w < 12:
        return [pil_img]

    # Tinta = pixels que se afastam do fundo (serve para texto claro ou escuro)
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

    # Junta pedaços separados por vãos minúsculos (espaços dentro do mesmo caractere)
    widest = max(b - a for a, b in segments)
    merged = [segments[0]]
    for a, b in segments[1:]:
        if a - merged[-1][1] < 0.15 * widest:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    if len(merged) < 2:
        return [pil_img]

    # Descarta colunas estreitas (furigana ou ruído)
    widest = max(b - a for a, b in merged)
    merged = [(a, b) for a, b in merged if (b - a) >= 0.45 * widest]
    if len(merged) < 2 and merged and (merged[0][1] - merged[0][0]) >= w * 0.9:
        return [pil_img]

    columns = []
    for a, b in sorted(merged, key=lambda s: -s[0]):  # da direita para a esquerda
        columns.append(pil_img.crop((max(0, a - 4), 0, min(w, b + 4), h)))
    return columns

def _is_jp_char(c):
    return unicodedata.name(c, '').startswith(('HIRAGANA', 'KATAKANA', 'CJK'))

def _script_counts(text):
    """(letras latinas, caracteres japoneses) de um texto, ignorando largura total."""
    norm = unicodedata.normalize('NFKC', text)
    latin = sum(1 for c in norm if c.isascii() and c.isalpha())
    jp = sum(1 for c in norm if _is_jp_char(c))
    return latin, jp

def pick_name_text(easy_txt, manga_txt, padded_txt=None):
    """
    Escolhe a leitura do nome do locutor entre EasyOCR e MangaOCR conforme o alfabeto.
    O MangaOCR só conhece japonês e "alucina" um kana no meio de nomes latinos,
    então a decisão é por proporção. Em nomes latinos vale o EasyOCR, sem sobras japonesas.
    """
    easy = (padded_txt or easy_txt or '').strip()
    e_lat, e_jp = _script_counts(easy)
    m_lat, m_jp = _script_counts(manga_txt)

    if e_jp == 0 and e_lat >= 3:
        return clean_character_name(easy)  # EasyOCR leu só letras latinas
    if m_jp >= 2 and m_jp > m_lat:
        return clean_character_name(manga_txt)  # nome japonês
    if e_lat >= 2 and e_lat > e_jp:
        return clean_character_name(''.join(c for c in easy if not _is_jp_char(c)))  # nome latino
    if m_jp >= 1:
        return clean_character_name(manga_txt)
    norm_m = unicodedata.normalize('NFKC', manga_txt).strip()
    return clean_character_name(easy if len(easy) >= 2 else norm_m)

def strip_latin_runs(text):
    """
    Remove sobras de inglês dentro de uma caixa de diálogo japonesa (ex: o fim de uma legenda
    em inglês que ficou colada na mesma caixa e foi "lida" pelo MangaOCR como letras latinas).
    Só age em sequências longas de letras latinas; siglas curtas como HP ou OK permanecem.
    """
    latin = 'A-Za-zＡ-Ｚａ-ｚ'
    cleaned = re.sub(f"[{latin}][{latin}．，！？’'-]{{5,}}", '', text)
    return cleaned.strip() if contains_japanese(cleaned) else text

def is_english_subtitle(easy_txt, manga_txt):
    """
    Identifica se a caixa é uma legenda ou texto em inglês que deve ser ignorada na tradução JP.
    """
    jp_pattern = r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]'

    # 1. MangaOCR retornou predominantemente letras latinas (ex: ｔｈｅｎｅｘｔ... em largura total).
    # O MangaOCR só conhece japonês: ao ler inglês ele "alucina" lixo em que sobra uma ou outra
    # letra japonesa, então o que vale é a proporção, não a ausência total de caracteres japoneses.
    norm_manga = unicodedata.normalize('NFKC', manga_txt).strip()
    latin_chars_manga = sum(1 for c in norm_manga if c.isascii() and c.isalpha())
    jp_chars_manga = len(re.findall(jp_pattern, norm_manga))
    if latin_chars_manga >= 4 and latin_chars_manga > jp_chars_manga:
        return True

    # 2. EasyOCR enxergou só letras latinas na caixa
    latin_chars_easy = sum(1 for c in easy_txt if c.isascii() and c.isalpha())
    jp_chars_easy = len(re.findall(jp_pattern, easy_txt))
    if latin_chars_easy >= 6 and jp_chars_easy == 0:
        return True
    if latin_chars_easy >= 4 and jp_chars_easy <= 1 and not contains_japanese(manga_txt):
        return True

    return False

class MangaOCREngine(BaseOCREngine):
    """
    Motor padrão para o alfabeto japonês.
    Também utiliza o EasyOCR.
    """
    def __init__(self, device='cpu'):
        import manga_ocr
        logger.info("Carregando MangaOCR + Detector CRAFT...")
        self.detector, self.device = create_easyocr_reader(['ja', 'en'], device)
        # Sempre carrega na CPU e move para o dispositivo escolhido (inclui Intel XPU,
        # que o manga_ocr não seleciona sozinho)
        self.mocr = manga_ocr.MangaOcr(force_cpu=True)
        self.crop_cache = OrderedDict()
        self.last_timings = {}
        if self.device != 'cpu':
            try:
                self.mocr.model.to(self.device)
                self._recognize_batch([Image.new("RGB", (120, 48), "white")])  # aquecimento
            except Exception as e:
                logger.warning(f"MangaOCR não funcionou em '{self.device}' ({e}). Usando a CPU.")
                self.mocr.model.to('cpu')
                self.device = 'cpu'
        logger.info("Motor MangaOCR japonês carregado com sucesso!")


    BATCH_SIZE = 16
    CROP_CACHE_SIZE = 256

    def warm_up(self):
        self.detector.readtext(np.zeros((128, 512, 3), dtype=np.uint8))
        with torch.inference_mode():
            self._recognize_batch([Image.new("RGB", (240, 48), "white")])

    @staticmethod
    def _strip_windows(length):
        """Janelas (início, fim) de leitura de uma faixa com o comprimento dado (largura ou altura)."""
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
        """Roda o MangaOCR em lote (uma passagem do modelo por BATCH_SIZE recortes)."""
        mocr = self.mocr
        texts = []
        for i in range(0, len(pil_imgs), self.BATCH_SIZE):
            group = pil_imgs[i:i + self.BATCH_SIZE]
            pixels = torch.stack([mocr._preprocess(im.convert("L").convert("RGB")) for im in group])
            out = mocr.model.generate(pixels.to(mocr.model.device), max_length=300).cpu()
            for ids in out:
                texts.append(manga_ocr_post_process(mocr.tokenizer.decode(ids, skip_special_tokens=True)))
        return texts

    def _read_strips(self, pil_imgs, vertical=None):
        """
        Lê várias faixas em um único lote, aplicando a costura das janelas deslizantes.
        `vertical` indica, para cada faixa, se é texto vertical (por padrão, decide pela proporção).
        """
        if vertical is None:
            vertical = [is_vertical_box(*img.size) for img in pil_imgs]
        # Faixas idênticas às já lidas (ex: linhas anteriores durante a digitação) vêm do cache
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
        # Caixas verticais viram uma unidade por coluna (lidas da direita para a esquerda)
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

    def _read_name_padded(self, image_np, x1, y1, x2, y2, tight_txt):
        """
        Relê o nome com margem lateral: a caixa justa do detector às vezes corta a primeira
        ou a última letra. Devolve None se não houver leitura melhor.
        """
        try:
            img_h, img_w = image_np.shape[:2]
            pad_x = max(8, int(0.5 * (y2 - y1)))
            pad_y = 3
            region = [max(0, x1 - pad_x), min(img_w, x2 + pad_x), max(0, y1 - pad_y), min(img_h, y2 + pad_y)]
            gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
            result = self.detector.recognize(gray, horizontal_list=[region], free_list=[])
            if result:
                text = result[0][1].strip()
                if len(text) >= len(tight_txt.strip()):
                    return text
        except Exception as e:
            logger.debug(f"Leitura do nome com margem falhou: {e}")
        return None

    def extract_text_boxes(self, image_np, offset_x=0, offset_y=0):
        if image_np is None or image_np.size == 0:
            return []
            
        img_h, img_w = image_np.shape[:2]
        pil_img = Image.fromarray(image_np)
        
        # 1. Detecção geométrica das caixas com CRAFT
        t0 = time.perf_counter()
        raw_res = self.detector.readtext(
            image_np, 
            paragraph=False,
            contrast_ths=0.1, 
            adjust_contrast=0.5,
            link_threshold=0.4,
            low_text=0.4,
            text_threshold=0.7,
            mag_ratio=DETECT_MAG_RATIO,
            canvas_size=DETECT_CANVAS_SIZE
        )
        self.last_timings['detect'] = time.perf_counter() - t0
        
        if not raw_res:
            return []
            
        # Fase 1: filtra as caixas detectadas e prepara os recortes
        pending = []
        
        for item in raw_res:
            box, easy_txt, score = item[0], item[1].strip(), item[2] if len(item) > 2 else 0.95
            
            # Filtro de botões HUD
            if is_hud_element(easy_txt):
                continue
                
            x1 = max(0, int(min(pt[0] for pt in box)))
            y1 = max(0, int(min(pt[1] for pt in box)))
            x2 = min(img_w, int(max(pt[0] for pt in box)))
            y2 = min(img_h, int(max(pt[1] for pt in box)))
            
            w = max(1, x2 - x1)
            h = max(1, y2 - y1)
            
            # Descarta ruídos microscópicos
            if w < 8 or h < 8:
                continue


            # 1. Identificação de Nome/Título ou Locutor (rótulo ancorado no canto superior esquerdo)
            vertical = is_vertical_box(w, h)
            if not vertical and h > 0.9 * w and w >= 40:
                # Caixa quase quadrada pode ser um bloco de várias colunas verticais
                columns = split_vertical_columns(pil_img.crop((x1, y1, x2, y2)))
                vertical = len(columns) >= 2 and all(c.height > 2.0 * c.width for c in columns)
            is_in_name_pos = (not vertical) and (x1 <= 0.15 * img_w) and (y1 <= 0.30 * img_h) and (h >= 22) and ((w / max(1, h)) <= 5.0)

            
            # 2. Pré-filtro ultra-rápido de legendas em inglês (0.00ms) ANTES de rodar MangaOCR:
            if not is_in_name_pos:
                ascii_letters = sum(1 for c in easy_txt if c.isascii() and c.isalpha())
                jp_chars = len(re.findall(r'[぀-ゟ゠-ヿ一-龯]', easy_txt))
                if ascii_letters >= 4 and jp_chars <= 1 and score >= 0.20:
                    # Legenda secundária descartada instantaneamente, poupando inferência pesada!
                    continue
            
            # Leve margem para leitura sem corte de bordas
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

        # Furigana colado ao texto principal não precisa (nem deve) ser lido
        pending = drop_furigana(pending)

        if not pending:
            return []

        # Fase 2: leitura de todos os recortes em lote
        t0 = time.perf_counter()
        read_texts = self._read_strips([p['crop'] for p in pending], [p['vertical'] for p in pending])
        self.last_timings['ocr'] = time.perf_counter() - t0

        # Fase 3: classificação em nome / diálogo
        name_candidates = []
        dialogue_items = []

        for p, manga_txt in zip(pending, read_texts):
            box, easy_txt, score = p['box'], p['easy_txt'], p['score']
            x1, y1, x2, y2, w, h = p['x1'], p['y1'], p['x2'], p['y2'], p['w'], p['h']
            is_in_name_pos = p['is_in_name_pos']

            if is_in_name_pos:
                # Nomes podem ser ocidentais ou japoneses
                padded_txt = self._read_name_padded(image_np, x1, y1, x2, y2, easy_txt)
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
                
            # Filtro secundário caso tenha passado pelo pré-filtro
            if is_english_subtitle(easy_txt, manga_txt):
                continue
                
            manga_txt = strip_latin_runs(manga_txt)
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
            # Seleciona o nome mais confiante / à esquerda
            best_name = min(name_candidates, key=lambda n: n[0][0][0])
            results.append(best_name)
            
        if dialogue_items:
            # Ordena diálogo de forma coerente de cima para baixo
            h_ref = calculate_dominant_font_height(dialogue_items)
            dialogue_items = order_dialogue_items(dialogue_items, h_ref)
            
            full_txt = " ".join([d['txt'] for d in dialogue_items])
            full_txt = clean_ocr_punctuation(full_txt)
            
            all_boxes = [d['box'] for d in dialogue_items]
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
# 2. MOTOR DE TRADUÇÃO E GERENCIADOR (FACTORY)
# ==========================================

class TranslationEngine:
    """
    Motor de tradução:
    1. Primário: Groq AI (Qwen-2.5 27B) - autocorreção contextual de OCR e linguagem natural para conteúdos gerais (interfaces, documentos, vídeos e jogos)
    2. Secundário: Fallback clássico para MyMemory / Google Translate se offline ou sem chave
    """
    DEFAULT_GROQ_MODELS = ["qwen/qwen3.8-27b", "groq/compound-mini"]

    def __init__(self, source='ja', target='pt', groq_models=None):
        # Lista de modelos Groq em ordem de preferência (ex: ["llama-3.1-8b-instant"] para baixa latência)
        if isinstance(groq_models, str):
            groq_models = [groq_models]
        self.groq_models = list(groq_models) if groq_models else list(self.DEFAULT_GROQ_MODELS)
        self.source = source[:2].lower()
        self.target = target[:2].lower()
        self.glossary = Glossary(self.source, self.target)
        
        # 1. Tenta inicializar cliente Groq
        self.groq_client = None
        groq_key = os.getenv("GROQ_API_KEY", "").strip()
        if groq_key and not groq_key.startswith("your_"):
            try:
                from groq import Groq
                self.groq_client = Groq(api_key=groq_key)
                logger.info("Motor de Tradução por IA ativado (Groq - Qwen)!")
            except Exception as e:
                logger.warning(f"Aviso ao inicializar Groq ({e}). Usando modo tradicional.")

                
        # 2. Instancia provedores tradicionais de fallback
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
        
    def warm_up(self):
        """Abre a conexão HTTPS com a Groq (DNS + TLS) sem gastar tokens, para a primeira tradução sair mais rápido."""
        if self.groq_client:
            try:
                self.groq_client.models.list()
            except Exception as e:
                logger.debug(f"Pré-conexão com a Groq falhou: {e}")

    def translate(self, text, is_name=False):
        text = text.strip()
        if not text:
            return ""

        # Termos fixos do glossário que aparecem neste texto
        terms = self.glossary.matches(text)
            
        # Tentativa 1: Tradução com IA Contextual (Groq)
        if self.groq_client:
            source_name = language(self.source).prompt
            target_name = language(self.target).prompt
            
            if is_name:
                system_prompt = (
                    f"Você é um tradutor geral e especialista em localização de alta precisão ({source_name} para {target_name}). "
                    f"Você é capaz de traduzir qualquer tipo de conteúdo exibido em tela (interfaces de softwares, documentos, mídias visuais e jogos eletrônicos).\n"
                    f"O texto fornecido é o nome de uma pessoa, interlocutor, autor ou personagem capturado via OCR da tela em tempo real, podendo conter pequenas distorções de caracteres causadas por fontes estilizadas ou compressão visual.\n"
                    f"Regras:\n"
                    f"1. Se for um nome próprio de pessoa ou personagem (real ou ficcional), deduza a grafia consagrada e mantenha-a sem traduzir literalmente (ex: Cloud, Arthur, Tanaka, etc.).\n"
                    f"2. Se for um cargo, profissão, título ou descrição de papel (ex: 'Guarda', 'Ferreiro', 'Diretor', 'Elder'), traduza de forma natural para {target_name}.\n"
                    f"3. Retorne EXCLUSIVAMENTE o nome final, sem aspas e sem explicações adicionais."
                )
            else:
                system_prompt = (
                    f"Você é um tradutor geral e especialista em localização de alta precisão ({source_name} para {target_name}). "
                    f"Você é capaz de traduzir qualquer conteúdo exibido em tela em tempo real, incluindo interfaces, sistemas, documentos, legendas, vídeos e jogos eletrônicos.\n"
                    f"O texto fornecido foi capturado por OCR da tela em tempo real. Devido a fontes estilizadas, efeitos visuais ou elementos de fundo, o OCR pode conter pequenas trocas visuais de caracteres ou pontuações imperfeitas.\n"
                    f"Diretrizes:\n"
                    f"1. Identifique o texto ou fala pretendida no contexto geral da tela, interface ou narrativa (incluindo diálogos de jogos quando for o caso), corrigindo silenciosamente eventuais trocas ou ruídos de caracteres causados pelo OCR.\n"
                    f"2. Produza uma tradução fluida, precisa e natural para {target_name}, preservando fielmente o tom, o sentido e o estilo do texto original.\n"
                    f"3. Retorne EXCLUSIVAMENTE a tradução final direta, sem aspas, sem notas explicativas e sem comentários adicionais."
                )

                
            if terms:
                system_prompt += (
                    "\nGlossário obrigatório (use exatamente estas traduções para estes termos):\n"
                    + "\n".join(f"- {k} → {v}" for k, v in terms.items())
                )

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
                    )
                    translated = res.choices[0].message.content.strip()
                    # Remove aspas se a IA colocou
                    if (translated.startswith('"') and translated.endswith('"')) or (translated.startswith('「') and translated.endswith('」')):
                        translated = translated[1:-1].strip()
                    if translated:
                        return translated
                except Exception:
                    continue
                    
        # Os tradutores clássicos não aceitam instruções: aplica o glossário trocando os termos no texto
        fallback_text = text
        for k, v in terms.items():
            fallback_text = fallback_text.replace(k, v)

        # Tentativa 2: Fallback para MyMemory
        if self.mymemory:
            try:
                res = self.mymemory.translate(fallback_text)
                if res and not any(err in res.lower() for err in ["error 500", "server error", "please try again"]):
                    return res.strip()
            except Exception:
                pass
                
        # Tentativa 3: Fallback para Google
        if self.google:
            try:
                res = self.google.translate(fallback_text)
                if res and not any(err in res.lower() for err in ["error 500", "server error", "please try again"]):
                    return res.strip()
            except Exception:
                pass
            
        return "[Traduzindo...]"

class OCRTranslator:
    """
    Fachada / Gerenciador do Sistema:
    Instancia o motor ideal e administra o cache e a tradução.
    - source_lang == 'ja': Usa MangaOCREngine (MangaOCR + CRAFT Detector com descarte de legendas EN)
    - source_lang != 'ja': Usa EasyOCREngine (Motor para alfabeto latino)
    """
    def __init__(self, source_lang='ja', target_lang='en', device_preference='auto', groq_models=None):
        device, device_label = resolve_device(device_preference)
        logger.info(f"Inicializando Tradutor... (dispositivo: {device_label})")
        
        self.source_lang = source_lang
        self.target_lang = target_lang
        
        if source_lang == 'ja':
            self.engine = MangaOCREngine(device=device)
        else:
            self.engine = EasyOCREngine(lang=source_lang, device=device)

        # O motor pode ter voltado para a CPU se a GPU falhou
        self.device = self.engine.device
        self.device_label = device_label if self.device == device else resolve_device('cpu')[1]
            
        self.translator = TranslationEngine(source=source_lang, target=target_lang, groq_models=groq_models)
        
        self.translation_cache = {}
        self.name_memory = NameMemory()
        self.disk_cache = PersistentTranslationCache()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="translate")
        self.last_detected_raw = ""
        self.last_results = []
        self.last_confidence = 0.0

        self.warm_up()
        
        logger.info(f"Tradutor Pronto para uso! (Destino: {target_lang.upper()}, dispositivo: {self.device_label})")


    def warm_up(self):
        """Aquece OCR e conexão com a API em paralelo; falhas aqui nunca impedem o uso."""
        t0 = time.time()
        net = self._pool.submit(self.translator.warm_up)
        try:
            self.engine.warm_up()
        except Exception as e:
            logger.warning(f"Aquecimento do OCR falhou ({e}); a primeira leitura será mais lenta.")
        net.result()
        logger.info(f"Aquecimento concluído em {time.time() - t0:.1f}s")

    def process_image(self, image_data, offset_x=0, offset_y=0, on_intermediate=None, force_reload=False,
                      should_abort_translation=None):
        if isinstance(image_data, str):
            if not os.path.exists(image_data):
                return []
            image_data = cv2.imread(image_data)
            if image_data is None:
                return []
            image_data = cv2.cvtColor(image_data, cv2.COLOR_BGR2RGB)

        if force_reload:
            self.last_detected_raw = ""
            self.last_results = []
            self.translation_cache.clear()

        start_time = time.time()
        
        boxes = self.engine.extract_text_boxes(image_data, offset_x=offset_x, offset_y=offset_y)
        t_engine = time.time() - start_time
        
        if not boxes:
            self.last_detected_raw = ""
            self.last_results = []
            self.last_confidence = 0.0
            return []
            
        all_texts = " | ".join([item[1] for item in boxes])
        current_conf = float(np.mean([item[2] for item in boxes])) if boxes else 0.0
        
        # Trava de Estabilidade de Cena (Fuzzy Match / Anti-Jitter)
        # Se o texto atual for similar ao frame anterior (>= 65%), o jogador ainda está na mesma cena!
        if not force_reload and self.last_detected_raw and self.last_results:
            similarity = compute_text_similarity(all_texts, self.last_detected_raw)
            if similarity >= 0.65:
                is_significant_expansion = len(all_texts) > (len(self.last_detected_raw) + 3)
                if not is_significant_expansion:
                    return self.last_results
                    
        self.last_detected_raw = all_texts
        self.last_confidence = current_conf

        # 1. Filtra itens válidos
        valid_items = []
        for item in boxes:
            box, txt, score = item[0], item[1], item[2]
            is_name = item[3] if len(item) > 3 else False
            
            cleaned_txt = txt.strip()
            if is_name:
                if len(cleaned_txt) < 2:
                    continue
                # Corrige variações de leitura do mesmo nome
                self.name_memory.seed(self.translator.glossary.latin_terms())
                cleaned_txt = self.name_memory.canonical(cleaned_txt)
            else:
                if not is_meaningful_text(cleaned_txt, source_lang=self.source_lang):
                    continue
            valid_items.append((box, cleaned_txt, score, is_name))

        if not valid_items:
            return []

        t_translate_start = time.time()

        # 2. Resolve o que já está em cache (memória e disco); force_reload ignora ambos para retraduzir
        lang_pair = (self.source_lang, self.target_lang)
        entries = []
        for box, cleaned_txt, score, is_name in valid_items:
            # O conjunto de termos do glossário entra na chave: editar o glossário invalida o cache
            fingerprint = Glossary.fingerprint(self.translator.glossary.matches(cleaned_txt))
            kind = ('N' if is_name else 'D') + (f"+{fingerprint}" if fingerprint else "")
            cache_key = f"{kind}:{cleaned_txt}"
            traducao = self.translation_cache.get(cache_key)
            if traducao is None and not force_reload:
                traducao = self.disk_cache.get(*lang_pair, kind, cleaned_txt)
                if traducao is not None:
                    self.translation_cache[cache_key] = traducao
            entries.append({
                'original': cleaned_txt,
                'traducao': traducao,
                'box': box,
                'confidence': score,
                'is_name': is_name,
                'cache_key': cache_key,
                'kind': kind,
            })

        pending = [e for e in entries if e['traducao'] is None]

        # 3. Feedback visual imediato: textos ainda não traduzidos aparecem como '[Traduzindo com IA...]'
        if on_intermediate and pending:
            preliminary = [
                {k: e[k] for k in ('original', 'box', 'confidence', 'is_name')}
                | {'traducao': e['traducao'] if e['traducao'] is not None else "[Traduzindo com IA...]"}
                for e in entries
            ]
            try:
                on_intermediate(preliminary)
            except Exception:
                pass

        # Se a tela mudou durante o OCR (texto ainda sendo digitado), não gasta tradução em texto
        # incompleto: devolve None e deixa o próximo ciclo ler a versão final
        if pending and should_abort_translation and should_abort_translation():
            self.last_detected_raw = ""
            logger.info("Texto ainda em digitação: tradução adiada.")
            return None

        # 4. Traduz em paralelo tudo que faltou (nome e fala em requisições simultâneas)
        if len(pending) > 1:
            futures = [self._pool.submit(self.translator.translate, e['original'], e['is_name']) for e in pending]
            translated = [f.result() for f in futures]
        else:
            translated = [self.translator.translate(e['original'], e['is_name']) for e in pending]

        for e, traducao in zip(pending, translated):
            e['traducao'] = traducao
            if traducao and not traducao.startswith("["):
                self.translation_cache[e['cache_key']] = traducao
                self.disk_cache.put(*lang_pair, e['kind'], e['original'], traducao)

        resultados_finais = [
            {k: e[k] for k in ('original', 'traducao', 'box', 'confidence', 'is_name')}
            for e in entries
        ]
            
        self.last_results = resultados_finais
        t_translate = time.time() - t_translate_start
        engine_detail = getattr(self.engine, 'last_timings', {})
        detail = " ".join(
            f"{k}={v * 1000:.0f}ms" if isinstance(v, float) else f"{k}={v}" for k, v in engine_detail.items()
        )
        logger.info(
            f"Ciclo concluído em {time.time() - start_time:.2f}s ({len(resultados_finais)} itens) | "
            f"motor={t_engine * 1000:.0f}ms {detail} | traducao={t_translate * 1000:.0f}ms"
        )
        return resultados_finais
