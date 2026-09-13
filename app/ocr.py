import abc
import os
import re
import time
import logging
import unicodedata
from difflib import SequenceMatcher
from PIL import Image
import cv2
import numpy as np
import torch
from dotenv import load_dotenv
from deep_translator import MyMemoryTranslator, GoogleTranslator

# Carrega variáveis do arquivo .env local
load_dotenv()

# Ocultar avisos internos
logging.getLogger("easyocr").setLevel(logging.ERROR)

def compute_text_similarity(text1, text2):
    """
    Calcula o grau de similaridade semântica entre duas leituras de tela (0.0 a 1.0)
    ignorando variações de espaços e pontuações, para identificar se o jogador ainda
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
    if source_lang == 'ja':
        return contains_japanese(cleaned)
    return len(cleaned) >= 2

def preprocess_for_ocr(image):
    """
    Aplica visão computacional para caixas de diálogo e nomes em jogos:
    - Upscale de 2.0x com interpolação Lanczos4 (suaviza curvas de fontes)
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
    scale_factor = 2.0
    
    # 1. Upscale de alta fidelidade
    up = cv2.resize(image, (int(w * scale_factor), int(h * scale_factor)), interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.cvtColor(up, cv2.COLOR_RGB2GRAY)
    
    return gray, scale_factor

def clean_character_name(text):
    """
    Higieniza nomes de personagens lidos por OCR:
    - Corrige fusões clássicas de katakanas (ex: 'ツ司' / 'ツョ' / 'vコラ' -> 'ショコラ')
    """
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r'^[@＠][ョ]', 'ショ', text)
    text = re.sub(r'^[vV][コラ]', 'ショコ', text)
    text = re.sub(r'^[ツッ][司ョ]', 'ショ', text)
    text = re.sub(r'ショコラ+', 'ショコラ', text)
    text = re.sub(r'^[cC]+(?=[A-Z])', '', text)
    text = re.sub(r'^[・\s\W_]+|[・\s\W_]+$', '', text)
    return text.strip()

def clean_ocr_punctuation(text):
    """
    Higieniza pontuação e caracteres corrompidos comuns em fontes estilizadas de jogos:
    - Normaliza aspas de abertura e fusão de '「' com 'い' (ex: 『っしゃ / っしゃ -> 「いらっしゃ)
    - Converte '@' ou '＠' em diálogos para '！'
    - Corrige confusões clássicas de katakana e kanji em jogos
    - Limpa caudas corrompidas de notas musicais ou símbolos de anime (ex: '一守め」', '古一)d」' -> '」')
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
    
    # 4. Gramática ultra-comum de jogos (〜になりまして / になります)
    text = re.sub(r'こちら[暖医尼隈厄]*[なゆり]+まし[てで]', 'こちらになりまして', text)
    
    # 5. Corrige katakanas com traços cruzados
    text = re.sub(r'オスス[次女・]', 'オススメ', text)
    
    # 6. Vocabulário frequente de jogos (看板 = placa/lousa de menu)
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
# ==========================================

class BaseOCREngine(abc.ABC):
    @abc.abstractmethod
    def extract_text_boxes(self, image_np, offset_x=0, offset_y=0):
        pass

HUD_KEYWORDS = {
    'auto', 'skip', 'save', 'load', 'q.save', 'q.load', 'qsave', 'qload',
    'config', 'log', 'back', 'next', 'menu', 'voice', 'system', 'history',
    'rewind', 'fast', 'stop', 'play', 'window', 'full'
}

def is_hud_element(text):
    """
    Identifica se um texto isolado é um botão de interface/HUD de jogos.
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

class EasyOCREngine(BaseOCREngine):
    """
    Motor Robusto e Estável para Jogos e Visual Novels.
    Lê sentenças horizontais com pré-processamento adaptativo e filtragem geométrica.
    """
    def __init__(self, lang='ja', use_gpu=False):
        import easyocr
        print(f"[{time.strftime('%H:%M:%S')}] Carregando EasyOCR (Motor de Leitura Horizontal)...")
        if lang == 'ja':
            self.reader = easyocr.Reader(['ja', 'en'], gpu=use_gpu)
        else:
            self.reader = easyocr.Reader([lang], gpu=use_gpu)
        self.lang = lang
        print(f"[{time.strftime('%H:%M:%S')}] Motor EasyOCR carregado com sucesso!")
        
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
            
        # 3. Separação Adaptativa: Nome da Personagem vs Falas de Diálogo
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
        
        # 4. Nome da personagem (se encontrado)
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
        if match.size >= 2:
            result = result[:match.a] + nxt[match.b:]
        else:
            result += nxt
    return result

