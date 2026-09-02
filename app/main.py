import sys
import time
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QThread, pyqtSignal

# Importa nossos módulos
from capture import cli_select_monitor, capture_screen
from ocr import OCRTranslator
from overlay import OverlayWindow

class WorkerThread(QThread):
    """
    Thread em segundo plano que fica tirando print e mandando pro OCR
    para nao congelar a interface grafica transparente.
    """
    update_signal = pyqtSignal(list)
    
    def __init__(self, monitor_region, ocr_engine):
        super().__init__()
        self.monitor_region = monitor_region
        self.ocr_engine = ocr_engine
        self.running = True
        
    def run(self):
        while self.running:
            # 1. Tira o print
            image_path = capture_screen(self.monitor_region, "temp_capture.png")
            
            # 2. Le e traduz
            resultados = self.ocr_engine.process_image(image_path)
            
            # 3. Manda os dados para a tela transparente
            self.update_signal.emit(resultados)
            
            # Pausa breve antes do proximo ciclo para nao derreter o processador
            time.sleep(1)

    def stop(self):
        self.running = False

if __name__ == "__main__":
    print("=== Inicializando o Tradutor de Tela (Fase 3) ===")
    
    # 1. Pede o monitor para o usuario no terminal
    monitor = cli_select_monitor()
    
    # 2. Inicializa o motor de Inteligencia Artificial (antes de abrir a tela)
    ocr_engine = OCRTranslator(target_lang='en', use_gpu=False)
    
    # 3. Inicializa o aplicativo grafico
    app = QApplication(sys.argv)
    
    # 4. Cria a janela transparente em cima do monitor escolhido
    overlay = OverlayWindow(monitor)
    overlay.show()
    
    # 5. Inicia a Thread de captura continua
    worker = WorkerThread(monitor, ocr_engine)
    worker.update_signal.connect(overlay.update_texts)
    worker.start()
    
    print("\n[!] Sistema rodando em tempo real. Pressione Ctrl+C neste terminal para encerrar.")
    
    # 6. Trava o script no loop do aplicativo grafico
    sys.exit(app.exec())
