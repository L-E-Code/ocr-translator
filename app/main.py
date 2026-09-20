import sys
import ssl
import time
import mss
from PyQt6.QtWidgets import QApplication

from logger_config import setup_logger, get_logger
logger = setup_logger()

# Desativa verificacao restrita de SSL do urllib para permitir o download
# automatico dos modelos do EasyOCR em maquinas com certificados locais desatualizados
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass

from capture import cli_select_monitor, cli_select_focus_area, capture_screen_np
from ocr import OCRTranslator
from overlay import OverlayWindow
from worker import WorkerThread


def run_cli():
    """Modo assistente interativo via terminal (CLI) para retrocompatibilidade."""
    print("=== OCR Translator - Tradutor em Tempo Real (Modo Terminal) ===")
    
    # 1. Inicializa o aplicativo gráfico do PyQt
    app = QApplication(sys.argv)
    
    # 2. Seleção do Monitor
    monitor = cli_select_monitor()
    
    # 3. Seleção da Área
    capture_region = cli_select_focus_area(monitor)
    
    # 4. Seleção do Modo de Exibição
    print("\n=== Modo de Exibição ===")
    print("[1] Modo Painel (Janela lateral estilo legendas) [Padrão]")
    print("[2] Modo Fantasma (Tarjas transparentes sobrepostas à tela)")
    
    escolha_modo = input("\nEscolha como quer ver as traduções (1 ou 2) [Padrão: 1]: ").strip()

    while escolha_modo not in ['1', '2', '']:
        print("Opção inválida. Digite 1 ou 2 (ou Enter para Padrão).")
        escolha_modo = input("Escolha como quer ver as traduções (1 ou 2) [Padrão: 1]: ").strip()
        
    modo_painel = (escolha_modo != '2')
    
    # 5. Seleção dos Idiomas de Tradução
    print("\n=== Idiomas de Tradução ===")
    print("[1] Japonês -> Inglês [Padrão]")
    print("[2] Inglês -> Português do Brasil")
    
    escolha_lang = input("Escolha a opção de tradução (1 ou 2) [Padrão: 1]: ").strip()
    if escolha_lang == '2':
        source_lang = 'en'
        target_lang = 'pt'
    else:
        source_lang = 'ja'
        target_lang = 'en'
        
    # 6. Inicializa o OCR 
    ocr_engine = OCRTranslator(source_lang=source_lang, target_lang=target_lang)
    
    # 7. Cria a janela escolhida
    if modo_painel:
        from sidebar import SidebarWindow
        ui_window = SidebarWindow()
    else:
        ui_window = OverlayWindow(monitor)
        
    ui_window.show()
    
    # 8. Inicia a Thread de captura contínua
    worker = WorkerThread(capture_region, ocr_engine)
    worker.update_signal.connect(ui_window.update_texts)
    
    if modo_painel:
        ui_window.pause_toggled.connect(worker.set_paused)
        ui_window.reload_requested.connect(worker.request_reload)
        
    worker.start()
    
    print("\n[!] Sistema ativo e rodando! Para encerrar, feche a janela ou aperte Ctrl+C neste terminal.\n")
    
    sys.exit(app.exec())

if __name__ == "__main__":
    if "--cli" in sys.argv:
        run_cli()
    else:
        from launcher import run_gui
        run_gui()
