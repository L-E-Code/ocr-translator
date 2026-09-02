import sys
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QScrollArea, QFrame
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

class SidebarWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        
    def initUI(self):
        self.setWindowTitle("OCR Translator - Painel de Leitura")
        self.resize(400, 600) # Tamanho padrao inicial
        
        # Mantem a janela sempre no topo, para vc poder jogar e ler ao mesmo tempo
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
        
        # Layout principal
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Area rolável para caber bastante texto
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; }")
        
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.scroll_content)
        
        self.layout.addWidget(self.scroll)
        
    def update_texts(self, new_texts):
        """
        Recebe a nova lista de textos traduzidos e atualiza o painel lateral.
        """
        # 1. Limpa os textos antigos
        for i in reversed(range(self.scroll_layout.count())): 
            widget = self.scroll_layout.itemAt(i).widget()
            if widget is not None:
                widget.setParent(None)
            
        # Se nao achou nada, coloca um aviso
        if not new_texts:
            lbl_vazio = QLabel("Nenhum texto detectado...")
            lbl_vazio.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_vazio.setFont(QFont("Arial", 10, QFont.Weight.Bold))
            lbl_vazio.setStyleSheet("color: gray; margin-top: 20px;")
            self.scroll_layout.addWidget(lbl_vazio)
            return

        # 2. Adiciona os novos textos
        for item in new_texts:
            original = item.get('original', '')
            traducao = item.get('traducao', '')
            
            # Pula bloquinhos falhos
            if not original or not traducao:
                continue
                
            frame = QFrame()
            frame.setFrameShape(QFrame.Shape.StyledPanel)
            frame.setStyleSheet("""
                QFrame {
                    background-color: #f8f9fa;
                    border: 1px solid #dee2e6;
                    border-radius: 5px;
                    margin: 5px;
                    padding: 5px;
                }
            """)
            
            frame_layout = QVBoxLayout(frame)
            
            lbl_orig = QLabel(f"<b>Original:</b> {original}")
            lbl_orig.setWordWrap(True)
            lbl_orig.setFont(QFont("Arial", 10))
            lbl_orig.setStyleSheet("color: #495057; border: none; background: transparent;")
            
            lbl_trad = QLabel(f"<b>Tradução:</b> <span style='color: #0d6efd;'>{traducao}</span>")
            lbl_trad.setWordWrap(True)
            lbl_trad.setFont(QFont("Arial", 12))
            lbl_trad.setStyleSheet("border: none; background: transparent;")
            
            frame_layout.addWidget(lbl_orig)
            frame_layout.addWidget(lbl_trad)
            
            self.scroll_layout.addWidget(frame)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SidebarWindow()
    window.show()
    
    # Teste de dados falsos
    window.update_texts([
        {'original': 'File', 'traducao': 'Arquivo'},
        {'original': 'Settings', 'traducao': 'Configurações'}
    ])
    
    sys.exit(app.exec())
