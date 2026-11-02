"""Window to manage the Groq keys: add, remove and choose the order in which they are used."""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem, QAbstractItemView,
    QInputDialog, QLineEdit, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal

from core import secrets_store
from ui.i18n import tr
from ui.ui_theme import set_variant


def prompt_new_key(parent):
    """
    Asks for a Groq key and saves it after the ones already saved. Returns True if one was saved. A text that does not
    look like a Groq key is only saved after the user confirms.
    """
    text, ok = QInputDialog.getText(
        parent, tr("Groq key"), tr("Paste your Groq API key (it is not shown or logged):"), QLineEdit.EchoMode.Password)
    text = text.strip()
    if not ok or not text:
        return False
    if not text.startswith("gsk_"):
        answer = QMessageBox.question(
            parent, tr("Groq key"), tr("This does not look like a Groq key (they start with “gsk_”). Save it anyway?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return False
    saved, error = secrets_store.add_groq_key(text)
    if not saved:
        QMessageBox.critical(parent, tr("Error"), tr("Could not save the key:\n{e}", e=tr(error)))
    return saved


class KeyManagerDialog(QDialog):
    """The saved keys, masked, in the order they are used (the first until it reaches its limit, then the next)."""
    changed = pyqtSignal()  # a key was added, removed or moved

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("root")
        self.setWindowTitle(tr("Groq keys"))
        self.resize(460, 420)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        hint = QLabel(tr("The first key is used until it reaches its limit; then the next one takes over, and the first "
                         "comes back when its wait is over. If every key is at its limit, the free translators are used."))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.list_keys = QListWidget()
        self.list_keys.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_keys.itemSelectionChanged.connect(self.refresh_buttons)
        root.addWidget(self.list_keys, 1)

        self.lbl_note = QLabel("")
        self.lbl_note.setObjectName("hint")
        self.lbl_note.setWordWrap(True)
        root.addWidget(self.lbl_note)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_add = QPushButton(tr("Add key…"))
        self.btn_add.clicked.connect(self.add_key)
        self.btn_remove = QPushButton(tr("Remove"))
        self.btn_remove.clicked.connect(self.remove_key)
        self.btn_up = QPushButton(tr("Move up"))
        self.btn_up.clicked.connect(lambda: self.move_key(-1))
        self.btn_down = QPushButton(tr("Move down"))
        self.btn_down.clicked.connect(lambda: self.move_key(+1))
        self.btn_close = QPushButton(tr("Close"))
        set_variant(self.btn_close, "primary")
        self.btn_close.clicked.connect(self.accept)
        for b in (self.btn_add, self.btn_remove, self.btn_up, self.btn_down):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.btn_close)
        root.addLayout(row)
        self.reload()

    # ------------------------------------------------------------------
    def stored_keys(self):
        return secrets_store.saved_groq_keys()

    def reload(self, select=None):
        keys = self.stored_keys()
        self.list_keys.clear()
        for number, key in enumerate(keys, start=1):
            item = QListWidgetItem(f"{number}.   {secrets_store.mask_key(key)}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.list_keys.addItem(item)
            if key == select:
                self.list_keys.setCurrentItem(item)
        if keys:
            self.lbl_note.setText(tr("{n} of {max} keys saved in the Windows Credential Manager.", n=len(keys), max=secrets_store.MAX_KEYS))
        elif secrets_store.groq_key_source() == secrets_store.SOURCE_ENV:
            self.lbl_note.setText(tr("The keys in use come from the .env file (plain text). Add them here to store them safely."))
        else:
            self.lbl_note.setText(tr("No key saved: the free translators are used (lower quality)."))
        self.refresh_buttons()

    def selected_key(self):
        item = self.list_keys.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None and item.isSelected() else None

    def refresh_buttons(self):
        key = self.selected_key()
        keys = self.stored_keys()
        index = keys.index(key) if key in keys else -1
        self.btn_add.setEnabled(len(keys) < secrets_store.MAX_KEYS)
        self.btn_remove.setEnabled(index >= 0)
        self.btn_up.setEnabled(index > 0)
        self.btn_down.setEnabled(0 <= index < len(keys) - 1)

    def add_key(self):
        if prompt_new_key(self):
            self.reload(select=self.stored_keys()[-1])
            self.changed.emit()

    def remove_key(self):
        key = self.selected_key()
        if key is None:
            return
        answer = QMessageBox.question(
            self, tr("Groq key"), tr("Remove {key} from the Windows Credential Manager?", key=secrets_store.mask_key(key)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes and secrets_store.remove_groq_key(key):
            self.reload()
            self.changed.emit()

    def move_key(self, step):
        key = self.selected_key()
        if key is not None and secrets_store.move_groq_key(key, step):
            self.reload(select=key)
            self.changed.emit()
