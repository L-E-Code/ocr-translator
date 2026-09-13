import easyocr
import time
import os
import re
import logging
import cv2
import numpy as np
from deep_translator import MyMemoryTranslator, GoogleTranslator

# Ocultar avisos internos
logging.getLogger("easyocr").setLevel(logging.ERROR)

def contains_japanese(text):
    """
    Verifica se o texto contém pelo menos um caractere japonês
    (Hiragana, Katakana ou Kanji).
    """
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]', text))

def is_meaningful_japanese(text):
    """
    Filtra pequenos ruídos de 1 a 2 caracteres aleatórios (ex: ícones ou bordas que viram 'び三ヲ'),
    focando em falas e diálogos reais.
    """
    cleaned = re.sub(r'[\s\W_]+', '', text)
    if len(cleaned) < 3:
        # Se tiver menos de 3 caracteres, só aceita se tiver Kanji real
        return bool(re.search(r'[\u4E00-\u9FAF]', cleaned))
    return contains_japanese(cleaned)

def preprocess_for_ocr(image):
    """
    Aplica melhorias de visão computacional na imagem para que
    o OCR consiga ler kanjis e fontes estilizadas com máxima nitidez.
    """
    if isinstance(image, str):
        if not os.path.exists(image):
            return None
        image = cv2.imread(image)
        if image is None:
            return None
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    # 1. Upscale de 2x com interpolação cúbica para destacar os radicais dos Kanjis
    h, w = image.shape[:2]
    if w < 3000 and h < 2000:
        image = cv2.resize(image, (int(w * 2.0), int(h * 2.0)), interpolation=cv2.INTER_CUBIC)

    return image

class TranslationEngine:
    """
    Motor de tradução resiliente:
    Usa o MyMemory como provedor primário (ultra estável, sem bloqueio de Error 500)
    e Google como fallback.
    """
    def __init__(self, source='ja-JP', target='en-US'):
        self.mymemory = MyMemoryTranslator(source=source, target=target)
        self.google = GoogleTranslator(source='ja', target='en')
        
    def translate(self, text):
        text = text.strip()
        if not text:
            return ""
            
        # 1. Tenta MyMemory (Excelente para diálogos em japonês)
        try:
            res = self.mymemory.translate(text)
            if res and not any(err in res.lower() for err in ["error 500", "server error", "please try again"]):
                return res.strip()
        except Exception:
            pass
            
        # 2. Fallback para Google
        try:
            res = self.google.translate(text)
            if res and not any(err in res.lower() for err in ["error 500", "server error", "please try again"]):
                return res.strip()
        except Exception:
            pass
            
        return "[Traduzindo...]"

import torch

class OCRTranslator:
    def __init__(self, ocr_lang='ja', target_lang='en', use_gpu=None):
        if use_gpu is None:
            use_gpu = torch.cuda.is_available()
            
        device_label = "Placa de Vídeo (GPU)" if use_gpu else "Processador (CPU)"
        print(f"[{time.strftime('%H:%M:%S')}] Inicializando IA [{device_label}] e Tradutor Resiliente...")
        self.reader = easyocr.Reader([ocr_lang, 'en'], gpu=use_gpu)
        self.translator = TranslationEngine(source='ja-JP', target='en-US')
        
        # Cache de tradução para reaproveitar frases idênticas instantaneamente
        self.translation_cache = {}
        self.last_detected_raw = ""
        self.last_results = []
        
        print(f"[{time.strftime('%H:%M:%S')}] IA Pronta para uso!")

    def process_image(self, image_data, offset_x=0, offset_y=0):
        """
        Lê a imagem (array numpy na RAM ou arquivo), extrai falas em japonês e traduz.
        """
        processed_img = preprocess_for_ocr(image_data)
        if processed_img is None:
            return []
            
        start_time = time.time()
        
        # Parâmetros otimizados para texto de jogos
        result = self.reader.readtext(
            processed_img,
            paragraph=True,       # Agrupa linhas da mesma fala em uma única sentença
            contrast_ths=0.1,     # Alta sensibilidade para capturar fontes coloridas
            adjust_contrast=0.8,  # Destaca o texto contra fundos dinâmicos
            mag_ratio=1.2
        )
        
        if not result:
            self.last_detected_raw = ""
            self.last_results = []
            return []
             
        # Assinatura dos textos encontrados para o cache
        raw_texts = []
        for item in result:
            txt = item[1].strip() if len(item) > 1 else ""
            if txt and is_meaningful_japanese(txt):
                raw_texts.append(txt)
                
        all_texts = " | ".join(raw_texts)
        
        # Se os textos forem idênticos aos do último ciclo, usa o cache instantaneamente
        if all_texts and all_texts == self.last_detected_raw:
            return self.last_results
            
        self.last_detected_raw = all_texts
        resultados_finais = []
        scale_factor = 2.0 # Fator de escala do preprocess
        
        for item in result:
            if len(item) == 3:
                box, txt, score = item
            else:
                box, txt = item
                score = 0.95
                
            txt = txt.strip()
            
            # FILTRO: Apenas falas japonesas com conteúdo real
            if not is_meaningful_japanese(txt):
                continue
                
            # Limpa ruídos de pontuação quebrada no início e fim
            cleaned_txt = re.sub(r'^[^\w『「【\(\]]+|[^\w』」】\)\.]+$', '', txt)
            if len(cleaned_txt) < 2:
                continue
                
            # Ajusta coordenadas se a imagem foi ampliada
            adjusted_box = [
                [int(pt[0] / scale_factor) + offset_x, int(pt[1] / scale_factor) + offset_y]
                for pt in box
            ]
            
            # Busca no cache de frases válidas (nunca salva erros no cache)
            if cleaned_txt in self.translation_cache:
                traducao = self.translation_cache[cleaned_txt]
            else:
                traducao = self.translator.translate(cleaned_txt)
                if traducao and not traducao.startswith("["):
                    self.translation_cache[cleaned_txt] = traducao
            
            resultados_finais.append({
                'original': cleaned_txt,
                'traducao': traducao,
                'box': adjusted_box,
                'confidence': score
            })
            
        self.last_results = resultados_finais
        print(f"[{time.strftime('%H:%M:%S')}] Ciclo concluido em {time.time() - start_time:.2f}s ({len(resultados_finais)} falas traduzidas)")
        return resultados_finais

if __name__ == "__main__":
    ocr = OCRTranslator(target_lang='en', use_gpu=False)
    if os.path.exists("capture.png"):
        resultados = ocr.process_image("capture.png")
        for r in resultados:
            print(f"Original: {r['original']} -> {r['traducao']}")
