"""Before / after preview of one file of a batch translation."""
import os

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QSizePolicy
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap

from core import inputs
from core.logger_config import get_logger
from ui.i18n import tr

logger = get_logger("Batch")


def first_page(path, pdf_dpi=inputs.DEFAULT_PDF_DPI, pages=None):
    """First page of a file as an RGB array, or None if it cannot be read."""
    try:
        return next(inputs.iter_pages(path, pdf_dpi, pages, use_text_layer=False)).image
    except Exception as e:
        logger.warning(f"Preview: could not read {os.path.basename(path)}: {e}")
        return None


def translated_picture(outputs, pdf_dpi):
    """The first page of the translated result: a PNG if there is one (cheap to read), else the PDF or CBZ."""
    candidates = [p for p in outputs if os.path.exists(p) and inputs.is_supported(p)]
    candidates.sort(key=lambda p: os.path.splitext(p)[1].lower() != ".png")
    for path in candidates:
        image = first_page(path, pdf_dpi)
        if image is not None:
            return image
    return None


class PagePreview(QLabel):
    """A picture scaled to the space it has, keeping its proportions."""
    def __init__(self):
        super().__init__()
        self._pixmap = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(240, 160)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def set_image(self, image_rgb):
        h, w = image_rgb.shape[:2]
        qimage = QImage(image_rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        self._pixmap = QPixmap.fromImage(qimage)
        self._rescale()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self):
        if self._pixmap is not None:
            self.setPixmap(self._pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))


class PreviewDialog(QDialog):
    """
    The first page of a file next to its translation. Without a translated picture (only the text was exported) the
    right side shows the translated lines instead.
    """
    def __init__(self, source, outputs, rows, pdf_dpi=inputs.DEFAULT_PDF_DPI, pages=None, parent=None):
        super().__init__(parent)
        self.setObjectName("root")
        self.setWindowTitle(tr("Preview — {name}", name=os.path.basename(source)))
        self.resize(1100, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        panes = QHBoxLayout()
        panes.setSpacing(14)

        original = first_page(source, pdf_dpi, pages)
        translated = translated_picture(outputs, pdf_dpi)

        left = QVBoxLayout()
        left.addWidget(self._title(tr("Original")))
        self.original = PagePreview()
        if original is not None:
            self.original.set_image(original)
        else:
            self.original.setText(tr("The file could not be read."))
        left.addWidget(self.original, 1)
        panes.addLayout(left, 1)

        right = QVBoxLayout()
        right.addWidget(self._title(tr("Translated")))
        self.translated = None
        self.text = None
        if translated is not None:
            self.translated = PagePreview()
            self.translated.set_image(translated)
            right.addWidget(self.translated, 1)
        else:
            self.text = QTextEdit()
            self.text.setReadOnly(True)
            self.text.setPlainText(self._rows_text(rows) or tr("Nothing was translated in this file."))
            right.addWidget(self.text, 1)
        panes.addLayout(right, 1)
        root.addLayout(panes, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton(tr("Close"))
        close.clicked.connect(self.accept)
        row.addWidget(close)
        root.addLayout(row)

    @staticmethod
    def _title(text):
        label = QLabel(text)
        label.setObjectName("muted")
        return label

    @staticmethod
    def _rows_text(rows):
        first_page_number = min((r["page"] for r in rows), default=None)
        lines = []
        for r in rows:
            if r["page"] != first_page_number:
                continue
            head = f"{r['speaker']}: " if r.get("speaker") else ""
            lines.append(f"{head}{r['translation']}")
        return "\n\n".join(lines)
