import easyocr
import time
import os
import logging

# Ocultar alguns avisos
logging.getLogger("easyocr").setLevel(logging.ERROR)

def extract_text(image_path, lang='ja'):
    """
    Usa o EasyOCR para extrair texto e coordenadas de uma imagem.
    """
    if not os.path.exists(image_path):
        print(f"[ERRO] Imagem nao encontrada: {image_path}")
        print("Execute a captura de tela (passo 1) antes de rodar o OCR.")
        return []

    print(f"[{time.strftime('%H:%M:%S')}] Inicializando o modelo de IA do EasyOCR...")
    
    reader = easyocr.Reader([lang, 'en'], gpu=True)
    
    print(f"[{time.strftime('%H:%M:%S')}] Iniciando leitura da imagem: {image_path}")
    start_time = time.time()
    
    result = reader.readtext(image_path)
    
    end_time = time.time()
    
    if not result:
         print("\n-> A IA nao encontrou nenhum texto nesta imagem.")
         return []
         
    resultados_finais = []
    
    print(f"\n--- Leitura concluida em {end_time - start_time:.2f} segundos ---")
    print(f"Foram encontrados {len(result)} blocos de texto:\n")
    
    for idx, line in enumerate(result):
        box = line[0] 
        txt = line[1]
        score = line[2]
        
        resultados_finais.append({
            'text': txt,
            'box': box,
            'confidence': score
        })
        
        print(f"Bloco {idx + 1}:")
        print(f"  Texto: {txt}")
        print(f"  Certeza da IA: {score:.2%}")
        print(f"  Posicao X/Y (superior esq): {int(box[0][0])}, {int(box[0][1])}")
        print("-" * 30)
        
    return resultados_finais

if __name__ == "__main__":
    extract_text("capture.png")
