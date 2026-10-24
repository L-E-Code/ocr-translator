import sys
import ssl
from PyQt6.QtWidgets import QApplication

from logger_config import setup_logger
logger = setup_logger()

# Disables strict SSL verification in urllib to allow the automatic
# download of the EasyOCR models on machines with outdated local certificates
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass



def run_cli():
    """Interactive wizard mode in the terminal (CLI) for backward compatibility."""
    # Heavy imports (PyTorch, OCR) live here so the GUI does not pay for them when it opens
    from capture import cli_select_monitor, cli_select_focus_area
    from ocr import OCRTranslator
    from overlay import OverlayWindow
    from worker import WorkerThread
    import ui_theme
    from config_manager import load_config

    print("=== OCR Translator - Real-Time Translator (Terminal Mode) ===")
    
    # 1. Initializes the PyQt graphical application
    app = QApplication(sys.argv)
    ui_theme.apply_theme(app)
    
    # 2. Monitor selection
    monitor = cli_select_monitor()
    
    # 3. Area selection
    capture_region = cli_select_focus_area(monitor)
    
    # 4. Display mode selection
    print("\n=== Display Mode ===")
    print("[1] Panel Mode (side window in subtitle style) [Default]")
    print("[2] Ghost Mode (transparent bars overlaid on the screen)")
    
    mode_choice = input("\nChoose how you want to see the translations (1 or 2) [Default: 1]: ").strip()

    while mode_choice not in ['1', '2', '']:
        print("Invalid option. Enter 1 or 2 (or Enter for Default).")
        mode_choice = input("Choose how you want to see the translations (1 or 2) [Default: 1]: ").strip()
        
    panel_mode = (mode_choice != '2')
    
    # 5. Translation language selection
    print("\n=== Translation Languages ===")
    print("[1] Japanese -> English [Default]")
    print("[2] English -> Brazilian Portuguese")
    
    lang_choice = input("Choose the translation option (1 or 2) [Default: 1]: ").strip()
    if lang_choice == '2':
        source_lang = 'en'
        target_lang = 'pt'
    else:
        source_lang = 'ja'
        target_lang = 'en'
        
    # 6. Initializes the OCR
    ocr_engine = OCRTranslator(source_lang=source_lang, target_lang=target_lang)
    
    # 7. Creates the chosen window
    if panel_mode:
        from sidebar import SidebarWindow
        ui_window = SidebarWindow()
    else:
        ui_window = OverlayWindow(monitor)
        
    ui_window.show()
    
    # 8. Starts the continuous capture thread
    worker = WorkerThread(capture_region, ocr_engine, debounce_ms=load_config().get("debounce_ms", 200))
    worker.update_signal.connect(ui_window.update_texts)
    
    if panel_mode:
        ui_window.pause_toggled.connect(worker.set_paused)
        ui_window.reload_requested.connect(worker.request_reload)
        
    worker.start()
    
    print("\n[!] System active and running! To quit, close the window or press Ctrl+C in this terminal.\n")
    
    sys.exit(app.exec())

if __name__ == "__main__":
    if "--cli" in sys.argv:
        run_cli()
    else:
        from launcher import run_gui
        run_gui()
