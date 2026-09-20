import sys
import time
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QScrollArea, QFrame, QPushButton, QApplication
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

class HistoryCardWidget(QFrame):
    """
    Card visual para uma fala no histórico com distinção de locutor,
    timestamp, texto original e tradução.
    """
    def __init__(self, speaker, original, traducao, timestamp):
        super().__init__()
        self.speaker = speaker
        self.original = original
        self.traducao = traducao
        self.timestamp = timestamp
        
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                padding: 4px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        
        # 1. Barra superior do card (Locutor e Horário)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        if self.speaker:
            lbl_speaker = QLabel(f"👤 {self.speaker}")
            lbl_speaker.setFont(QFont("Arial", 10, QFont.Weight.Bold))
            lbl_speaker.setStyleSheet("""
                background-color: #fef3c7;
                color: #b45309;
                border: 1px solid #fde68a;
                border-radius: 4px;
                padding: 2px 8px;
            """)
            header_layout.addWidget(lbl_speaker)
        else:
            lbl_speaker = QLabel("💬 Texto")
            lbl_speaker.setFont(QFont("Arial", 9, QFont.Weight.Bold))
            lbl_speaker.setStyleSheet("color: #64748b; background: transparent; border: none;")
            header_layout.addWidget(lbl_speaker)
            
        header_layout.addStretch()
        
        lbl_time = QLabel(self.timestamp)
        lbl_time.setFont(QFont("Arial", 9))
        lbl_time.setStyleSheet("color: #94a3b8; background: transparent; border: none;")
        header_layout.addWidget(lbl_time)
        
        layout.addLayout(header_layout)
        
        # 2. Texto Original
        self.lbl_orig = QLabel(self.original)
        self.lbl_orig.setWordWrap(True)
        self.lbl_orig.setFont(QFont("Arial", 10))
        self.lbl_orig.setStyleSheet("color: #475569; background: transparent; border: none; margin-top: 2px;")
        layout.addWidget(self.lbl_orig)
        
        # 3. Texto Traduzido
        self.lbl_trad = QLabel(self.traducao)
        self.lbl_trad.setWordWrap(True)
        self.lbl_trad.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.lbl_trad.setStyleSheet("color: #0284c7; background: transparent; border: none; margin-top: 1px;")
        layout.addWidget(self.lbl_trad)

    def update_content(self, speaker, original, traducao):
        self.speaker = speaker
        self.original = original
        self.traducao = traducao
        self.lbl_orig.setText(original)
        self.lbl_trad.setText(traducao)


class HistoryWindow(QWidget):
    """
    Janela dedicada para exibição do histórico de traduções da sessão.
    """
    def __init__(self):
        super().__init__()
        self.cards = []
        self.initUI()
        
    def initUI(self):
        self.setWindowTitle("OCR Translator - Histórico de Traduções")
        self.resize(520, 680)

        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Window)
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.main_layout.setSpacing(10)
        
        # 1. Barra de ferramentas superior
        self.toolbar = QHBoxLayout()
        
        self.lbl_count = QLabel("📜 Histórico (0 falas)")
        self.lbl_count.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self.lbl_count.setStyleSheet("color: #1e293b;")
        
        self.btn_clear = QPushButton("🗑 Limpar")
        self.btn_clear.setFont(QFont("Arial", 9))
        self.btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #f8fafc;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 4px 12px;
                color: #334155;
            }
            QPushButton:hover {
                background-color: #fee2e2;
                border-color: #fca5a5;
                color: #dc2626;
            }
        """)
        self.btn_clear.clicked.connect(self.clear_history)
        
        self.toolbar.addWidget(self.lbl_count)
        self.toolbar.addStretch()
        self.toolbar.addWidget(self.btn_clear)
        
        self.main_layout.addLayout(self.toolbar)
        
        # 2. Área rolável de falas
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("""
            QScrollArea {
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                background-color: #f8fafc;
            }
        """)
        
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_layout.setSpacing(8)
        self.scroll.setWidget(self.scroll_content)
        
        self.main_layout.addWidget(self.scroll)

    def add_entry(self, speaker, original, traducao, timestamp=None):
        if not original and not traducao:
            return
            
        if not timestamp:
            timestamp = time.strftime("%H:%M:%S")
            
        # Verifica se o usuário está perto do final para auto-scroll inteligente
        scrollbar = self.scroll.verticalScrollBar()
        was_at_bottom = scrollbar.value() >= (scrollbar.maximum() - 40)
        
        card = HistoryCardWidget(speaker, original, traducao, timestamp)
        self.cards.append(card)
        self.scroll_layout.addWidget(card)
        
        self.update_count_label()
        
        if was_at_bottom or len(self.cards) == 1:
            # Processa eventos pendentes para recalcular altura e rolar
            QApplication.processEvents()
            scrollbar.setValue(scrollbar.maximum())

    def update_last_entry(self, speaker, original, traducao):
        if not self.cards:
            self.add_entry(speaker, original, traducao)
            return
            
        last_card = self.cards[-1]
        last_card.update_content(speaker, original, traducao)

    def clear_history(self):
        for card in self.cards:
            card.setParent(None)
            card.deleteLater()
        self.cards.clear()
        self.update_count_label()

    def update_count_label(self):
        count = len(self.cards)
        fala_str = "fala" if count == 1 else "falas"
        self.lbl_count.setText(f"📜 Histórico ({count} {fala_str})")

