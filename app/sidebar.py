import sys
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QScrollArea, QFrame, QPushButton
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

class SidebarWindow(QWidget):
    pause_toggled = pyqtSignal(bool) # True = Pausado, False = Rodando
    
    def __init__(self):
        super().__init__()
        self.is_paused = False
        self.initUI()
        
    def initUI(self):
        self.setWindowTitle("OCR Translator - Painel de Leitura")
        self.resize(420, 620)
        
        # Mantem a janela sempre no topo
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
        
        # Layout principal
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(8)
        
        # 1. Barra de ferramentas superior
        self.toolbar = QHBoxLayout()
        
        # Indicador de Status
        self.lbl_status = QLabel("● Monitorando")
        self.lbl_status.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.lbl_status.setStyleSheet("color: #16a34a;") # Verde
        
        # Botão Pausar / Retomar
        self.btn_pause = QPushButton("❚❚ Pausar")
        self.btn_pause.setFont(QFont("Arial", 9))
        self.btn_pause.setStyleSheet("""
            QPushButton {
                background-color: #f3f4f6;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: #e5e7eb;
            }
        """)
        self.btn_pause.clicked.connect(self.toggle_pause)
        
        # Botão Limpar
        self.btn_clear = QPushButton("🗑 Limpar")
        self.btn_clear.setFont(QFont("Arial", 9))
        self.btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #f3f4f6;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: #fee2e2;
                border-color: #fca5a5;
                color: #dc2626;
            }
        """)
        self.btn_clear.clicked.connect(self.clear_history)
        
        self.toolbar.addWidget(self.lbl_status)
        self.toolbar.addStretch()
        self.toolbar.addWidget(self.btn_pause)
        self.toolbar.addWidget(self.btn_clear)
        
        self.main_layout.addLayout(self.toolbar)
        
        # 2. Área rolável de falas
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: 1px solid #e5e7eb; border-radius: 6px; background-color: #ffffff; }")
        
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_layout.setSpacing(6)
        self.scroll.setWidget(self.scroll_content)
        
        self.main_layout.addWidget(self.scroll)
        
    def toggle_pause(self):
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.lbl_status.setText("❚❚ Pausado")
            self.lbl_status.setStyleSheet("color: #ca8a04;") # Amarelo escuro
            self.btn_pause.setText("▶ Retomar")
        else:
            self.lbl_status.setText("● Monitorando")
            self.lbl_status.setStyleSheet("color: #16a34a;") # Verde
            self.btn_pause.setText("❚❚ Pausar")
            
        self.pause_toggled.emit(self.is_paused)

    def clear_history(self):
        for i in reversed(range(self.scroll_layout.count())): 
            widget = self.scroll_layout.itemAt(i).widget()
            if widget is not None:
                widget.setParent(None)

    def update_texts(self, new_texts):
        """
        Recebe a nova lista de textos traduzidos e atualiza o painel lateral.
        """
        if self.is_paused:
            return

        # Limpa conteúdo atual se houver novos textos válidos
        if new_texts:
            self.clear_history()
            
            for item in new_texts:
                original = item.get('original', '')
                traducao = item.get('traducao', '')
                
                if not original or not traducao:
                    continue
                    
                frame = QFrame()
                frame.setFrameShape(QFrame.Shape.StyledPanel)
                frame.setStyleSheet("""
                    QFrame {
                        background-color: #f8f9fa;
                        border: 1px solid #dee2e6;
                        border-radius: 6px;
                        padding: 6px;
                    }
                """)
                
                frame_layout = QVBoxLayout(frame)
                frame_layout.setContentsMargins(8, 8, 8, 8)
                frame_layout.setSpacing(4)
                
                lbl_orig = QLabel(f"<b style='color: #111827;'>Original:</b> <span style='color: #374151;'>{original}</span>")
                lbl_orig.setWordWrap(True)
                lbl_orig.setFont(QFont("Arial", 11))
                lbl_orig.setStyleSheet("border: none; background: transparent;")
                
                lbl_trad = QLabel(f"<b style='color: #111827;'>Tradução:</b> <span style='color: #0284c7; font-weight: bold;'>{traducao}</span>")
                lbl_trad.setWordWrap(True)
                lbl_trad.setFont(QFont("Arial", 13))
                lbl_trad.setStyleSheet("border: none; background: transparent;")
                
                frame_layout.addWidget(lbl_orig)
                frame_layout.addWidget(lbl_trad)
                
                self.scroll_layout.addWidget(frame)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SidebarWindow()
    window.show()
    
    window.update_texts([
        {'original': 'お待たせしました', 'traducao': 'Thank you for waiting'},
        {'original': '季節のミルフィーユ', 'traducao': 'Seasonal mille-feuille'}
    ])
    
    sys.exit(app.exec())
