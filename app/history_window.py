import time
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QLineEdit,
    QApplication, QFileDialog
)
from PyQt6.QtCore import Qt

import ui_theme
from ui_theme import DialogueCard, icon_button
from i18n import tr


class HistoryCardWidget(DialogueCard):
    """Card for one history line (speaker, time, translation and original)."""
    def __init__(self, speaker, original, translation, timestamp):
        super().__init__(speaker, original, translation, timestamp=timestamp, compact=True)

    def update_content(self, speaker, original, translation):
        self.set_content(speaker, original, translation)


class HistoryWindow(QWidget):
    """
    Window dedicated to the session's translation history, with search,
    text export and smart auto-scrolling.
    """
    def __init__(self):
        super().__init__()
        self.cards = []
        self.initUI()

    def initUI(self):
        self.setObjectName("root")
        self.setWindowTitle(tr("OCR Translator — History"))
        self.resize(500, 700)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Window)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        # Header
        header = QHBoxLayout()
        header.setSpacing(4)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        self.lbl_title = QLabel(tr("History"))
        self.lbl_title.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.lbl_count = QLabel(tr("No lines yet"))
        self.lbl_count.setObjectName("muted")
        title_box.addWidget(self.lbl_title)
        title_box.addWidget(self.lbl_count)
        header.addLayout(title_box)
        header.addStretch()

        self.btn_export = icon_button("download", tr("Export history (.txt)"))
        self.btn_export.clicked.connect(self.export_history)
        self.btn_copy_all = icon_button("copy", tr("Copy all translations"))
        self.btn_copy_all.clicked.connect(self.copy_all)
        self.btn_clear = icon_button("trash", tr("Clear history"))
        self.btn_clear.clicked.connect(self.clear_history)
        for b in (self.btn_export, self.btn_copy_all, self.btn_clear):
            header.addWidget(b)
        root.addLayout(header)

        # Search
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search the history…"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(ui_theme.icon("search", ui_theme.FAINT, 16), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self.apply_filter)
        root.addWidget(self.search)

        # List
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 4, 0)
        self.scroll_layout.setSpacing(10)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.scroll_content)

        self.lbl_empty = QLabel(tr("Translated lines will appear here."))
        self.lbl_empty.setObjectName("hint")
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_layout.addWidget(self.lbl_empty)

        root.addWidget(self.scroll, 1)
        self.update_count_label()

    def retranslate(self):
        """The interface language changed: updates the window and its cards."""
        self.setWindowTitle(tr("OCR Translator — History"))
        self.lbl_title.setText(tr("History"))
        self.btn_export.setToolTip(tr("Export history (.txt)"))
        self.btn_copy_all.setToolTip(tr("Copy all translations"))
        self.btn_clear.setToolTip(tr("Clear history"))
        self.search.setPlaceholderText(tr("Search the history…"))
        self.lbl_empty.setText(tr("Translated lines will appear here."))
        for card in self.cards:
            card.retranslate()
        self.apply_filter()

    def add_entry(self, speaker, original, translation, timestamp=None):
        if not original and not translation:
            return

        if not timestamp:
            timestamp = time.strftime("%H:%M:%S")

        # Only scrolls on its own if the user was already near the bottom
        scrollbar = self.scroll.verticalScrollBar()
        was_at_bottom = scrollbar.value() >= (scrollbar.maximum() - 40)

        card = HistoryCardWidget(speaker, original, translation, timestamp)
        self.cards.append(card)
        self.scroll_layout.addWidget(card)
        card.setVisible(self._matches_filter(card))

        self.update_count_label()

        if was_at_bottom or len(self.cards) == 1:
            QApplication.processEvents()
            scrollbar.setValue(scrollbar.maximum())

    def update_last_entry(self, speaker, original, translation):
        if not self.cards:
            self.add_entry(speaker, original, translation)
            return
        last_card = self.cards[-1]
        last_card.update_content(speaker, original, translation)
        last_card.setVisible(self._matches_filter(last_card))

    def clear_history(self):
        for card in self.cards:
            card.setParent(None)
            card.deleteLater()
        self.cards.clear()
        self.update_count_label()

    def _matches_filter(self, card):
        needle = self.search.text().strip()
        return not needle or card.matches(needle)

    def apply_filter(self):
        shown = 0
        for card in self.cards:
            visible = self._matches_filter(card)
            card.setVisible(visible)
            shown += visible
        self.update_count_label(shown)

    def update_count_label(self, shown=None):
        count = len(self.cards)
        has_filter = bool(self.search.text().strip()) if hasattr(self, "search") else False
        if count == 0:
            self.lbl_count.setText(tr("No lines yet"))
        elif has_filter and shown is not None:
            self.lbl_count.setText(tr("{shown} of {count} lines", shown=shown, count=count))
        else:
            self.lbl_count.setText(tr("1 line") if count == 1 else tr("{n} lines", n=count))
        self.lbl_empty.setVisible(count == 0)
        for b in (self.btn_export, self.btn_copy_all, self.btn_clear):
            b.setEnabled(count > 0)

    def _as_text(self):
        blocks = []
        for c in self.cards:
            head = f"[{c.timestamp}]" + (f" {c.speaker}" if c.speaker else "")
            blocks.append(f"{head}\n{c.original}\n{c.translation}")
        return "\n\n".join(blocks)

    def copy_all(self):
        QApplication.clipboard().setText("\n\n".join(c.translation for c in self.cards))

    def export_history(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Export history"), f"history_{time.strftime('%Y-%m-%d_%H-%M')}.txt", tr("Text (*.txt)")
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._as_text())
