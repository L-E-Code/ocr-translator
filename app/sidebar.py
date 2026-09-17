import sys
import time
from difflib import SequenceMatcher
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QScrollArea, QFrame, QPushButton
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from history_window import HistoryWindow

class SidebarWindow(QWidget):
    pause_toggled = pyqtSignal(bool) # True = Pausado, False = Rodando
    reload_requested = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.is_paused = False
        
        # Histórico em janela separada
        self.history_window = HistoryWindow()
        
        # Rastreamento de falas para deduplicação no histórico
        self.last_confirmed_original = ""
        self.last_confirmed_speaker = ""
        
        self.initUI()
        
    def initUI(self):
        self.setWindowTitle("OCR Translator - Painel de Leitura")
        self.resize(420, 620)
        
        # Mantém a janela sempre no topo
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
        
        # Botão Retraduzir
        self.btn_reload = QPushButton("🔄 Retraduzir")
        self.btn_reload.setFont(QFont("Arial", 9))
        self.btn_reload.setToolTip("Re-lê a tela agora e gera uma nova tradução com IA")
        self.btn_reload.setStyleSheet("""
            QPushButton {
                background-color: #f0f9ff;
                border: 1px solid #7dd3fc;
                border-radius: 4px;
                padding: 4px 10px;
                color: #0369a1;
            }
            QPushButton:hover {
                background-color: #e0f2fe;
                border-color: #38bdf8;
            }
        """)
        self.btn_reload.clicked.connect(self.trigger_reload)
        
        # Botão Histórico
        self.btn_history = QPushButton("📜 Histórico")
        self.btn_history.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        self.btn_history.setStyleSheet("""
            QPushButton {
                background-color: #f0fdf4;
                border: 1px solid #86efac;
                border-radius: 4px;
                padding: 4px 10px;
                color: #166534;
            }
            QPushButton:hover {
                background-color: #dcfce7;
                border-color: #4ade80;
            }
        """)
        self.btn_history.clicked.connect(self.toggle_history)
        
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
        self.btn_clear.clicked.connect(self.clear_current_view)
        
        self.toolbar.addWidget(self.lbl_status)
        self.toolbar.addStretch()
        self.toolbar.addWidget(self.btn_reload)
        self.toolbar.addWidget(self.btn_history)
        self.toolbar.addWidget(self.btn_pause)
        self.toolbar.addWidget(self.btn_clear)
        
        self.main_layout.addLayout(self.toolbar)
        
        # 2. Área rolável de falas (exibe o texto atual)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: 1px solid #e5e7eb; border-radius: 6px; background-color: #ffffff; }")
        
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_layout.setSpacing(6)
        self.scroll.setWidget(self.scroll_content)
        
        self.main_layout.addWidget(self.scroll)
        
    def trigger_reload(self):
        """Solicita ao worker a releitura imediata da tela e nova tradução."""
        self.lbl_status.setText("🔄 Lendo tela...")
        self.lbl_status.setStyleSheet("color: #0284c7;")
        self.reload_requested.emit()

    def toggle_history(self):
        """Abre ou traz para frente a janela de histórico."""
        if self.history_window.isVisible():
            self.history_window.activateWindow()
            self.history_window.raise_()
        else:
            self.history_window.show()
            self.history_window.raise_()

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

    def clear_current_view(self):
        """Limpa a exibição da tela atual da sidebar."""
        for i in reversed(range(self.scroll_layout.count())): 
            widget = self.scroll_layout.itemAt(i).widget()
            if widget is not None:
                widget.setParent(None)

    def clear_history(self):
        """Compatibilidade para limpar a visão atual."""
        self.clear_current_view()

    def update_texts(self, new_texts):
        """
        Recebe a lista de textos (preliminares ou finais) e:
        1. Atualiza a sidebar mostrando apenas o texto atual.
        2. Registra e atualiza a fala correspondente no Histórico.
        """
        if self.is_paused or not new_texts:
            return

        # 1. Separa locutor de diálogo
        speakers = [item['original'].strip() for item in new_texts if item.get('is_name')]
        speaker_name = speakers[0] if speakers else ""
        
        dialogue_items = [item for item in new_texts if not item.get('is_name')]
        
        # Se todos os itens fossem apenas nomes (raro), trata como diálogo
        if not dialogue_items and speakers:
            dialogue_items = [item for item in new_texts]
            speaker_name = ""

        if not dialogue_items:
            return

        combined_orig = " ".join(item['original'].strip() for item in dialogue_items if item.get('original'))
        combined_trad = " ".join(item['traducao'].strip() for item in dialogue_items if item.get('traducao'))
        
        if not combined_orig and not combined_trad:
            return

        is_preliminary = "[Traduzindo com IA...]" in combined_trad

        # Atualiza indicador de status se não estiver pausado
        if not self.is_paused:
            if is_preliminary:
                self.lbl_status.setText("● Traduzindo...")
                self.lbl_status.setStyleSheet("color: #0284c7;")
            else:
                self.lbl_status.setText("● Monitorando")
                self.lbl_status.setStyleSheet("color: #16a34a;")

        # 2. Renderiza na Sidebar
        self.clear_current_view()
        
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 8px;
                padding: 6px;
            }
        """)
        
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(10, 10, 10, 10)
        frame_layout.setSpacing(6)
        
        # Distinção de Locutor
        if speaker_name:
            lbl_speaker = QLabel(f"👤 {speaker_name}")
            lbl_speaker.setFont(QFont("Arial", 10, QFont.Weight.Bold))
            lbl_speaker.setStyleSheet("""
                background-color: #fef3c7;
                color: #b45309;
                border: 1px solid #fde68a;
                border-radius: 4px;
                padding: 3px 8px;
            """)
            frame_layout.addWidget(lbl_speaker)
        
        lbl_orig = QLabel(f"<b style='color: #111827;'>Original:</b> <span style='color: #374151;'>{combined_orig}</span>")
        lbl_orig.setWordWrap(True)
        lbl_orig.setFont(QFont("Arial", 11))
        lbl_orig.setStyleSheet("border: none; background: transparent;")
        
        color_trad = "#9ca3af" if is_preliminary else "#0284c7"
        lbl_trad = QLabel(f"<b style='color: #111827;'>Tradução:</b> <span style='color: {color_trad}; font-weight: bold;'>{combined_trad}</span>")
        lbl_trad.setWordWrap(True)
        lbl_trad.setFont(QFont("Arial", 13))
        lbl_trad.setStyleSheet("border: none; background: transparent;")
        
        frame_layout.addWidget(lbl_orig)
        frame_layout.addWidget(lbl_trad)
        
        self.scroll_layout.addWidget(frame)
        
        # 3. Alimenta o Histórico
        if not is_preliminary:
            similarity = 0.0
            if self.last_confirmed_original:
                similarity = SequenceMatcher(None, combined_orig, self.last_confirmed_original).ratio()

            # Se for continuação/atualização da mesma fala (similaridade >= 70%)
            if similarity >= 0.70:
                self.history_window.update_last_entry(
                    speaker=speaker_name or self.last_confirmed_speaker,
                    original=combined_orig,
                    traducao=combined_trad
                )
            else:
                # É uma fala nova!
                self.history_window.add_entry(
                    speaker=speaker_name,
                    original=combined_orig,
                    traducao=combined_trad
                )

            self.last_confirmed_original = combined_orig
            self.last_confirmed_speaker = speaker_name

    def closeEvent(self, event):
        """Fecha também a janela de histórico ao fechar a sidebar."""
        self.history_window.close()
        super().closeEvent(event)
