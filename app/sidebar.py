from difflib import SequenceMatcher
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt, pyqtSignal

import ui_theme
from ui_theme import DialogueCard, StatusPill, icon, icon_button, PLACEHOLDER
from history_window import HistoryWindow


class SidebarWindow(QWidget):
    """
    Painel lateral de leitura: mostra a fala atual (tradução em destaque + original)
    e alimenta o histórico.
    """
    pause_toggled = pyqtSignal(bool)  # True = Pausado, False = Rodando
    reload_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.is_paused = False

        # Histórico em janela separada
        self.history_window = HistoryWindow()

        # Rastreamento de falas para deduplicação no histórico
        self.last_confirmed_original = ""
        self.last_confirmed_speaker = ""

        self.current_card = None

        self.initUI()

    def initUI(self):
        self.setObjectName("root")
        self.setWindowTitle("OCR Translator — Painel de Leitura")
        self.resize(440, 560)
        self.setMinimumSize(340, 300)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(14)

        # Barra superior: status + ferramentas
        bar = QHBoxLayout()
        bar.setSpacing(2)
        self.status = StatusPill("Monitorando", "running")
        bar.addWidget(self.status)
        bar.addStretch()

        self.btn_reload = icon_button("refresh", "Retraduzir: relê a tela agora e gera nova tradução")
        self.btn_reload.clicked.connect(self.trigger_reload)
        self.btn_history = icon_button("history", "Abrir histórico")
        self.btn_history.clicked.connect(self.toggle_history)
        self.btn_pause = icon_button("pause", "Pausar a leitura")
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_clear = icon_button("trash", "Limpar a fala atual")
        self.btn_clear.clicked.connect(self.clear_current_view)
        self.btn_pin = icon_button("pin", "Manter sempre no topo", checkable=True)
        self.btn_pin.setChecked(True)
        self.btn_pin.toggled.connect(self.set_always_on_top)
        for b in (self.btn_reload, self.btn_history, self.btn_pause, self.btn_clear, self.btn_pin):
            bar.addWidget(b)
        root.addLayout(bar)

        # Área da fala atual
        self.content = QVBoxLayout()
        self.content.setSpacing(0)
        self.content.setAlignment(Qt.AlignmentFlag.AlignTop)
        root.addLayout(self.content, 1)

        self.empty = QWidget()
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(10)
        glyph = QLabel("訳")
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glyph.setStyleSheet(f"font-size: 44px; font-weight: 700; color: {ui_theme.BORDER_HI};")
        hint = QLabel("Aguardando texto na tela…")
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(glyph)
        empty_layout.addWidget(hint)
        self.content.addWidget(self.empty)

    # ------------------------------------------------------------------
    def set_always_on_top(self, on):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.show()  # trocar flags esconde a janela

    def trigger_reload(self):
        """Solicita ao worker a releitura imediata da tela e nova tradução."""
        self.status.set_state("Lendo a tela…", "busy")
        self.reload_requested.emit()

    def toggle_history(self):
        """Abre ou traz para frente a janela de histórico."""
        self.history_window.show()
        self.history_window.raise_()
        self.history_window.activateWindow()

    open_history = toggle_history

    def toggle_pause(self):
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.status.set_state("Pausado", "paused")
            self.btn_pause.setIcon(icon("play", ui_theme.MUTED, 18))
            self.btn_pause.setToolTip("Retomar a leitura")
        else:
            self.status.set_state("Monitorando", "running")
            self.btn_pause.setIcon(icon("pause", ui_theme.MUTED, 18))
            self.btn_pause.setToolTip("Pausar a leitura")
        self.pause_toggled.emit(self.is_paused)

    def clear_current_view(self):
        """Limpa a fala exibida no painel."""
        if self.current_card is not None:
            self.current_card.setParent(None)
            self.current_card.deleteLater()
            self.current_card = None
        self.empty.setVisible(True)

    def clear_history(self):
        """Compatibilidade para limpar a visão atual."""
        self.clear_current_view()

    # ------------------------------------------------------------------
    def update_texts(self, new_texts):
        """
        Recebe a lista de textos (preliminares ou finais) e:
        1. Atualiza o painel mostrando apenas a fala atual.
        2. Registra e atualiza a fala correspondente no Histórico.
        """
        if self.is_paused or not new_texts:
            return

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

        is_preliminary = PLACEHOLDER in combined_trad

        self.status.set_state("Traduzindo…" if is_preliminary else "Monitorando",
                              "loading" if is_preliminary else "running")

        # Atualiza o cartão no lugar (sem recriar, evita flicker)
        if self.current_card is None:
            self.current_card = DialogueCard(speaker_name, combined_orig, combined_trad)
            self.content.addWidget(self.current_card)
            self.empty.setVisible(False)
        else:
            self.current_card.set_content(speaker_name, combined_orig, combined_trad)

        # Alimenta o histórico apenas com traduções concluídas
        if not is_preliminary:
            similarity = 0.0
            if self.last_confirmed_original:
                similarity = SequenceMatcher(None, combined_orig, self.last_confirmed_original).ratio()

            # Continuação/atualização da mesma fala (similaridade >= 70%)
            if similarity >= 0.70:
                self.history_window.update_last_entry(
                    speaker=speaker_name or self.last_confirmed_speaker,
                    original=combined_orig,
                    traducao=combined_trad
                )
            else:
                self.history_window.add_entry(
                    speaker=speaker_name,
                    original=combined_orig,
                    traducao=combined_trad
                )

            self.last_confirmed_original = combined_orig
            self.last_confirmed_speaker = speaker_name

    def closeEvent(self, event):
        """Fecha também a janela de histórico ao fechar o painel."""
        self.history_window.close()
        super().closeEvent(event)
