"""Dialog to translate a series of files (images, PDFs, comic archives) and export the translations."""
import atexit
import os
import shutil
import tempfile
import time

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem, QCheckBox,
    QFileDialog, QProgressBar, QMessageBox, QAbstractItemView, QComboBox, QLineEdit, QApplication, QScrollArea, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut

from core import batch, config_manager, inputs
from core.logger_config import get_logger
from core.reading_modes import MODE_DIALOGUE, MODE_DOCUMENT
from ui import card_render
from ui.batch_preview import PreviewDialog
from ui.batch_worker import BatchWorker
from ui.region_picker import pick_region, region_text
from ui.i18n import tr
from ui.ui_theme import Card, icon, set_variant, TEXT, WARN, ON_ACCENT

logger = get_logger("Batch")

# A document with more pages than this makes the user confirm: every block of text is one translation request
LARGE_BATCH_PAGES = 30


def _status_text(status):
    return {
        "waiting": tr("waiting"), "reading": tr("reading"), batch.DONE: tr("done"),
        batch.PARTIAL: tr("partial"), batch.FAILED: tr("failed"), batch.CANCELLED: tr("cancelled"),
    }.get(status, status)


class ImageBatchWindow(QWidget):
    """
    Non-modal window: list of files, what to export, Start/Cancel. The engine comes from the main window through
    `engine_provider(on_ready, on_error)`, which reuses the one already loaded for the chosen languages.
    """
    busy_changed = pyqtSignal(bool)  # True from Start until the batch is over: the live translation must not start

    def __init__(self, engine_provider):
        super().__init__()
        self.engine_provider = engine_provider
        self.worker = None
        self.busy = False
        self.out_dir = None
        self.region = None  # [x, y, width, height] as fractions of the page
        self.expected = {}  # path -> pages that will be read, for the progress bar
        self.mode_touched = False  # until the user picks a mode, it follows the first file added
        self.run_files = []  # the files of the batch that is running (or ran last): all of the list, or the ones retried
        self.status = {}  # path -> last status of the file
        self.outputs = {}  # path -> the translated files written for it
        self.page_rows = {}  # path -> the report rows read from it
        self.clipboard_dir = None  # where pasted images are kept until the program closes
        self.out_dir_used = None
        self.last_dir = None  # the folder the file picker opened last
        self.setAcceptDrops(True)
        self.initUI()
        self.load_settings()

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------
    def initUI(self):
        self.setObjectName("root")
        self.setWindowTitle(tr("OCR Translator — Translate files"))
        self.resize(680, 760)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 24)
        root.setSpacing(12)

        # The options scroll (there are many of them); Start, Cancel and the progress stay in view at the bottom
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 6, 0)
        content_layout.setSpacing(12)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        banner = QLabel(tr("⚠ Experimental mode. Translating files is still being tested: results may be inaccurate and some files may fail."))
        banner.setWordWrap(True)
        policy = banner.sizePolicy()  # keeps height-for-width; Ignored stops the label from being wider than the scroll area
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        banner.setSizePolicy(policy)
        banner.setStyleSheet(f"color: {WARN}; border: 1px solid {WARN}; border-radius: 6px; padding: 8px 10px;")
        content_layout.addWidget(banner)

        files = Card(tr("Files"))
        self.list_files = QListWidget()
        self.list_files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_files.setMinimumHeight(180)
        self.list_files.itemDoubleClicked.connect(self.preview_selected)
        remove_key = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.list_files)
        remove_key.setContext(Qt.ShortcutContext.WidgetShortcut)
        remove_key.activated.connect(self.remove_selected)
        files.body.addWidget(self.list_files, 1)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_add = QPushButton(tr(" Add files"))
        self.btn_add.setIcon(icon("folder", TEXT, 16))
        self.btn_add.clicked.connect(self.add_files)
        self.btn_add_folder = QPushButton(tr("Add folder"))
        self.btn_add_folder.clicked.connect(self.add_folder)
        self.btn_remove = QPushButton(tr("Remove"))
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear = QPushButton(tr("Clear"))
        self.btn_clear.clicked.connect(self.clear_files)
        for b in (self.btn_add, self.btn_add_folder, self.btn_remove, self.btn_clear):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(b)
        files.body.addLayout(row)
        hint = QLabel(tr("Images (PNG, JPG, WebP, BMP, TIFF, GIF), PDF and CBZ. Drag files here or press Ctrl+V to paste an image. Double-click a finished file to compare."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        files.body.addWidget(hint)
        content_layout.addWidget(files, 1)

        self.docs = Card(tr("Documents"))
        pages_row = QHBoxLayout()
        pages_row.setSpacing(8)
        self.lbl_pages = QLabel(tr("PDF pages"))
        self.lbl_pages.setObjectName("muted")
        self.edit_pages = QLineEdit()
        self.edit_pages.setPlaceholderText(tr("All, or for example 1-5, 8, 12-"))
        self.edit_pages.setToolTip(tr("Applies to every PDF in the list"))
        pages_row.addWidget(self.lbl_pages)
        pages_row.addWidget(self.edit_pages, 1)
        self.docs.body.addLayout(pages_row)
        quality_row = QHBoxLayout()
        quality_row.setSpacing(8)
        self.lbl_quality = QLabel(tr("PDF quality"))
        self.lbl_quality.setObjectName("muted")
        self.combo_quality = QComboBox()
        for dpi, label in ((100, tr("Draft (100 dpi)")), (150, tr("Normal (150 dpi)")), (300, tr("High (300 dpi, slower)"))):
            self.combo_quality.addItem(label, dpi)
        self.combo_quality.currentIndexChanged.connect(self.save_settings)
        quality_row.addWidget(self.lbl_quality)
        quality_row.addWidget(self.combo_quality, 1)
        self.docs.body.addLayout(quality_row)
        self.chk_ocr = QCheckBox(tr("Always read with OCR"))
        self.chk_ocr.setToolTip(tr("Ignores the text inside the PDF. Use it when that text comes out garbled."))
        self.chk_ocr.toggled.connect(self.save_settings)
        self.docs.body.addWidget(self.chk_ocr)
        self.chk_png = QCheckBox(tr("Also a PNG of each page"))
        self.chk_png.toggled.connect(self.save_settings)
        self.docs.body.addWidget(self.chk_png)
        content_layout.addWidget(self.docs)

        area = Card(tr("Area to read"))
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        lbl_mode = QLabel(tr("Reading"))
        lbl_mode.setObjectName("muted")
        self.combo_mode = QComboBox()
        self.combo_mode.addItem(tr("Dialogue box (one text and its speaker)"), MODE_DIALOGUE)
        self.combo_mode.addItem(tr("Document (every block of text)"), MODE_DOCUMENT)
        self.combo_mode.setToolTip(tr("Dialogue keeps the main text of each image. Document translates every paragraph of the page, in reading order."))
        self.combo_mode.activated.connect(self.on_mode_picked)
        mode_row.addWidget(lbl_mode)
        mode_row.addWidget(self.combo_mode, 1)
        area.body.addLayout(mode_row)
        self.chk_region = QCheckBox(tr("Only the dialogue box"))
        self.chk_region.setToolTip(tr("For full screenshots: reads just the area you draw, the same on every file"))
        self.chk_region.toggled.connect(self.on_region_toggled)
        area.body.addWidget(self.chk_region)
        region_row = QHBoxLayout()
        region_row.setSpacing(8)
        self.lbl_region = QLabel("")
        self.lbl_region.setObjectName("hint")
        self.lbl_region.setWordWrap(True)
        region_row.addWidget(self.lbl_region, 1)
        self.btn_region = QPushButton(tr("Choose area…"))
        self.btn_region.clicked.connect(self.choose_region)
        region_row.addWidget(self.btn_region)
        area.body.addLayout(region_row)
        content_layout.addWidget(area)

        output = Card(tr("Output"))
        self.chk_images = QCheckBox(tr("Translated files (same format as the original)"))
        output.body.addWidget(self.chk_images)
        style_row = QHBoxLayout()
        style_row.setSpacing(8)
        self.lbl_style = QLabel(tr("Style"))
        self.lbl_style.setObjectName("muted")
        self.combo_style = QComboBox()
        self.combo_style.addItem(tr("Over the original (cards on images, rewritten text on documents)"), card_render.STYLE_CARD)
        self.combo_style.addItem(tr("Text strip below the image"), card_render.STYLE_STRIP)
        self.combo_style.currentIndexChanged.connect(self.save_settings)
        style_row.addWidget(self.lbl_style)
        style_row.addWidget(self.combo_style, 1)
        output.body.addLayout(style_row)
        self.chk_txt = QCheckBox(tr("Text file (translations.txt)"))
        self.chk_csv = QCheckBox(tr("Spreadsheet (translations.csv)"))
        self.chk_share = QCheckBox(tr("Use the previous lines as context (files in name order)"))
        self.chk_share.setToolTip(tr("Turn it off when the files are unrelated to each other"))
        for c in (self.chk_txt, self.chk_csv, self.chk_share):
            output.body.addWidget(c)
        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self.lbl_folder = QLabel("")
        self.lbl_folder.setObjectName("hint")
        self.lbl_folder.setWordWrap(True)
        folder_row.addWidget(self.lbl_folder, 1)
        self.btn_folder = QPushButton(tr("Change…"))
        self.btn_folder.clicked.connect(self.choose_folder)
        folder_row.addWidget(self.btn_folder)
        output.body.addLayout(folder_row)
        content_layout.addWidget(output)

        run = Card()
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        run.body.addWidget(self.progress)
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("muted")
        self.lbl_status.setWordWrap(True)
        run.body.addWidget(self.lbl_status)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.btn_start = QPushButton(tr("  Start"))
        self.btn_start.setIcon(icon("play", ON_ACCENT, 18))
        self.btn_start.setIconSize(QSize(18, 18))
        set_variant(self.btn_start, "primary")
        self.btn_start.clicked.connect(lambda *_: self.start())  # `clicked` passes a bool, not a list of files
        self.btn_cancel = QPushButton(tr("Cancel"))
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_open = QPushButton(tr("Open folder"))
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self.open_output_folder)
        for b in (self.btn_start, self.btn_cancel, self.btn_open):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            buttons.addWidget(b)
        run.body.addLayout(buttons)
        after = QHBoxLayout()
        after.setSpacing(8)
        self.btn_retry = QPushButton(tr("Retry failed"))
        self.btn_retry.setToolTip(tr("Translates again the files that failed, finished partly or were cancelled. What was already translated comes from the cache."))
        self.btn_retry.setEnabled(False)
        self.btn_retry.clicked.connect(self.retry_failed)
        self.btn_preview = QPushButton(tr("Compare…"))
        self.btn_preview.setToolTip(tr("The original and the translation of the selected file, side by side"))
        self.btn_preview.setEnabled(False)
        self.btn_preview.clicked.connect(self.preview_selected)
        for b in (self.btn_retry, self.btn_preview):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            after.addWidget(b)
        run.body.addLayout(after)
        self.list_files.itemSelectionChanged.connect(self.refresh_preview_button)
        root.addWidget(run)

        for c in (self.chk_images, self.chk_txt, self.chk_csv, self.chk_share):
            c.toggled.connect(self.save_settings)
        paste = QShortcut(QKeySequence(QKeySequence.StandardKey.Paste), self)
        paste.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)  # the window is a page of the launcher now
        paste.activated.connect(self.paste_from_clipboard)
        self.refresh_options()
        self.chk_images.toggled.connect(self.combo_style.setEnabled)
        self.chk_images.toggled.connect(self.lbl_style.setEnabled)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def load_settings(self):
        config = config_manager.load_config()
        self.chk_images.setChecked(config["batch_export_images"])
        self.combo_style.setCurrentIndex(max(0, self.combo_style.findData(config["batch_image_style"])))
        self.combo_style.setEnabled(self.chk_images.isChecked())
        self.lbl_style.setEnabled(self.chk_images.isChecked())
        self.combo_quality.setCurrentIndex(max(0, self.combo_quality.findData(config["batch_pdf_dpi"])))
        self.chk_png.setChecked(config["batch_also_png"])
        self.chk_ocr.setChecked(config["batch_always_ocr"])
        self.region = config["batch_region"]
        self.chk_region.blockSignals(True)
        self.chk_region.setChecked(config["batch_use_region"] and self.region is not None)
        self.chk_region.blockSignals(False)
        self.refresh_region_label()
        self.chk_txt.setChecked(config["batch_export_txt"])
        self.chk_csv.setChecked(config["batch_export_csv"])
        self.chk_share.setChecked(config["batch_share_context"])
        self.out_dir = config["batch_output_dir"]
        self.last_dir = config["batch_last_dir"]
        self.refresh_folder_label()

    def save_settings(self, *_):
        config_manager.save_config({
            "batch_last_dir": self.last_dir,
            "batch_pdf_dpi": self.combo_quality.currentData(),
            "batch_also_png": self.chk_png.isChecked(),
            "batch_always_ocr": self.chk_ocr.isChecked(),
            "batch_use_region": self.chk_region.isChecked(),
            "batch_region": self.region,
            "batch_export_images": self.chk_images.isChecked(),
            "batch_image_style": self.combo_style.currentData(),
            "batch_export_txt": self.chk_txt.isChecked(),
            "batch_export_csv": self.chk_csv.isChecked(),
            "batch_share_context": self.chk_share.isChecked(),
            "batch_output_dir": self.out_dir,
        })

    def refresh_folder_label(self):
        if self.out_dir:
            self.lbl_folder.setText(tr("Folder: {path}", path=self.out_dir))
        else:
            self.lbl_folder.setText(tr("Folder: a 'translated' folder next to the first file"))

    def refresh_region_label(self):
        self.lbl_region.setText(region_text(self.region) if self.chk_region.isChecked() else tr("whole page"))
        self.btn_region.setEnabled(self.chk_region.isChecked() and not self.busy)

    def on_region_toggled(self, checked):
        if checked and self.region is None and not self.choose_region():
            self.chk_region.setChecked(False)  # cancelled: back to the whole page
            return
        self.refresh_region_label()
        self.save_settings()

    def choose_region(self):
        """Draws the area on the first page of the list. Returns True if an area is now set."""
        files = self.paths()
        if not files:
            QMessageBox.information(self, tr("Translate files"), tr("Add at least one file."))
            return False
        try:
            page = next(inputs.iter_pages(files[0]))
        except Exception as e:
            QMessageBox.warning(self, tr("Translate files"), str(e))
            return False
        accepted, region = pick_region(self, page.image, self.region)
        if not accepted:
            return self.region is not None
        if region is None:  # "Whole page"
            self.region = None
            self.chk_region.setChecked(False)
            return False
        self.region = list(region)
        self.refresh_region_label()
        self.save_settings()
        return True

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Output folder"), self.out_dir or "")
        if folder:
            self.out_dir = folder
            self.refresh_folder_label()
            self.save_settings()

    # ------------------------------------------------------------------
    # File list
    # ------------------------------------------------------------------
    def paths(self):
        return [self.list_files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list_files.count())]

    def on_mode_picked(self, *_):
        self.mode_touched = True

    def follow_first_file(self):
        """Until the user chooses, a PDF or a comic archive as first file means document mode; images, dialogue."""
        files = self.paths()
        if self.mode_touched or not files:
            return
        document = inputs.is_pdf(files[0]) or inputs.is_archive(files[0])
        self.combo_mode.setCurrentIndex(self.combo_mode.findData(MODE_DOCUMENT if document else MODE_DIALOGUE))

    def add_paths(self, new_paths):
        """Adds supported files that are not in the list yet; the whole list stays in natural name order."""
        known = set(self.paths())
        # Qt hands over 'C:/a/b.png' and the file manager 'C:\a\b.png': one spelling, so a file is never listed twice
        fresh = [p for p in (os.path.normpath(p) for p in new_paths) if inputs.is_supported(p) and p not in known]
        everything = sorted(known | set(fresh), key=inputs.natural_key)
        self.list_files.clear()
        for path in everything:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.list_files.addItem(item)
            self.set_row_status(path, "waiting")
        self.refresh_options()
        if not known:
            self.follow_first_file()
        return len(fresh)

    def refresh_options(self):
        """The document options only show when the list has a file they apply to."""
        files = self.paths()
        has_pdf = any(inputs.is_pdf(p) for p in files)
        has_document = has_pdf or any(inputs.is_archive(p) for p in files)
        for w in (self.lbl_pages, self.edit_pages, self.lbl_quality, self.combo_quality, self.chk_ocr):
            w.setVisible(has_pdf)
        self.chk_png.setVisible(has_document)
        self.docs.setVisible(has_document)

    def set_row_status(self, path, status):
        for i in range(self.list_files.count()):
            item = self.list_files.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                item.setText(f"{os.path.basename(path)}   ·   {_status_text(status)}")
                item.setToolTip(path)
                return

    def remember_dir(self, path):
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        if folder and folder != self.last_dir:
            self.last_dir = folder
            self.save_settings()

    def add_files(self):
        patterns = " ".join(f"*{ext}" for ext in inputs.SUPPORTED_EXTENSIONS)
        files, _ = QFileDialog.getOpenFileNames(self, tr("Choose files"), self.last_dir or "", f"{tr('Images')} ({patterns})")
        if files:
            self.remember_dir(files[0])
            self.add_paths(files)

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Choose a folder"), self.last_dir or "")
        if folder:
            self.remember_dir(folder)
            self.add_paths(inputs.list_folder(folder))

    # ------------------------------------------------------------------
    # Drag and drop, paste
    # ------------------------------------------------------------------
    def add_dropped(self, paths):
        """Adds what was dropped or copied: files, and the supported files directly inside folders."""
        expanded, skipped = [], 0
        for path in paths:
            if os.path.isdir(path):
                expanded.extend(inputs.list_folder(path))
            elif inputs.is_supported(path):
                expanded.append(path)
            else:
                skipped += 1
        added = self.add_paths(expanded)
        text = tr("Added {added} file(s).", added=added)
        if skipped:
            text += " " + tr("{skipped} skipped: not a supported type.", skipped=skipped)
        self.lbl_status.setText(text)
        return added

    @staticmethod
    def local_paths(mime):
        return [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]

    def dragEnterEvent(self, event):
        if not self.busy and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not self.busy and event.mimeData().hasUrls():
            self.add_dropped(self.local_paths(event.mimeData()))
            event.acceptProposedAction()

    def paste_from_clipboard(self):
        """Ctrl+V: files copied in the file manager, or a picture (a screenshot) from the clipboard."""
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit):  # the page range field keeps its normal paste
            focus.paste()
            return
        if self.busy:
            return
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        if mime is None:  # an emptied clipboard has no data at all
            self.lbl_status.setText(tr("The clipboard has no image or file."))
        elif mime.hasUrls() and self.local_paths(mime):
            self.add_dropped(self.local_paths(mime))
        elif mime.hasImage():
            image = clipboard.image()
            if image.isNull():
                return
            if self.clipboard_dir is None:
                self.clipboard_dir = tempfile.mkdtemp(prefix="ocr_translator_clipboard_")
                atexit.register(shutil.rmtree, self.clipboard_dir, True)
            path = os.path.join(self.clipboard_dir, time.strftime("clipboard_%Y-%m-%d_%H-%M-%S.png"))
            path = batch.unique_path(path)
            image.save(path, "PNG")
            self.add_paths([path])
            self.lbl_status.setText(tr("Pasted an image from the clipboard."))
        else:
            self.lbl_status.setText(tr("The clipboard has no image or file."))

    def forget(self, path):
        """A file left the list: its results are no longer needed, and a pasted picture is deleted."""
        for table in (self.status, self.outputs, self.page_rows):
            table.pop(path, None)
        if self.clipboard_dir and os.path.dirname(path) == self.clipboard_dir:
            try:
                os.remove(path)
            except OSError:
                pass

    def remove_selected(self):
        if self.busy:
            return
        for item in self.list_files.selectedItems():
            self.forget(item.data(Qt.ItemDataRole.UserRole))
            self.list_files.takeItem(self.list_files.row(item))
        self.refresh_options()
        self.refresh_retry_button()

    def clear_files(self):
        for path in self.paths():
            self.forget(path)
        self.list_files.clear()
        self.refresh_options()
        self.refresh_retry_button()

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def set_busy(self, busy):
        self.busy = busy
        for w in (self.btn_add, self.btn_add_folder, self.btn_remove, self.btn_clear, self.btn_folder, self.btn_start,
                  self.chk_images, self.chk_txt, self.chk_csv, self.chk_share):
            w.setEnabled(not busy)
        if not busy:
            self.combo_style.setEnabled(self.chk_images.isChecked())
            self.lbl_style.setEnabled(self.chk_images.isChecked())
        else:
            self.combo_style.setEnabled(False)
            self.lbl_style.setEnabled(False)
        self.btn_cancel.setEnabled(busy)
        self.chk_region.setEnabled(not busy)
        for w in (self.edit_pages, self.combo_quality, self.chk_png, self.chk_ocr, self.combo_mode):
            w.setEnabled(not busy)
        self.refresh_region_label()
        self.refresh_retry_button()
        self.refresh_preview_button()
        self.busy_changed.emit(busy)

    def resolve_out_dir(self, files):
        if self.out_dir:
            return self.out_dir
        folder = os.path.dirname(files[0])
        if self.clipboard_dir and folder == self.clipboard_dir:  # pasted pictures have no folder of their own
            return os.path.join(os.path.expanduser("~"), "Documents", "OCR Translator")
        return os.path.join(folder, "translated")

    def start(self, only=None):
        """Translates the whole list, or only the files in `only` (retrying the ones that did not finish)."""
        files = list(only) if only else self.paths()
        if not files:
            QMessageBox.information(self, tr("Translate files"), tr("Add at least one file."))
            return
        if not (self.chk_images.isChecked() or self.chk_txt.isChecked() or self.chk_csv.isChecked()):
            QMessageBox.information(self, tr("Translate files"), tr("Choose at least one thing to export."))
            return
        pages = self.edit_pages.text().strip() or None
        try:
            inputs.parse_ranges(pages)
        except ValueError as e:
            QMessageBox.information(self, tr("Translate files"), str(e))
            return
        for path in files:
            self.set_row_status(path, "waiting")
        self.expected = self.count_pages(files, pages)
        total_pages = sum(self.expected.values())
        if self.combo_mode.currentData() == MODE_DOCUMENT and total_pages > LARGE_BATCH_PAGES:
            answer = QMessageBox.question(
                self, tr("Translate files"),
                tr("About {pages} pages will be read in document mode. Every block of text is one translation request, "
                   "so a long document can reach the limit of the AI service and finish with the backup translators, "
                   "which are less accurate. Continue?", pages=total_pages))
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.progress.setRange(0, max(1, sum(self.expected.values())))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.btn_open.setEnabled(False)
        self.run_files = files
        for path in files:
            self.status[path] = "waiting"
            self.outputs.pop(path, None)
            self.page_rows[path] = []
        if not (only and self.out_dir_used):  # a retry writes next to the first run
            self.out_dir_used = self.resolve_out_dir(files)
        self.lbl_status.setText(tr("Loading AI engines…"))
        self.btn_retry.setEnabled(False)
        self.set_busy(True)
        self.engine_provider(self.on_engine_ready, self.on_engine_error)

    def on_engine_error(self, message):
        self.progress.setVisible(False)
        self.lbl_status.setText(message)
        self.set_busy(False)

    def on_engine_ready(self, engine):
        files = self.run_files
        render = self.make_renderer() if self.chk_images.isChecked() else None
        region = tuple(self.region) if self.chk_region.isChecked() and self.region else None
        self.worker = BatchWorker(engine, files, region=region, share_context=self.chk_share.isChecked(), render=render,
                                  out_dir=self.out_dir_used, target_lang=getattr(engine, "target_lang", ""),
                                  pdf_dpi=self.combo_quality.currentData(),
                                  pages=self.edit_pages.text().strip() or None, also_png=self.chk_png.isChecked(),
                                  mode=self.combo_mode.currentData(), always_ocr=self.chk_ocr.isChecked())
        self.worker.progress.connect(self.on_progress)
        self.worker.page_done.connect(self.on_page_done)
        self.worker.file_done.connect(self.on_file_done)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def make_renderer(self):
        """Draws the translation on a page with the look of the overlay (the user's opacity, text colour and padding)."""
        config = config_manager.load_config()
        style = self.combo_style.currentData()
        document = self.combo_mode.currentData() == MODE_DOCUMENT

        def render(image, results):
            return card_render.render_page(image, results, style, config["overlay_opacity"],
                                           config["overlay_text_color"], config["overlay_padding"], document)
        return render

    def cancel(self):
        if self.worker:
            self.worker.cancel()
            self.btn_cancel.setEnabled(False)
            self.lbl_status.setText(tr("Cancelling after the current page…"))

    def count_pages(self, files, pages):
        """Pages each file will give (a file that cannot be opened counts as one; it fails later with its reason)."""
        counts = {}
        for path in files:
            try:
                counts[path] = max(1, inputs.count_pages(path, pages if inputs.is_pdf(path) else None))
            except Exception:
                counts[path] = 1
        return counts

    def pages_before(self, file_n):
        return sum(self.expected.get(p, 1) for p in self.run_files[:file_n])

    def on_progress(self, file_n, file_count, page_n, page_count, label):
        self.progress.setValue(self.pages_before(file_n - 1) + page_n - 1)
        self.set_row_status(self.run_files[file_n - 1], "reading")
        self.lbl_status.setText(tr("File {file}/{files} · page {page}/{pages} — {name}", file=file_n, files=file_count,
                                   page=page_n, pages=page_count, name=label))

    def on_page_done(self, path, page_index, rows):
        self.page_rows.setdefault(path, []).extend(rows)

    def on_file_done(self, path, status, message):
        self.status[path] = status
        self.set_row_status(path, status)
        self.progress.setValue(self.pages_before(self.run_files.index(path) + 1))

    def on_finished(self, summary):
        self.worker = None
        files = self.run_files
        self.outputs.update(summary.get("outputs", {}))
        counts = {s: sum(1 for v in summary["status"].values() if v == s)
                  for s in (batch.DONE, batch.PARTIAL, batch.FAILED, batch.CANCELLED)}
        written = list(summary.get("images", []))
        if summary["rows"] and files and (self.chk_txt.isChecked() or self.chk_csv.isChecked()):
            try:
                written += batch.write_text_report(summary["rows"], self.out_dir_used,
                                                   self.chk_txt.isChecked(), self.chk_csv.isChecked())
            except OSError as e:
                logger.error(f"Could not write the report: {e}", exc_info=True)
                QMessageBox.critical(self, tr("Translate files"), tr("Could not save the files:\n{err}", err=str(e)))
        text = tr("Finished in {seconds:.0f} s — {done} done, {partial} partial, {failed} failed.",
                  seconds=summary["seconds"], done=counts[batch.DONE], partial=counts[batch.PARTIAL],
                  failed=counts[batch.FAILED])
        if counts[batch.CANCELLED] or summary["cancelled"]:
            text += " " + tr("Cancelled before the end.")
        if counts[batch.PARTIAL]:
            text += " " + tr("Partial: some lines could not be translated (marked with [ ]).")
        if written:
            text += " " + tr("Saved to {path}", path=self.out_dir_used)
        elif not summary["rows"]:
            text += " " + tr("No text was found.")
        errors = [m for m in summary["errors"].values() if m]
        if errors:
            text += "\n" + errors[0]
        self.lbl_status.setText(text)
        self.progress.setVisible(False)
        self.btn_open.setEnabled(bool(written))
        self.set_busy(False)
        self.refresh_retry_button()
        self.refresh_preview_button()

    # ------------------------------------------------------------------
    # After the run: retry and compare
    # ------------------------------------------------------------------
    def unfinished(self):
        """Files of the list that failed, finished only partly or were cancelled, in list order."""
        return [p for p in self.paths() if self.status.get(p) in (batch.FAILED, batch.PARTIAL, batch.CANCELLED)]

    def refresh_retry_button(self):
        self.btn_retry.setEnabled(not self.busy and bool(self.unfinished()))

    def retry_failed(self):
        todo = self.unfinished()
        if todo:
            self.start(only=todo)

    def selected_path(self):
        items = self.list_files.selectedItems()
        return items[0].data(Qt.ItemDataRole.UserRole) if items else None

    def refresh_preview_button(self):
        path = self.selected_path()
        self.btn_preview.setEnabled(not self.busy and path is not None and self.status.get(path) in (batch.DONE, batch.PARTIAL))

    def preview_selected(self, *_):
        path = self.selected_path()
        if path is None or self.status.get(path) not in (batch.DONE, batch.PARTIAL):
            return
        dialog = PreviewDialog(path, self.outputs.get(path, []), self.page_rows.get(path, []),
                               self.combo_quality.currentData(), self.edit_pages.text().strip() or None, self)
        dialog.exec()

    def open_output_folder(self):
        folder = getattr(self, "out_dir_used", None)
        if folder and os.path.isdir(folder):
            os.startfile(folder)

    def stop_and_wait(self, timeout_ms=8000):
        """Used when the whole application closes: stops the thread between pages."""
        if self.worker:
            self.worker.cancel()
            self.worker.wait(timeout_ms)

    def closeEvent(self, event):
        if self.busy:
            self.cancel()
            event.ignore()  # the thread finishes its page first; close again afterwards
            return
        event.accept()
