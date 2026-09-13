import sys
import time
import mss
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QThread, pyqtSignal

# Importa nossos módulos
from capture import cli_select_monitor, cli_select_focus_area, get_roi_region, capture_screen_np
from ocr import OCRTranslator
from overlay import OverlayWindow

class WorkerThread(QThread):
    """
    Thread contínua que captura frames diretamente na memória RAM
    e envia para a IA processar sem travar a interface.
    """
    update_signal = pyqtSignal(list)
    
    def __init__(self, capture_region, ocr_engine):
        super().__init__()
        self.capture_region = capture_region
        self.offset_x = capture_region.get('offset_x', 0)
        self.offset_y = capture_region.get('offset_y', 0)
        self.ocr_engine = ocr_engine
        self.running = True
        self.paused = False
        
    def set_paused(self, is_paused):
        self.paused = is_paused

    def run(self):
        # Cria uma instância MSS reutilizável na thread para evitar recriação constante
        with mss.MSS() as sct:
            while self.running:
                if self.paused:
                    time.sleep(0.5)
                    continue

                # 1. Captura direto na RAM como array NumPy
                frame_np = capture_screen_np(self.capture_region, sct=sct)
                
                # 2. Processa OCR e Tradução com cache
                resultados = self.ocr_engine.process_image(
                    frame_np, 
                    offset_x=self.offset_x, 
                    offset_y=self.offset_y
                )
                
                # 3. Emite os dados para a interface visual
                self.update_signal.emit(resultados)
                
                # Intervalo saudável para economizar CPU e requisições de rede
                time.sleep(1.0)

    def stop(self):
        self.running = False

if __name__ == "__main__":
    print("=== OCR Translator - Tradutor de Jogos em Tempo Real ===")
    
    # 1. Inicializa o aplicativo gráfico do PyQt
    app = QApplication(sys.argv)
    
    # 2. Seleção do Monitor
    monitor = cli_select_monitor()
    
    # 3. Seleção da Área Prioritária (Otimização de Velocidade ou Seleção com Mouse)
    capture_region = cli_select_focus_area(monitor)
    
    # 3. Seleção do Modo de Exibição
    print("\n=== Modo de Exibicao ===")
    print("[1] Modo Painel (Janela de leitura separada estilo legendas)")
    print("[2] Modo Fantasma (Tarjas transparentes grudadas sobre o jogo)")
    
    escolha_modo = ""
    while escolha_modo not in ['1', '2']:
        escolha_modo = input("Escolha como quer ver as traducoes (1 ou 2): ").strip()
        
    modo_painel = (escolha_modo == '1')
    
    # 4. Inicializa o motor de IA (detecta GPU automaticamente se disponível)
    ocr_engine = OCRTranslator(target_lang='en')
    
    # 5. Cria a janela escolhida
    if modo_painel:
        from sidebar import SidebarWindow
        ui_window = SidebarWindow()
    else:
        ui_window = OverlayWindow(monitor)
        
    ui_window.show()
    
    # 7. Inicia a Thread de captura contínua na memória RAM
    worker = WorkerThread(capture_region, ocr_engine)
    worker.update_signal.connect(ui_window.update_texts)
    
    if modo_painel:
        ui_window.pause_toggled.connect(worker.set_paused)
        
    worker.start()
    
    print("\n[!] Sistema ativo e rodando! Para encerrar, feche a janela ou aperte Ctrl+C neste terminal.\n")
    
    sys.exit(app.exec())