def is_english_subtitle(easy_txt, manga_txt):
    """
    Identifica se a caixa é uma legenda ou texto em inglês (recurso de legendas
    duplas EN+JP em jogos como Nekopara) que deve ser ignorada na tradução JP.
    """
    # Se o MangaOCR identificou caracteres japoneses reais (Hiragana, Katakana ou Kanji),
    # é 100% garantido que é diálogo em japonês e NUNCA legenda em inglês!
    if contains_japanese(manga_txt):
        return False

    # 1. EasyOCR detectou predominantemente letras latinas
    latin_chars_easy = sum(1 for c in easy_txt if c.isascii() and c.isalpha())
    jp_chars_easy = len(re.findall(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]', easy_txt))
    if latin_chars_easy >= 4 and jp_chars_easy <= 1:
        return True
        
    # 2. MangaOCR retornou romaji em largura total (ex: ｔｈｅｎｅｘｔ... ou ｃａｒｍｙ...)
    norm_manga = unicodedata.normalize('NFKC', manga_txt).strip()
    latin_chars_manga = sum(1 for c in norm_manga if c.isascii() and c.isalpha())
    jp_chars_manga = len(re.findall(r'[\u3040-\u309F\u4E00-\u9FAF]', norm_manga))
    if latin_chars_manga >= 4 and jp_chars_manga == 0:
        return True
        
    return False

class MangaOCREngine(BaseOCREngine):
    """
    Motor Especializado de Alta Precisão para Japonês (MangaOCR + EasyOCR CRAFT).
    Combina a detecção precisa de caixas do CRAFT com a leitura profunda por IA do MangaOCR,
    fatiando linhas horizontais longas em janelas deslizantes e filtrando legendas duplas em inglês.
    """
    def __init__(self, use_gpu=False):
        import easyocr
        import manga_ocr
        print(f"[{time.strftime('%H:%M:%S')}] Carregando MangaOCR + Detector CRAFT (Japonês Especializado)...")
        self.detector = easyocr.Reader(['ja', 'en'], gpu=use_gpu)
        self.mocr = manga_ocr.MangaOcr()
        print(f"[{time.strftime('%H:%M:%S')}] Motor MangaOCR japonês carregado com sucesso!")

    def _read_strip(self, pil_img):
        w, h = pil_img.size
        if w <= 360:
            return self.mocr(pil_img).strip()
        step = 260
        window = 340
        chunks = []
        for x in range(0, w, step):
            x2 = min(w, x + window)
            c = pil_img.crop((x, 0, x2, h))
            t = self.mocr(c).strip()
            if t and t not in ['...', '…', '‥']:
                chunks.append(t)
            if x2 == w or (t and t.endswith('」')):
                break
        return stitch_ocr_chunks(chunks)

    def extract_text_boxes(self, image_np, offset_x=0, offset_y=0):
        if image_np is None or image_np.size == 0:
            return []
            
        img_h, img_w = image_np.shape[:2]
        pil_img = Image.fromarray(image_np)
        
        # 1. Detecção geométrica das caixas com CRAFT
        raw_res = self.detector.readtext(
            image_np, 
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
            
        name_candidates = []
        dialogue_items = []
        
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
            
            # 1. Identificação de Nome do Personagem (placa ancorada no canto superior esquerdo)
            is_in_name_pos = (x1 <= 0.15 * img_w) and (y1 <= 0.30 * img_h) and (h >= 22) and ((w / max(1, h)) <= 5.0)
            
            # 2. Pré-filtro ultra-rápido de legendas em inglês (0.00ms) ANTES de rodar MangaOCR:
            if not is_in_name_pos:
                ascii_letters = sum(1 for c in easy_txt if c.isascii() and c.isalpha())
                jp_chars = len(re.findall(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]', easy_txt))
                if ascii_letters >= 4 and jp_chars <= 1 and score >= 0.20:
                    # Legenda secundária descartada instantaneamente, poupando inferência pesada!
                    continue
            
            # Leve margem para leitura sem corte de bordas
            pad_x1 = max(0, x1 - 4)
            pad_y1 = max(0, y1 - 4)
            pad_x2 = min(img_w, x2 + 4)
            pad_y2 = min(img_h, y2 + 4)
            
            box_crop = pil_img.crop((pad_x1, pad_y1, pad_x2, pad_y2))
            with torch.inference_mode():
                manga_txt = self._read_strip(box_crop)
            
            if is_in_name_pos:
                # Nomes podem ser ocidentais (ex: Vanilla) ou japoneses (ex: ショコラ)
                if any('\u3040' <= c <= '\u9FAF' for c in manga_txt):
                    final_name = clean_character_name(manga_txt)
                else:
                    norm_m = unicodedata.normalize('NFKC', manga_txt).strip()
                    final_name = easy_txt if len(easy_txt) >= 2 else norm_m
                    final_name = clean_character_name(final_name)
                    
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
                
            if manga_txt and manga_txt not in ['...', '…', '‥']:
                dialogue_items.append({
                    'box': box,
                    'txt': manga_txt,
                    'score': score,
                    'x1': x1, 'y1': y1,
                    'x2': x2, 'y2': y2,
                    'w': w, 'h': h
                })
                
        results = []
        if name_candidates:
            # Seleciona o nome mais confiante / à esquerda
            best_name = min(name_candidates, key=lambda n: n[0][0][0])
            results.append(best_name)
            
        if dialogue_items:
            # Ordena diálogo de forma coerente de cima para baixo
            h_ref = calculate_dominant_font_height(dialogue_items)
            row_h = max(12.0, 0.6 * h_ref) if h_ref > 0 else 20.0
            dialogue_items = sorted(dialogue_items, key=lambda d: (round(d['y1'] / row_h), d['x1']))
            
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
    Motor de tradução inteligente para jogos:
    1. Primário: Groq AI (Qwen-2.5 27B) - autocorreção contextual de OCR e linguagem natural de jogos
    2. Secundário: Fallback clássico para MyMemory / Google Translate se offline ou sem chave
    """
    def __init__(self, source='ja', target='pt'):
        self.source = source[:2].lower()
        self.target = target[:2].lower()
        
        # 1. Tenta inicializar cliente Groq
        self.groq_client = None
        groq_key = os.getenv("GROQ_API_KEY", "").strip()
        if groq_key and not groq_key.startswith("your_"):
            try:
                from groq import Groq
                self.groq_client = Groq(api_key=groq_key)
                print(f"[{time.strftime('%H:%M:%S')}] Motor de Tradução por IA ativado (Groq - Qwen)!")
            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] Aviso ao inicializar Groq ({e}). Usando modo tradicional.")
                
        # 2. Instancia provedores tradicionais de fallback
        mymemory_codes = {
            'ja': 'ja-JP',
            'pt': 'pt-BR',
            'en': 'en-US',
            'es': 'es-ES'
        }
        src_tag = mymemory_codes.get(self.source, 'ja-JP')
        tgt_tag = mymemory_codes.get(self.target, 'pt-BR')
        
        try:
            self.mymemory = MyMemoryTranslator(source=src_tag, target=tgt_tag)
        except Exception:
            self.mymemory = None
            
        try:
            self.google = GoogleTranslator(source=self.source, target=self.target)
        except Exception:
            self.google = None
        
    LANG_NAMES = {
        'pt': 'português do Brasil',
        'en': 'inglês',
        'es': 'espanhol',
        'ja': 'japonês'
    }

    def translate(self, text, is_name=False):
        text = text.strip()
        if not text:
            return ""
            
        # Tentativa 1: Tradução com IA Contextual (Groq)
        if self.groq_client:
            source_name = self.LANG_NAMES.get(self.source, self.source)
            target_name = self.LANG_NAMES.get(self.target, self.target)
            
            if is_name:
                system_prompt = (
                    f"Você é um especialista em localização profissional de jogos eletrônicos ({source_name} para {target_name}).\n"
                    f"O texto fornecido é o nome de um personagem ou interlocutor capturado via OCR da tela do jogo em tempo real e pode conter pequenas distorções de caracteres causadas por fontes estilizadas.\n"
                    f"Regras:\n"
                    f"1. Se for um nome próprio de personagem (real ou fantasia), deduza a grafia oficial ocidental consagrada e mantenha-a sem traduzir literalmente (ex: Chocola, Vanilla, Cloud, etc.).\n"
                    f"2. Se for um cargo, título ou apelido de NPC (ex: 'Guarda', 'Ferreiro', 'Elder'), traduza de forma natural para {target_name}.\n"
                    f"3. Retorne EXCLUSIVAMENTE o nome final, sem aspas e sem explicações adicionais."
                )
            else:
                system_prompt = (
                    f"Você é um tradutor especialista em localização profissional de jogos eletrônicos ({source_name} para {target_name}).\n"
                    f"O texto fornecido foi capturado por OCR da tela do jogo em tempo real. Devido a fontes estilizadas, efeitos de contorno e elementos visuais de fundo, o OCR pode conter pequenas trocas visuais de caracteres ou pontuações imperfeitas.\n"
                    f"Diretrizes:\n"
                    f"1. Identifique a fala pretendida no contexto narrativo da cena e dos personagens do jogo, corrigindo silenciosamente eventuais trocas ou ruídos de caracteres causados pelo OCR.\n"
                    f"2. Produza uma tradução fluida, imersiva e natural para {target_name}, preservando fielmente o tom, a emoção e o estilo dos personagens.\n"
                    f"3. Retorne EXCLUSIVAMENTE a tradução final direta, sem aspas, sem notas explicativas e sem comentários adicionais."
                )
                
            for model_candidate in ["qwen/qwen3.8-27b", "groq/compound-mini"]:
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
                    
        # Tentativa 2: Fallback para MyMemory
        if self.mymemory:
            try:
                res = self.mymemory.translate(text)
                if res and not any(err in res.lower() for err in ["error 500", "server error", "please try again"]):
                    return res.strip()
            except Exception:
                pass
                
        # Tentativa 3: Fallback para Google
        if self.google:
            try:
                res = self.google.translate(text)
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
    - source_lang != 'ja': Usa EasyOCREngine (Motor de alta precisão para alfabeto latino)
    """
    def __init__(self, source_lang='ja', target_lang='en', use_gpu=None):
        if use_gpu is None:
            use_gpu = torch.cuda.is_available()
            
        device_label = "Placa de Vídeo (GPU)" if use_gpu else "Processador (CPU)"
        print(f"[{time.strftime('%H:%M:%S')}] Inicializando Tradutor de Jogos [{device_label}]...")
        
        self.source_lang = source_lang
        self.target_lang = target_lang
        
        if source_lang == 'ja':
            self.engine = MangaOCREngine(use_gpu=use_gpu)
        else:
            self.engine = EasyOCREngine(lang=source_lang, use_gpu=use_gpu)
            
        self.translator = TranslationEngine(source=source_lang, target=target_lang)
        
        self.translation_cache = {}
        self.last_detected_raw = ""
        self.last_results = []
        self.last_confidence = 0.0
        
        print(f"[{time.strftime('%H:%M:%S')}] Tradutor Pronto para uso! (Destino: {target_lang.upper()})")

    def process_image(self, image_data, offset_x=0, offset_y=0, on_intermediate=None):
        if isinstance(image_data, str):
            if not os.path.exists(image_data):
                return []
            image_data = cv2.imread(image_data)
            if image_data is None:
                return []
            image_data = cv2.cvtColor(image_data, cv2.COLOR_BGR2RGB)

        start_time = time.time()
        
        boxes = self.engine.extract_text_boxes(image_data, offset_x=offset_x, offset_y=offset_y)
        
        if not boxes:
            self.last_detected_raw = ""
            self.last_results = []
            self.last_confidence = 0.0
            return []
            
        all_texts = " | ".join([item[1] for item in boxes])
        current_conf = float(np.mean([item[2] for item in boxes])) if boxes else 0.0
        
        # Trava de Estabilidade de Cena (Fuzzy Match / Anti-Jitter)
        # Se o texto atual for similar ao frame anterior (>= 65%), o jogador ainda está na mesma cena!
        if self.last_detected_raw and self.last_results:
            similarity = compute_text_similarity(all_texts, self.last_detected_raw)
            if similarity >= 0.65:
                # Se o texto novo for uma extensão da frase (ex: efeito de digitação completando as últimas palavras),
                # PERMITE atualizar para nunca travar em frases cortadas pela metade!
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
            else:
                if not is_meaningful_text(cleaned_txt, source_lang=self.source_lang):
                    continue
            valid_items.append((box, cleaned_txt, score, is_name))

        if not valid_items:
            return []

        # 2. Feedback visual imediato: se houver itens que ainda não estão no cache,
        # emite o texto original com '[Traduzindo com IA...]' para a interface atualizar instantaneamente!
        if on_intermediate:
            preliminary = []
            needs_translation = False
            for box, cleaned_txt, score, is_name in valid_items:
                cache_key = f"{'N:' if is_name else 'D:'}{cleaned_txt}"
                if cache_key in self.translation_cache:
                    tr = self.translation_cache[cache_key]
                else:
                    tr = "[Traduzindo com IA...]"
                    needs_translation = True
                preliminary.append({
                    'original': cleaned_txt,
                    'traducao': tr,
                    'box': box,
                    'confidence': score
                })
            if needs_translation:
                try:
                    on_intermediate(preliminary)
                except Exception:
                    pass

        # 3. Tradução completa (com cache)
        resultados_finais = []
        for box, cleaned_txt, score, is_name in valid_items:
            cache_key = f"{'N:' if is_name else 'D:'}{cleaned_txt}"
            if cache_key in self.translation_cache:
                traducao = self.translation_cache[cache_key]
            else:
                traducao = self.translator.translate(cleaned_txt, is_name=is_name)
                if traducao and not traducao.startswith("["):
                    self.translation_cache[cache_key] = traducao
                    
            resultados_finais.append({
                'original': cleaned_txt,
                'traducao': traducao,
                'box': box,
                'confidence': score
            })
            
        self.last_results = resultados_finais
        print(f"[{time.strftime('%H:%M:%S')}] Ciclo concluido em {time.time() - start_time:.2f}s ({len(resultados_finais)} itens)")
        return resultados_finais

if __name__ == "__main__":
    ocr = OCRTranslator(source_lang='ja', target_lang='en')
    print("Módulo OCR pronto!")
