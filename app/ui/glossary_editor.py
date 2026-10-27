from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QAbstractItemView
)
from PyQt6.QtCore import Qt

from core.glossary import glossary_path, read_terms, write_terms
from core.languages import language
from core.logger_config import get_logger
from ui.i18n import tr

logger = get_logger("GlossaryEditor")


class GlossaryEditor(QDialog):
    """Editor of the terms (original → translation) of one glossary file, for the current language pair."""

    def __init__(self, filename, source, target, parent=None):
        super().__init__(parent)
        self.path = glossary_path(filename)
        self.source, self.target = source, target
        self._saved = False

        self.setWindowTitle(tr("Glossary"))
        self.resize(560, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        pair = f"{tr(language(source).label)} → {tr(language(target).label)}"
        title = QLabel(tr("{file} · {pair}", file=filename or "glossary.json", pair=pair))
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        root.addWidget(title)
        hint = QLabel(tr("Fixed translations for names and terms: the AI must use exactly these. "
                         "Changes apply to the next line, even with the translation running."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([tr("Original"), tr("Translation")])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(False)
        root.addWidget(self.table, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        btn_add = QPushButton(tr("Add term"))
        btn_add.clicked.connect(lambda: self._add_row("", "", True, edit=True))
        btn_remove = QPushButton(tr("Remove"))
        btn_remove.clicked.connect(self._remove_selected)
        row.addWidget(btn_add)
        row.addWidget(btn_remove)
        row.addStretch()
        btn_cancel = QPushButton(tr("Cancel"))
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton(tr("Save"))
        btn_save.setProperty("variant", "primary")
        btn_save.clicked.connect(self._save)
        row.addWidget(btn_cancel)
        row.addWidget(btn_save)
        root.addLayout(row)

        self._load()

    def _add_row(self, original, translation, in_pair, edit=False):
        r = self.table.rowCount()
        self.table.insertRow(r)
        first = QTableWidgetItem(original)
        first.setData(Qt.ItemDataRole.UserRole, in_pair)  # whether the term lives in the language pair's section
        self.table.setItem(r, 0, first)
        self.table.setItem(r, 1, QTableWidgetItem(translation))
        if edit:
            self.table.setCurrentCell(r, 0)
            self.table.editItem(first)

    def _load(self):
        try:
            rows = read_terms(self.path, self.source, self.target)
        except Exception as e:
            logger.warning(f"Could not read the glossary {self.path}: {e}")
            QMessageBox.warning(self, tr("Glossary"), tr("Could not read the file:\n{e}", e=e))
            rows = []
        for original, translation, in_pair in rows:
            self._add_row(original, translation, in_pair)

    def _remove_selected(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def _save(self):
        rows = []
        for r in range(self.table.rowCount()):
            original = (self.table.item(r, 0).text() if self.table.item(r, 0) else "").strip()
            translation = (self.table.item(r, 1).text() if self.table.item(r, 1) else "").strip()
            if not original and not translation:
                continue
            if not original or not translation:
                self.table.setCurrentCell(r, 0 if not original else 1)
                QMessageBox.information(self, tr("Glossary"), tr("Fill in both the original and the translation, or remove the line."))
                return
            rows.append((original, translation, bool(self.table.item(r, 0).data(Qt.ItemDataRole.UserRole))))
        try:
            write_terms(self.path, self.source, self.target, rows)
        except OSError as e:
            logger.error(f"Failed to save the glossary: {e}")
            QMessageBox.critical(self, tr("Error"), tr("Could not save the file:\n{e}", e=e))
            return
        self.accept()

