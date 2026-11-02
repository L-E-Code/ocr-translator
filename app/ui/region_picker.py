"""Dialog to draw, on the first page of a batch, the area where the dialogue box is (applied to every page)."""
import numpy as np
from PyQt6.QtWidgets import QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap

from ui import ui_theme
from ui.i18n import tr
from ui.ui_theme import set_variant

# Smallest area accepted, as a fraction of the page (avoids an accidental click being taken as a region)
MIN_WIDTH = 0.03
MIN_HEIGHT = 0.02


def to_fractions(p1, p2, area):
    """
    Region (x, y, width, height) as fractions of the page, from two corner points in widget coordinates and the
    rectangle `area` the page occupies in the widget. Points outside the page are clamped to its edge. None if the
    result is too small.
    """
    def clamp(point):
        x = min(max(point.x(), area.left()), area.right())
        y = min(max(point.y(), area.top()), area.bottom())
        return (x - area.left()) / area.width(), (y - area.top()) / area.height()

    (x1, y1), (x2, y2) = clamp(p1), clamp(p2)
    x, y, w, h = min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)
    return (x, y, w, h) if w >= MIN_WIDTH and h >= MIN_HEIGHT else None


def region_text(region):
    """'x 12% · y 60% · 76% × 30%' for the label of the dialog."""
    if not region:
        return tr("whole page")
    x, y, w, h = (round(v * 100) for v in region)
    return tr("{w}% × {h}% of the page, from {x}% / {y}%", x=x, y=y, w=w, h=h)


def _qimage(image_rgb):
    h, w = image_rgb.shape[:2]
    data = np.ascontiguousarray(image_rgb[:, :, :3])
    return QImage(data.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class RegionCanvas(QWidget):
    """The page, scaled to fit, with a veil outside the chosen area. Click and drag to choose."""
    changed = pyqtSignal()

    def __init__(self, image_rgb, region=None):
        super().__init__()
        self.pixmap = QPixmap.fromImage(_qimage(image_rgb))
        self.region = tuple(region) if region else None
        self._start = None
        self._current = None
        self.setMinimumSize(560, 340)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def page_area(self):
        """Where the page is drawn: as large as fits, centred, keeping its proportions."""
        box = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        scale = min(box.width() / self.pixmap.width(), box.height() / self.pixmap.height())
        w, h = self.pixmap.width() * scale, self.pixmap.height() * scale
        return QRectF(box.center().x() - w / 2, box.center().y() - h / 2, w, h)

    def _fraction_rect(self, region, area):
        x, y, w, h = region
        return QRectF(area.left() + x * area.width(), area.top() + y * area.height(), w * area.width(), h * area.height())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = self._current = QPointF(event.position())
            self.update()

    def mouseMoveEvent(self, event):
        if self._start is not None:
            self._current = QPointF(event.position())
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._start is not None:
            region = to_fractions(self._start, QPointF(event.position()), self.page_area())
            if region:
                self.region = region
            self._start = self._current = None
            self.update()
            self.changed.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(ui_theme.BG))
        area = self.page_area()
        painter.drawPixmap(area, self.pixmap, QRectF(self.pixmap.rect()))

        shown = None
        if self._start is not None:
            shown = to_fractions(self._start, self._current, area)
            if shown:
                painter.setPen(QPen(QColor(255, 255, 255, 150), 1, Qt.PenStyle.DashLine))
        elif self.region:
            shown = self.region
        if not shown:
            return
        rect = self._fraction_rect(shown, area)
        veil = QColor(6, 10, 22, 165)
        painter.fillRect(QRectF(area.left(), area.top(), area.width(), rect.top() - area.top()), veil)
        painter.fillRect(QRectF(area.left(), rect.bottom(), area.width(), area.bottom() - rect.bottom()), veil)
        painter.fillRect(QRectF(area.left(), rect.top(), rect.left() - area.left(), rect.height()), veil)
        painter.fillRect(QRectF(rect.right(), rect.top(), area.right() - rect.right(), rect.height()), veil)
        accent = QColor(ui_theme.ACCENT)
        painter.setPen(QPen(accent, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)
        painter.setBrush(accent)
        painter.setPen(Qt.PenStyle.NoPen)
        for corner in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()):
            painter.drawEllipse(corner, 5, 5)


class RegionPickerDialog(QDialog):
    """Modal window: the first page, and the area drawn on it. `region` is None until one is chosen."""
    def __init__(self, image_rgb, region=None, parent=None):
        super().__init__(parent)
        self.setObjectName("root")
        self.setWindowTitle(tr("Choose the dialogue area"))
        self.resize(900, 600)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        hint = QLabel(tr("Click and drag over the area where the text to translate appears. It is applied to every file."))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.canvas = RegionCanvas(image_rgb, region)
        self.canvas.changed.connect(self.on_region_changed)
        root.addWidget(self.canvas, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.lbl_region = QLabel("")
        self.lbl_region.setObjectName("hint")
        row.addWidget(self.lbl_region, 1)
        self.btn_whole = QPushButton(tr("Whole page"))
        self.btn_whole.clicked.connect(self.use_whole_page)
        self.btn_cancel = QPushButton(tr("Cancel"))
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton(tr("Use this area"))
        set_variant(self.btn_ok, "primary")
        self.btn_ok.clicked.connect(self.accept)
        for b in (self.btn_whole, self.btn_cancel, self.btn_ok):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(b)
        root.addLayout(row)
        self.on_region_changed()

    @property
    def region(self):
        return self.canvas.region

    def on_region_changed(self):
        self.lbl_region.setText(region_text(self.canvas.region))
        self.btn_ok.setEnabled(self.canvas.region is not None)

    def use_whole_page(self):
        self.canvas.region = None
        self.accept()


def pick_region(parent, image_rgb, current=None):
    """Opens the dialog. Returns (accepted, region): region is None when the user chose the whole page."""
    dialog = RegionPickerDialog(image_rgb, current, parent)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    return accepted, dialog.region
