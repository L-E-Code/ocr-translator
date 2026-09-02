import easyocr
import time
import os
import logging
from deep_translator import GoogleTranslator

# Ocultar alguns avisos
logging.getLogger("easyocr").setLevel(logging.ERROR)

class OCRTranslator:
    def __init__(self, ocr_lang='ja', target_lang='en', use_gpu=False):
        print(f"[{time.strftime('%H:%M:%S')}] Inicializando IA e Tradutor (aguarde, modelos carregando...)")
        # Inicia o leitor de imagem apenas UMA VEZ para poupar processamento
        self.reader = easyocr.Reader([ocr_lang, 'en'], gpu=use_gpu)
        self.translator = GoogleTranslator(source='auto', target=target_lang)
        print(f"[{time.strftime('%H:%M:%S')}] IA Pronta!")

    def process_image(self, image_path):
        """
        Lê a imagem, extrai textos e traduz.
        Retorna a lista de dicionários prontas para o overlay.
        """
        if not os.path.exists(image_path):
            return []
            
        print(f"[{time.strftime('%H:%M:%S')}] Lendo a imagem e traduzindo...")
        start_time = time.time()
        
        result = self.reader.readtext(image_path)
        
        if not result:
            return []
             
        resultados_finais = []
        
        for idx, line in enumerate(result):
            box = line[0]
            txt = line[1]
            score = line[2]
            
            # Ignorar textos muito curtos ou que sejam apenas numeros/letras basicas
            # (Isso ajuda muito na velocidade caso a tela tenha muito texto de UI)
            if len(txt.strip()) < 2:
                continue
                
            print(f"Traduzindo bloco {idx+1}/{len(result)}...", end='\r')
            
            try:
                traducao = self.translator.translate(txt)
            except Exception:
                traducao = ""
            
            resultados_finais.append({
                'original': txt,
                'traducao': traducao,
                'box': box,
                'confidence': score
            })
            
        print(f"--- Ciclo concluido em {time.time() - start_time:.2f} seg ({len(resultados_finais)} blocos) ---")
        return resultados_finais

if __name__ == "__main__":
    # Apenas para teste independente
    ocr = OCRTranslator(target_lang='en', use_gpu=False)
    resultados = ocr.process_image("capture.png")
    for r in resultados:
        print(f"Original: {r['original']} -> {r['traducao']}")
