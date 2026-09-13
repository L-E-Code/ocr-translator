import mss
import numpy as np
import cv2
import os
import json

CONFIG_FILE = "config.json"

def get_available_monitors():
    """
    Retorna uma lista dos monitores disponíveis (ignorando o índice 0, que é a união de todos).
    """
    with mss.MSS() as sct:
        return sct.monitors[1:]

def capture_screen_np(region, sct=None):
    """
    Captura a região fornecida e retorna como array NumPy (RGB) direto na memória RAM,
    sem gravar arquivos no disco e garantindo os canais corretos de cor.
    """
    if sct is None:
        with mss.MSS() as local_sct:
            img = local_sct.grab(region)
            return cv2.cvtColor(np.array(img), cv2.COLOR_BGRA2RGB)
    else:
        img = sct.grab(region)
        return cv2.cvtColor(np.array(img), cv2.COLOR_BGRA2RGB)

def load_saved_roi():
    """
    Carrega a última área personalizada selecionada com o mouse.
    """
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("last_custom_roi")
    except Exception:
        pass
    return None

def save_custom_roi(roi):
    """
    Salva a área personalizada selecionada com o mouse para uso futuro.
    """
    try:
        data = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        data["last_custom_roi"] = roi
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def get_roi_region(monitor, roi_type="full"):
    """
    Calcula a sub-região de captura baseado na área de foco desejada:
    - 'full': Tela inteira
    - 'bottom_third': Terço inferior (caixas de diálogo típicas)
    - 'bottom_half': Metade inferior
    """
    left = monitor['left']
    top = monitor['top']
    width = monitor['width']
    height = monitor['height']
    
    if roi_type == "bottom_third":
        new_top = top + int(height * 0.65)
        new_height = int(height * 0.33)
        return {'left': left, 'top': new_top, 'width': width, 'height': new_height, 'offset_y': int(height * 0.65), 'offset_x': 0}
    elif roi_type == "bottom_half":
        new_top = top + int(height * 0.50)
        new_height = int(height * 0.48)
        return {'left': left, 'top': new_top, 'width': width, 'height': new_height, 'offset_y': int(height * 0.50), 'offset_x': 0}
    else:
        reg = dict(monitor)
        reg['offset_x'] = 0
        reg['offset_y'] = 0
        return reg

def cli_select_monitor():
    """
    Interface de linha de comando para listar e selecionar o monitor.
    """
    monitors = get_available_monitors()
    
    print("\n=== Seleção de Monitor ===")
    for i, monitor in enumerate(monitors):
        print(f"[{i + 1}] Monitor {i + 1} (Resolução: {monitor['width']}x{monitor['height']})")
    
    while True:
        try:
            escolha = input(f"\nSelecione o monitor que o jogo está rodando (1-{len(monitors)}): ")
            indice = int(escolha) - 1
            
            if 0 <= indice < len(monitors):
                monitor_escolhido = monitors[indice]
                print(f"-> Monitor {indice + 1} selecionado!")
                return monitor_escolhido
            else:
                print("Opção inválida. Digite um número correspondente a um dos monitores.")
        except ValueError:
            print("Por favor, digite um número válido.")

def cli_select_focus_area(monitor):
    """
    Menu para selecionar a área de foco prioritária para acelerar a IA.
    Suporta seleção interativa com mouse ou presets rápidos.
    """
    saved_roi = load_saved_roi()
    
    print("\n=== Área de Foco da Tela (Velocidade do OCR) ===")
    print("[1] Selecionar com o Mouse (Clicar e arrastar exatamente sobre o diálogo) - MÁXIMA PRECISÃO")
    
    idx_saved = None
    if saved_roi:
        idx_saved = "2"
        w = saved_roi['width']
        h = saved_roi['height']
        print(f"[2] Usar Última Área Salva ({w}x{h} px)")
        print("[3] Caixa de Diálogos Padrão (Terço inferior da tela) - Rápido (~1s)")
        print("[4] Metade Inferior da Tela - Rápido (~2s)")
        print("[5] Tela Inteira (Todos os menus e HUD) - Mais lento (~15-25s)")
    else:
        print("[2] Caixa de Diálogos Padrão (Terço inferior da tela) - Rápido (~1s)")
        print("[3] Metade Inferior da Tela - Rápido (~2s)")
        print("[4] Tela Inteira (Todos os menus e HUD) - Mais lento (~15-25s)")
    
    while True:
        escolha = input("\nSelecione uma opção: ").strip()
        
        if escolha == "1":
            from selector import select_region_interactive
            print("\n-> Abra a tela do jogo! Clique e arraste um retângulo sobre o diálogo.")
            roi = select_region_interactive(monitor)
            if roi:
                print(f"-> Área selecionada com sucesso: {roi['width']}x{roi['height']} pixels!")
                save_custom_roi(roi)
                return roi
            else:
                print("Seleção cancelada. Usando caixa de diálogos padrão.")
                return get_roi_region(monitor, "bottom_third")
                
        elif saved_roi and escolha == "2":
            print("-> Usando última área salva!")
            return saved_roi
            
        elif (saved_roi and escolha == "3") or (not saved_roi and escolha == "2"):
            return get_roi_region(monitor, "bottom_third")
            
        elif (saved_roi and escolha == "4") or (not saved_roi and escolha == "3"):
            return get_roi_region(monitor, "bottom_half")
            
        elif (saved_roi and escolha == "5") or (not saved_roi and escolha == "4"):
            return get_roi_region(monitor, "full")
            
        print("Opção inválida. Tente novamente.")
