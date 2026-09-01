import easyocr
import time
import os
import logging
from deep_translator import GoogleTranslator

# Ocultar alguns avisos
logging.getLogger("easyocr").setLevel(logging.ERROR)

def extract_and_translate(image_path, ocr_lang='ja', target_lang='en'):
    """
    Usa o EasyOCR para extrair texto de uma imagem e traduz com o Deep Translator.
    """
    if not os.path.exists(image_path):
        print(f"[ERRO] Imagem nao encontrada: {image_path}")
        print("Execute a captura de tela (passo 1) antes de rodar o OCR.")
        return []

    print(f"[{time.strftime('%H:%M:%S')}] Inicializando Inteligencia Artificial e Motor de Traducao...")
    
    # Inicia o leitor de imagem (Japones e Ingles)
    reader = easyocr.Reader([ocr_lang, 'en'], gpu=True)
    
    # Inicia o tradutor (Auto-detecta o idioma de origem e traduz para o alvo: Ingles)
    translator = GoogleTranslator(source='auto', target=target_lang)
    
    print(f"[{time.strftime('%H:%M:%S')}] Lendo a imagem e traduzindo... aguarde.")
    start_time = time.time()
    
    # Le a imagem
    result = reader.readtext(image_path)
    
    if not result:
         print("\n-> A IA nao encontrou nenhum texto nesta imagem.")
         return []
         
    resultados_finais = []
    
    print(f"\n--- Processamento concluido em {time.time() - start_time:.2f} segundos ---")
    print(f"Encontrados {len(result)} blocos de texto:\n")
    
    for idx, line in enumerate(result):
        box = line[0] # Coordenadas
        txt = line[1] # Texto lido
        score = line[2] # Confianca da IA
        
        # Ignorar textos muito curtos para nao poluir a tela ou sobrecarregar o tradutor
        if len(txt.strip()) < 2:
            continue
            
        # Traduz o texto extraido
        try:
            traducao = translator.translate(txt)
        except Exception as e:
            traducao = f"[Erro na traducao: {str(e)}]"
        
        resultados_finais.append({
            'original': txt,
            'traducao': traducao,
            'box': box,
            'confidence': score
        })
        
        print(f"Bloco {idx + 1}:")
        print(f"  📝 Original:  {txt}")
        print(f"  🌐 Traducao:  {traducao}")
        print(f"  (Confianca da IA: {score:.1%})")
        print("-" * 40)
        
    return resultados_finais

if __name__ == "__main__":
    # Teste: Tenta ler e traduzir a imagem 'capture.png' para o Ingles, como voce pediu!
    extract_and_translate("capture.png", target_lang='en')
