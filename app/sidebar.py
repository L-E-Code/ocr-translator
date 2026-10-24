from difflib import SequenceMatcher
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt, pyqtSignal

import ui_theme
from ui_theme import DialogueCard, StatusPill, icon, icon_button, PLACEHOLDER
from history_window import HistoryWindow
from i18n import tr


class SidebarWindow(QWidget):
    """
    Reading side panel: shows the current line (highlighted translation + original)
    and feeds the history.
    """
    pause_toggled = pyqtSignal(bool)  # True = Paused, False = Running
    reload_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.is_paused = False

        # History in a separate window
        self.history_window = HistoryWindow()

        # Line tracking for deduplication in the history
        self.confirmed = {}  # region -> (last confirmed line, speaker)

        # One line per capture region (the single region uses the None key)
        self.cards = {}
        self.last_region_in_history = None
        self.hints = {}

        self.initUI()

    def initUI(self):
        self.setObjectName("root")
        self.setWindowTitle(tr("OCR Translator — Reading Panel"))
        self.resize(440, 560)
        self.setMinimumSize(340, 300)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(14)

        # Top bar: status + tools
        bar = QHBoxLayout()
        bar.setSpacing(2)
        self.status = StatusPill(tr("Monitoring"), "running")
        bar.addWidget(self.status)
        bar.addStretch()

        self.btn_reload = icon_button("refresh", tr("Retranslate: re-reads the screen now and produces a new translation"))
        self.btn_reload.clicked.connect(self.trigger_reload)
        self.btn_history = icon_button("history", tr("Open history"))
        self.btn_history.clicked.connect(self.toggle_history)
        self.btn_pause = icon_button("pause", tr("Pause reading"))
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_clear = icon_button("trash", tr("Clear the current line"))
        self.btn_clear.clicked.connect(self.clear_current_view)
        self.btn_pin = icon_button("pin", tr("Keep always on top"), checkable=True)
        self.btn_pin.setChecked(True)
        self.btn_pin.toggled.connect(self.set_always_on_top)
        for b in (self.btn_reload, self.btn_history, self.btn_pause, self.btn_clear, self.btn_pin):
            bar.addWidget(b)
        root.addLayout(bar)

        # Translation engine and latency of the last cycle
        self.lbl_info = QLabel("")
        self.lbl_info.setObjectName("hint")
        self.lbl_info.setVisible(False)
        root.addWidget(self.lbl_info)

        # Warning when the capture cannot read the screen (followed game window closed or minimized)
        self.lbl_capture = QLabel("")
        self.lbl_capture.setObjectName("hint")
        self.lbl_capture.setStyleSheet(f"color: {ui_theme.WARN};")
        self.lbl_capture.setWordWrap(True)
        self.lbl_capture.setVisible(False)
        root.addWidget(self.lbl_capture)

        # Current line area
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
        hint = QLabel(tr("Waiting for text on screen…"))
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(glyph)
        empty_layout.addWidget(hint)
        self.content.addWidget(self.empty)

    # ------------------------------------------------------------------
    def set_always_on_top(self, on):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.show()  # changing flags hides the window

    def set_shortcut_hints(self, hints):
        """Shows the configured global hotkeys in the button tooltips ({'pause': 'Ctrl+Alt+P', ...})."""
        self.hints = {k: v for k, v in hints.items() if v}
        self.btn_reload.setToolTip(self._with_hint(tr("Retranslate: re-reads the screen now and produces a new translation"), "reload"))
        self.btn_history.setToolTip(self._with_hint(tr("Open history"), "history"))
        self.btn_clear.setToolTip(self._with_hint(tr("Clear the current line"), "clear"))
        self._update_pause_tooltip()

    def _with_hint(self, text, action):
        key = self.hints.get(action)
        return f"{text} ({key})" if key else text

    def _update_pause_tooltip(self):
        text = tr("Resume reading") if self.is_paused else tr("Pause reading")
        self.btn_pause.setToolTip(self._with_hint(text, "pause"))

    def trigger_reload(self):
        """Asks the worker to re-read the screen immediately and translate again."""
        self.status.set_state(tr("Reading the screen…"), "busy")
        self.reload_requested.emit()

    def toggle_history(self):
        """Opens the history window or brings it to the front."""
        self.history_window.show()
        self.history_window.raise_()
        self.history_window.activateWindow()

    open_history = toggle_history

    def toggle_pause(self):
        self.set_paused(not self.is_paused)
        self.pause_toggled.emit(self.is_paused)

    def set_paused(self, paused):
        """Updates the pause state and visuals without notifying the launcher (also used by whoever paused from outside)."""
        self.is_paused = paused
        if self.is_paused:
            self.status.set_state(tr("Paused"), "paused")
            self.btn_pause.setIcon(icon("play", ui_theme.MUTED, 18))
        else:
            self.status.set_state(tr("Monitoring"), "running")
            self.btn_pause.setIcon(icon("pause", ui_theme.MUTED, 18))
        self._update_pause_tooltip()

    def clear_current_view(self):
        """Clears the lines shown in the panel."""
        for card in self.cards.values():
            card.setParent(None)
            card.deleteLater()
        self.cards.clear()
        self.empty.setVisible(True)

    def clear_history(self):
        """Compatibility alias to clear the current view."""
        self.clear_current_view()

    def set_capture_available(self, available, title=""):
        """Warns in the panel while the followed game window cannot be captured; goes back to normal when it returns."""
        self.lbl_capture.setVisible(not available)
        if available:
            self.set_paused(self.is_paused)  # puts the status pill back
        else:
            self.lbl_capture.setText(tr("Game window “{title}” not found or minimized. Showing the last line.", title=title))
            self.status.set_state(tr("Game window not found"), "paused")

    def update_info(self, info):
        """Shows which engine translated and how long it took; warns when the AI fell back to the backup engine."""
        engine, ms = info.get('engine', ''), info.get('ms', 0)
        if engine == 'cache':
            text, warn = tr("From cache · instant"), False
        elif info.get('limited'):
            text, warn = tr("Groq limit reached · using {engine} · {ms} ms", engine=engine, ms=f"{ms:.0f}"), True
        elif engine == 'failed':
            text, warn = tr("Translation unavailable: no connection or services are down"), True
        elif info.get('fallback'):
            text, warn = tr("Backup engine: {engine} · {ms} ms", engine=engine, ms=f"{ms:.0f}"), True
        else:
            text, warn = f"{engine} · {ms:.0f} ms", False
        self.lbl_info.setText(text)
        self.lbl_info.setStyleSheet(f"color: {ui_theme.WARN};" if warn else "")
        self.lbl_info.setVisible(True)

    # ------------------------------------------------------------------
    def update_texts(self, new_texts):
        """
        Receives the list of texts (preliminary or final) of a capture region and:
        1. Updates the region's card showing only its current line.
        2. Records and updates the matching line in the History.
        """
        if self.is_paused or not new_texts:
            return

        region = new_texts[0].get('region')

        speakers = [item['original'].strip() for item in new_texts if item.get('is_name')]
        speaker_name = speakers[0] if speakers else ""

        dialogue_items = [item for item in new_texts if not item.get('is_name')]

        # If all items were just names (rare), treats them as dialogue
        if not dialogue_items and speakers:
            dialogue_items = [item for item in new_texts]
            speaker_name = ""

        if not dialogue_items:
            return

        combined_orig = " ".join(item['original'].strip() for item in dialogue_items if item.get('original'))
        combined_trans = " ".join(item['translation'].strip() for item in dialogue_items if item.get('translation'))

        if not combined_orig and not combined_trans:
            return

        is_preliminary = PLACEHOLDER in combined_trans

        self.status.set_state(tr("Translating…") if is_preliminary else tr("Monitoring"),
                              "loading" if is_preliminary else "running")

        # Updates the card in place (no recreation, avoids flicker)
        card = self.cards.get(region)
        if card is None:
            card = DialogueCard(speaker_name, combined_orig, combined_trans, tag=(region or "TEXT").upper())
            self.cards[region] = card
            self.content.addWidget(card)
            self.empty.setVisible(False)
        else:
            card.set_content(speaker_name, combined_orig, combined_trans)

        # Feeds the history only with finished translations
        if not is_preliminary:
            last_original, last_speaker = self.confirmed.get(region, ("", ""))
            similarity = 0.0
            if last_original:
                similarity = SequenceMatcher(None, combined_orig, last_original).ratio()

            # Continuation/update of the same line (similarity >= 70%), as long as the last
            # history entry still belongs to this region
            if similarity >= 0.70 and self.last_region_in_history == region:
                self.history_window.update_last_entry(
                    speaker=speaker_name or last_speaker,
                    original=combined_orig,
                    translation=combined_trans
                )
            else:
                self.history_window.add_entry(
                    speaker=speaker_name,
                    original=combined_orig,
                    translation=combined_trans
                )

            self.confirmed[region] = (combined_orig, speaker_name)
            self.last_region_in_history = region

    def closeEvent(self, event):
        """Also closes the history window when the panel is closed."""
        self.history_window.close()
        super().closeEvent(event)
