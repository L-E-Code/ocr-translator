import mss
import mss.tools

def get_available_monitors():
    """
    Retorna uma lista dos monitores disponíveis (ignorando o índice 0, que é a união de todos).
    """
    with mss.MSS() as sct:
        # sct.monitors[0] é a área total de todos os monitores combinados.
        # Os monitores individuais começam no índice 1.
        return sct.monitors[1:]

def capture_screen(monitor, output_filename="capture.png"):
    """
    Captura a região (ou monitor inteiro) fornecida e salva em um arquivo.
    """
    with mss.MSS() as sct:
        # Pega a captura (como pixels brutos)
        sct_img = sct.grab(monitor)
        
        # Salva em um arquivo
        mss.tools.to_png(sct_img.rgb, sct_img.size, output=output_filename)
        
        print(f"Captura salva com sucesso em: {output_filename}")
        
        return output_filename

def cli_select_monitor():
    """
    Interface de linha de comando básica para listar e selecionar o monitor.
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

if __name__ == "__main__":
    # 1. Pede para o usuário escolher o monitor no terminal
    monitor_selecionado = cli_select_monitor()
    
    # 2. Tira o print do monitor inteiro escolhido
    print("\nIniciando captura da tela inteira...")
    capture_screen(monitor_selecionado)
