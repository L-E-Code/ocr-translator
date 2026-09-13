import abc
import os
import re
import time
import logging
import cv2
import numpy as np
import torch
from dotenv import load_dotenv
from deep_translator import MyMemoryTranslator, GoogleTranslator

# Carrega variáveis do arquivo .env local
load_dotenv()

# Ocultar avisos internos
logging.getLogger("easyocr").setLevel(logging.ERROR)

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
    Aplica visão computacional especializada para caixas de diálogo e nomes em jogos:
    - Upscale de 2.0x com interpolação Lanczos4 (suaviza curvas de fontes)
    - Filtro Bilateral para preservar bordas nítidas dos kanjis enquanto remove ruídos e texturas de fundo
    - CLAHE (Contrast Limited Adaptive Histogram Equalization) para alto contraste local equilibrado
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
    
    # 2. Converte para escala de cinza e aplica filtro bilateral
    gray = cv2.cvtColor(up, cv2.COLOR_RGB2GRAY)
    filtered = cv2.bilateralFilter(gray, 7, 50, 50)
    
    # 3. Contraste adaptativo CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    clean_img = clahe.apply(filtered)
    
    return clean_img, scale_factor

def clean_ocr_punctuation(text):
    """
    Higieniza pontuação e caracteres de fechamento corrompidos pelo OCR.
    """
    text = re.sub(r'\[$', 'た。', text)
    text = re.sub(r'V$', '」', text)
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
            adjust_contrast=0.8,
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
                adj_box = [[int(pt[0] / scale) + offset_x, int(pt[1] / scale) + offset_y] for pt in it['box']]
                results.append((adj_box, it['txt'], it['score'], True))
                
        # 5. Agrupamento espacial das linhas de diálogo (elimina textos de cenário periféricos)
        if dialogue_candidates:
            clustered_dialogue = cluster_dialogue_lines(dialogue_candidates, h_ref)
            
            # Ordena diálogo de cima para baixo
            clustered_dialogue = sorted(clustered_dialogue, key=lambda d: d['y1'])
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
            'es': 'es-ES',
            'ko': 'ko-KR',
            'zh': 'zh-CN',
            'fr': 'fr-FR',
            'de': 'de-DE',
            'it': 'it-IT'
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
        
    def translate(self, text, is_name=False):
        text = text.strip()
        if not text:
            return ""
            
        # Tentativa 1: Tradução com IA Contextual (Groq)
        if self.groq_client:
            target_name = "português do Brasil" if self.target == 'pt' else "inglês"
            if is_name:
                system_prompt = (
                    f"Você é um tradutor especialista de jogos e animes. O texto fornecido é o nome de um personagem de jogo lido por OCR. "
                    f"Se for um nome próprio conhecido (como Vanilla de Nekopara), escreva o nome correto no padrão ocidental. "
                    f"Retorne EXCLUSIVAMENTE o nome final, sem aspas, sem explicações."
                )
            else:
                system_prompt = (
                    f"Você é um tradutor especialista de jogos e visual novels. O texto a seguir foi obtido por OCR da tela e pode conter pequenos erros de leitura de caracteres. "
                    f"Deduza a fala correta pelo contexto e traduza naturalmente para {target_name} com linguagem fluida de jogos/animes. "
                    f"Retorne EXCLUSIVAMENTE a tradução final direta, sem aspas, sem notas adicionais."
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
    """
    def __init__(self, source_lang='ja', target_lang='pt', use_gpu=None):
        if use_gpu is None:
            use_gpu = torch.cuda.is_available()
            
        device_label = "Placa de Vídeo (GPU)" if use_gpu else "Processador (CPU)"
        print(f"[{time.strftime('%H:%M:%S')}] Inicializando Tradutor de Jogos [{device_label}]...")
        
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.engine = EasyOCREngine(lang=source_lang, use_gpu=use_gpu)
        self.translator = TranslationEngine(source=source_lang, target=target_lang)
        
        self.translation_cache = {}
        self.last_detected_raw = ""
        self.last_results = []
        
        print(f"[{time.strftime('%H:%M:%S')}] Tradutor Pronto para uso! (Destino: {target_lang.upper()})")

    def process_image(self, image_data, offset_x=0, offset_y=0):
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
            return []
            
        all_texts = " | ".join([item[1] for item in boxes])
        if all_texts and all_texts == self.last_detected_raw:
            return self.last_results
            
        self.last_detected_raw = all_texts
        resultados_finais = []
        
        for item in boxes:
            box, txt, score = item[0], item[1], item[2]
            is_name = item[3] if len(item) > 3 else False
            
            cleaned_txt = txt.strip()
            if not is_meaningful_text(cleaned_txt, source_lang=self.source_lang):
                continue
                
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
    ocr = OCRTranslator(source_lang='ja', target_lang='pt')
    print("Módulo OCR pronto!")
