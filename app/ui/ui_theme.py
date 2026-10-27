"""
Shared visual theme of OCR Translator: palette, global stylesheet,
vector icons and components reused by the launcher, side panel and history.
"""
from html import escape
from ui.i18n import tr

from PyQt6.QtWidgets import (
    QApplication, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QWidget,
    QPushButton, QButtonGroup, QToolButton, QGraphicsOpacityEffect, QSizePolicy
)
from PyQt6.QtCore import Qt, QRectF, QPointF, QTimer, QPropertyAnimation, QSize
from PyQt6.QtGui import (
    QColor, QPainter, QPainterPath, QPen, QIcon, QPixmap, QFont,
    QLinearGradient
)

PLACEHOLDER = "[Translating with AI...]"

# ----------------------------------------------------------------------
# Palette
# ----------------------------------------------------------------------
BG = "#0a0f1e"
SURFACE = "#121a30"
SURFACE_HI = "#19233f"
BORDER = "#26324f"
BORDER_HI = "#34446b"
TEXT = "#e8edf7"
MUTED = "#8793b0"
FAINT = "#5d6a8a"
ACCENT = "#38bdf8"
ACCENT_2 = "#8b7dfa"
OK = "#34d399"
WARN = "#fbbf24"
BAD = "#f87171"
SPEAKER = "#fbbf24"

STATE_COLORS = {
    "idle": MUTED,
    "busy": ACCENT,
    "loading": WARN,
    "running": OK,
    "paused": WARN,
    "error": BAD,
}

FONT_STACK = '"Segoe UI Variable Text", "Segoe UI", Arial, sans-serif'


def _chevron_path():
    """Generates (once) the PNG of the combo box arrow, referenced by the QSS."""
    import os, tempfile
    folder = os.path.join(tempfile.gettempdir(), "ocr_translator_ui")
    path = os.path.join(folder, "chevron.png")
    try:
        os.makedirs(folder, exist_ok=True)
        px = QPixmap(24, 24)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(MUTED), 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(6, 9), QPointF(12, 15), QPointF(18, 9)])
        p.end()
        px.save(path)

        tick = QPixmap(24, 24)
        tick.fill(Qt.GlobalColor.transparent)
        p = QPainter(tick)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#04101f"), 3.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(5.5, 12.5), QPointF(10, 17), QPointF(18.5, 7)])
        p.end()
        tick.save(os.path.join(folder, "check.png"))
    except Exception:
        pass
    return path.replace("\\", "/")


def _check_path():
    import os, tempfile
    return os.path.join(tempfile.gettempdir(), "ocr_translator_ui", "check.png").replace("\\", "/")


def app_stylesheet():
    CHEVRON_PATH = _chevron_path()
    CHECK_PATH = _check_path()
    return f"""
    QWidget {{
        color: {TEXT};
        font-family: {FONT_STACK};
        font-size: 13px;
    }}
    QMainWindow, QDialog, QWidget#root {{
        background-color: {BG};
    }}
    QScrollArea, QScrollArea > QWidget > QWidget {{
        background: transparent;
        border: none;
    }}
    QToolTip {{
        background-color: {SURFACE_HI};
        color: {TEXT};
        border: 1px solid {BORDER_HI};
        border-radius: 6px;
        padding: 5px 8px;
    }}

    QFrame#card {{
        background-color: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 14px;
    }}
    QLabel#cardTitle {{
        color: {MUTED};
        font-size: 11px;
        font-weight: 700;
    }}
    QLabel#muted {{ color: {MUTED}; }}
    QLabel#hint {{ color: {FAINT}; font-size: 11px; }}
    QLabel#accentValue {{ color: {ACCENT}; font-weight: 600; }}

    QComboBox {{
        background-color: {BG};
        border: 1px solid {BORDER};
        border-radius: 9px;
        padding: 7px 12px;
        min-height: 18px;
    }}
    QComboBox:hover {{ border-color: {BORDER_HI}; }}
    QComboBox:focus, QComboBox:on {{ border-color: {ACCENT}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox::down-arrow {{ image: url("{CHEVRON_PATH}"); width: 12px; height: 12px; margin-right: 6px; }}
    QComboBox QAbstractItemView {{
        background-color: {SURFACE_HI};
        border: 1px solid {BORDER_HI};
        border-radius: 8px;
        selection-background-color: {ACCENT};
        selection-color: #04101f;
        padding: 4px;
        outline: none;
    }}

    QLineEdit {{
        background-color: {BG};
        border: 1px solid {BORDER};
        border-radius: 9px;
        padding: 7px 12px;
        selection-background-color: {ACCENT};
        selection-color: #04101f;
    }}
    QLineEdit:focus {{ border-color: {ACCENT}; }}

    QTableWidget {{
        background-color: {BG};
        alternate-background-color: {BG};
        border: 1px solid {BORDER};
        border-radius: 9px;
        gridline-color: {BORDER};
        selection-background-color: {ACCENT};
        selection-color: #04101f;
    }}
    QTableWidget QLineEdit {{ border-radius: 0; padding: 2px 6px; }}
    QHeaderView::section {{
        background-color: {BG};
        color: {MUTED};
        border: none;
        border-bottom: 1px solid {BORDER};
        padding: 6px 8px;
        font-weight: 600;
    }}
    QTableCornerButton::section {{ background-color: {BG}; border: none; }}

    QCheckBox {{ color: {MUTED}; spacing: 9px; }}
    QCheckBox:hover {{ color: {TEXT}; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px;
        border-radius: 5px;
        border: 1px solid {BORDER_HI};
        background-color: {BG};
    }}
    QCheckBox::indicator:checked {{
        background-color: {ACCENT};
        border-color: {ACCENT};
        image: url("{CHECK_PATH}");
    }}

    QPushButton {{
        background-color: {SURFACE_HI};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 9px 14px;
        font-weight: 600;
    }}
    QPushButton:hover {{ background-color: {BORDER}; border-color: {BORDER_HI}; }}
    QPushButton:pressed {{ background-color: {BG}; }}
    QPushButton:disabled {{ color: {FAINT}; background-color: {SURFACE}; border-color: {BORDER}; }}

    QPushButton[variant="primary"] {{
        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2fb8f2, stop:1 #7f78f4);
        color: #04101f;
        border: none;
        font-size: 14px;
        font-weight: 700;
        padding: 13px 16px;
    }}
    QPushButton[variant="primary"]:hover {{
        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #5ccbf8, stop:1 #968ff7);
    }}
    QPushButton[variant="primary"]:disabled {{ background-color: {SURFACE_HI}; color: {FAINT}; }}
    QPushButton[variant="danger"] {{
        background-color: #3a1620;
        color: {BAD};
        border: 1px solid #6b2433;
        font-size: 14px;
        font-weight: 700;
        padding: 13px 16px;
    }}
    QPushButton[variant="danger"]:hover {{ background-color: #4b1b28; border-color: {BAD}; }}
    QPushButton[variant="ghost"] {{
        background-color: transparent;
        border: 1px solid transparent;
        color: {MUTED};
    }}
    QPushButton[variant="ghost"]:hover {{ background-color: {SURFACE_HI}; color: {TEXT}; }}
    QPushButton[variant="seg"] {{
        background-color: transparent;
        border: none;
        border-radius: 8px;
        color: {MUTED};
        padding: 7px 12px;
        font-weight: 600;
    }}
    QPushButton[variant="seg"]:hover {{ color: {TEXT}; }}
    QPushButton[variant="seg"]:checked {{ background-color: {SURFACE_HI}; color: {ACCENT}; border: 1px solid {BORDER_HI}; }}
    QPushButton[variant="seg"]:disabled {{ color: {FAINT}; }}
    QPushButton[variant="seg"]:checked:disabled {{ color: {MUTED}; }}

    QToolButton {{
        background-color: transparent;
        border: 1px solid transparent;
        border-radius: 9px;
        padding: 6px;
    }}
    QToolButton:hover {{ background-color: {SURFACE_HI}; border-color: {BORDER}; }}
    QToolButton:pressed {{ background-color: {BORDER}; }}
    QToolButton:checked {{ background-color: {SURFACE_HI}; border-color: {ACCENT}; }}
    QToolButton:disabled {{ background-color: transparent; }}

    QFrame#segmented {{
        background-color: {BG};
        border: 1px solid {BORDER};
        border-radius: 11px;
    }}

    QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; margin: 0; }}
    QSlider::add-page:horizontal {{ background: {BORDER}; height: 4px; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {ACCENT}; height: 4px; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: {TEXT};
        width: 14px; height: 14px;
        margin: -5px 0;
        border-radius: 7px;
    }}
    QSlider::handle:horizontal:hover {{ background: {ACCENT}; }}
    QSlider::sub-page:horizontal:disabled {{ background: {FAINT}; }}

    QProgressBar {{
        background-color: {BG};
        border: none;
        border-radius: 2px;
        max-height: 4px;
        min-height: 4px;
    }}
    QProgressBar::chunk {{
        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 {ACCENT_2});
        border-radius: 2px;
    }}

    QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {BORDER}; min-height: 30px; border-radius: 3px; }}
    QScrollBar::handle:vertical:hover {{ background: {BORDER_HI}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QScrollBar:horizontal {{ height: 0; }}

    QFrame#dialogue {{
        background-color: {SURFACE};
        border: 1px solid {BORDER};
        border-left: 3px solid {ACCENT};
        border-radius: 12px;
    }}
    QFrame#dialogue[loading="true"] {{ border-left-color: {WARN}; }}
    QLabel#speakerChip {{
        color: {SPEAKER};
        background-color: #2a2110;
        border: 1px solid #5c4716;
        border-radius: 9px;
        padding: 2px 10px;
        font-weight: 700;
        font-size: 12px;
    }}
    QLabel#textChip {{ color: {FAINT}; font-size: 11px; font-weight: 700; }}
    QLabel#translation {{ color: {TEXT}; font-weight: 600; }}
    QLabel#translation[loading="true"] {{ color: {WARN}; }}
    QLabel#original {{ color: {MUTED}; }}
    QLabel#time {{ color: {FAINT}; font-size: 11px; }}
    """


def apply_theme(app: QApplication):
    app.setStyle("Fusion")
    app.setStyleSheet(app_stylesheet())


def set_variant(widget, variant):
    """Switches the style variant ('variant' property) and reapplies the QSS."""
    widget.setProperty("variant", variant)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def set_flag(widget, name, value):
    widget.setProperty(name, "true" if value else "false")
    widget.style().unpolish(widget)
    widget.style().polish(widget)


# ----------------------------------------------------------------------
# Vector icons
# ----------------------------------------------------------------------
def icon(name, color=TEXT, size=18):
    """Icon drawn as a vector (sharp at any DPI)."""
    scale = 2
    px = QPixmap(size * scale, size * scale)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(scale * size / 20.0, scale * size / 20.0)
    col = QColor(color)
    pen = QPen(col, 1.7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    if name == "play":
        path = QPainterPath()
        path.moveTo(6, 3.5); path.lineTo(16, 10); path.lineTo(6, 16.5); path.closeSubpath()
        p.setBrush(col); p.drawPath(path)
    elif name == "stop":
        p.setBrush(col)
        p.drawRoundedRect(QRectF(4.5, 4.5, 11, 11), 2.5, 2.5)
    elif name == "pause":
        p.setBrush(col)
        p.drawRoundedRect(QRectF(5, 4, 3.4, 12), 1.4, 1.4)
        p.drawRoundedRect(QRectF(11.6, 4, 3.4, 12), 1.4, 1.4)
    elif name == "refresh":
        p.drawArc(QRectF(4, 4, 12, 12), 40 * 16, 270 * 16)
        path = QPainterPath()
        path.moveTo(14.6, 2.6); path.lineTo(15.2, 6.6); path.lineTo(11.4, 6.0)
        p.setBrush(col); p.drawPath(path)
    elif name == "history":
        p.drawEllipse(QRectF(3.5, 3.5, 13, 13))
        p.drawLine(QPointF(10, 6.5), QPointF(10, 10))
        p.drawLine(QPointF(10, 10), QPointF(12.6, 11.6))
    elif name == "folder":
        path = QPainterPath()
        path.moveTo(3, 6); path.lineTo(3, 15); path.lineTo(17, 15); path.lineTo(17, 7.5)
        path.lineTo(9.5, 7.5); path.lineTo(8, 5.5); path.lineTo(4, 5.5); path.closeSubpath()
        p.drawPath(path)
    elif name == "trash":
        p.drawLine(QPointF(4, 6), QPointF(16, 6))
        p.drawLine(QPointF(8, 6), QPointF(8, 4)); p.drawLine(QPointF(8, 4), QPointF(12, 4)); p.drawLine(QPointF(12, 4), QPointF(12, 6))
        path = QPainterPath()
        path.moveTo(5.5, 6); path.lineTo(6.3, 16); path.lineTo(13.7, 16); path.lineTo(14.5, 6)
        p.drawPath(path)
    elif name == "target":
        p.drawEllipse(QRectF(4, 4, 12, 12))
        p.setBrush(col); p.drawEllipse(QRectF(8.6, 8.6, 2.8, 2.8)); p.setBrush(Qt.BrushStyle.NoBrush)
        for a, b in (((10, 1.5), (10, 4.5)), ((10, 15.5), (10, 18.5)), ((1.5, 10), (4.5, 10)), ((15.5, 10), (18.5, 10))):
            p.drawLine(QPointF(*a), QPointF(*b))
    elif name == "copy":
        p.drawRoundedRect(QRectF(7, 7, 9, 9), 2, 2)
        path = QPainterPath()
        path.moveTo(5.5, 13); path.lineTo(5.5, 5.5); path.quadTo(5.5, 4, 7, 4); path.lineTo(13, 4)
        p.drawPath(path)
    elif name == "pin":
        p.setBrush(col)
        path = QPainterPath()
        path.moveTo(7, 3.5); path.lineTo(13, 3.5); path.lineTo(12.2, 8.5); path.lineTo(14.5, 11); path.lineTo(5.5, 11)
        path.lineTo(7.8, 8.5); path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(10, 11), QPointF(10, 16.5))
    elif name == "search":
        p.drawEllipse(QRectF(3.5, 3.5, 9, 9))
        p.drawLine(QPointF(11.2, 11.2), QPointF(16, 16))
    elif name == "download":
        p.drawLine(QPointF(10, 3.5), QPointF(10, 12.5))
        p.drawLine(QPointF(6.4, 9.2), QPointF(10, 12.8)); p.drawLine(QPointF(13.6, 9.2), QPointF(10, 12.8))
        p.drawLine(QPointF(4, 16), QPointF(16, 16))
    elif name == "wait":
        p.setBrush(col)
        for i, x in enumerate((4.5, 8.7, 12.9)):
            p.drawEllipse(QRectF(x, 8.6, 2.6, 2.6))
    p.end()
    px.setDevicePixelRatio(scale)
    return QIcon(px)


def icon_button(name, tooltip, color=MUTED, size=18, checkable=False):
    btn = QToolButton()
    btn.setIcon(icon(name, color, size))
    btn.setIconSize(QSize(size, size))
    btn.setToolTip(tooltip)
    btn.setCheckable(checkable)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setAutoRaise(True)
    return btn


# ----------------------------------------------------------------------
# Componentes
# ----------------------------------------------------------------------
class Card(QFrame):
    """Panel with an uppercase title; the content goes into self.body (QVBoxLayout)."""
    def __init__(self, title=None, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 18)
        outer.setSpacing(12)
        if title:
            lbl = QLabel(title.upper())
            lbl.setObjectName("cardTitle")
            outer.addWidget(lbl)
        self.body = outer


class StatusPill(QWidget):
    """Status pill with a pulsing indicator when there is activity."""
    def __init__(self, text="Ready", kind="idle", parent=None):
        super().__init__(parent)
        self._text = text
        self._kind = kind
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._advance)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set_state(text, kind)

    def set_state(self, text, kind):
        self._text = text
        self._kind = kind
        if kind in ("busy", "loading", "running"):
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self._phase = 0.0
        self.updateGeometry()
        self.update()

    def _advance(self):
        self._phase = (self._phase + 0.025) % 1.0
        self.update()

    def sizeHint(self):
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self._text) + 46, 30)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(STATE_COLORS.get(self._kind, MUTED))
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        bg = QColor(col); bg.setAlpha(28)
        edge = QColor(col); edge.setAlpha(80)
        p.setPen(QPen(edge, 1))
        p.setBrush(bg)
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)

        cx, cy = 16.0, rect.height() / 2
        if self._timer.isActive():
            ring = QColor(col); ring.setAlpha(int(110 * (1 - self._phase)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ring)
            r = 4 + 6 * self._phase
            p.drawEllipse(QPointF(cx, cy), r, r)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawEllipse(QPointF(cx, cy), 4, 4)

        p.setPen(col)
        font = QFont(self.font()); font.setWeight(QFont.Weight.DemiBold); font.setPixelSize(12)
        p.setFont(font)
        p.drawText(QRectF(28, 0, rect.width() - 30, rect.height()),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self._text)


class LogoMark(QWidget):
    """Application mark: gradient square with the ideogram 訳 (translation)."""
    def __init__(self, size=40, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0, QColor("#2fb8f2"))
        grad.setColorAt(1, QColor("#7f78f4"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(rect, rect.width() * 0.28, rect.width() * 0.28)
        font = QFont("Yu Gothic UI")
        font.setPixelSize(int(rect.height() * 0.58))
        font.setWeight(QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QColor("#04101f"))
        p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), "訳")


class SegmentedControl(QFrame):
    """Segmented selector (exclusive). The buttons are checkable QPushButtons."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("segmented")
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(3, 3, 3, 3)
        self._layout.setSpacing(2)

    def add(self, text, button_id, tooltip=None):
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setProperty("variant", "seg")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setMinimumWidth(1)  # lets the control shrink in a narrow column
        if tooltip:
            btn.setToolTip(tooltip)
        self.group.addButton(btn, button_id)
        self._layout.addWidget(btn, 1)
        return btn


class RegionPreview(QWidget):
    """Monitor thumbnail showing the chosen capture area."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._mon_w, self._mon_h = 1920, 1080
        self._regions = []  # [((x, y, w, h) relative (0..1), label)]
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(128)

    def set_monitor(self, width, height):
        self._mon_w, self._mon_h = max(1, width), max(1, height)
        self.update()

    def set_region(self, rel, label=""):
        self.set_regions([(rel, label)] if rel else [])

    def set_regions(self, regions):
        self._regions = list(regions)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        avail = QRectF(self.rect()).adjusted(0, 4, 0, -4)
        ratio = self._mon_w / self._mon_h
        h = avail.height() - 10
        w = h * ratio
        if w > avail.width() - 20:
            w = avail.width() - 20
            h = w / ratio
        screen = QRectF(avail.center().x() - w / 2, avail.center().y() - h / 2 - 1, w, h)

        # Monitor stand
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(BORDER))
        p.drawRoundedRect(QRectF(screen.center().x() - 22, screen.bottom() + 3, 44, 4), 2, 2)

        # Screen
        grad = QLinearGradient(screen.topLeft(), screen.bottomLeft())
        grad.setColorAt(0, QColor("#162040"))
        grad.setColorAt(1, QColor("#0c1329"))
        p.setPen(QPen(QColor(BORDER_HI), 1.4))
        p.setBrush(grad)
        p.drawRoundedRect(screen, 7, 7)

        for rel, label in self._regions:
            rx, ry, rw, rh = rel
            region = QRectF(screen.left() + rx * screen.width(), screen.top() + ry * screen.height(),
                            rw * screen.width(), rh * screen.height())
            region = region.intersected(screen.adjusted(1, 1, -1, -1))
            fill = QColor(ACCENT); fill.setAlpha(46)
            p.setBrush(fill)
            pen = QPen(QColor(ACCENT), 1.6, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawRoundedRect(region, 3, 3)
            if label and region.width() > 70 and region.height() > 16:
                f = QFont(self.font()); f.setPixelSize(11); f.setWeight(QFont.Weight.DemiBold)
                p.setFont(f)
                p.setPen(QColor(ACCENT))
                p.drawText(region, int(Qt.AlignmentFlag.AlignCenter), label)


# Word dictionary (optional): when set, the original text becomes clickable words
_word_dictionary = None


def set_word_dictionary(dictionary):
    global _word_dictionary
    _word_dictionary = dictionary


class WordPopup(QFrame):
    """Bubble with the reading and meaning of a word, closed by clicking outside."""
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("wordPopup")
        self.setStyleSheet(
            f"QFrame#wordPopup {{ background: {SURFACE_HI}; border: 1px solid {BORDER_HI}; border-radius: 10px; }}"
            f"QLabel {{ color: {TEXT}; background: transparent; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(360)
        self.label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.label)

    def show_word(self, word, entries, pos):
        title = f'<span style="font-size:18px; font-weight:700;">{escape(word.surface)}</span>'
        if word.lemma and word.lemma != word.surface:
            title += f' <span style="color:{MUTED};">→ {escape(word.lemma)}</span>'
        body = [title]
        if not entries:
            body.append(f'<span style="color:{MUTED};">{tr("No entry in the dictionary.")}</span>')
        for e in entries[:5]:
            head = f'<span style="color:{ACCENT};">{escape(e.reading)}</span>'
            if e.pos:
                head += f' <span style="color:{FAINT}; font-size:11px;">{escape(e.pos)}</span>'
            body.append(f'{head}<br>{escape("; ".join(e.glosses))}')
        self.label.setText("<br><br>".join(body))
        self.adjustSize()
        self.move(pos)
        self.show()


class DialogueCard(QFrame):
    """
    Line card (side panel and history): speaker, highlighted translation,
    gray original and a copy button. Shows an animated "Translating…" while the AI responds.
    """
    def __init__(self, speaker="", original="", translation="", timestamp=None, compact=False, parent=None, tag="TEXT"):
        super().__init__(parent)
        self.setObjectName("dialogue")
        self.tag = tag  # label shown when there is no speaker (e.g. the capture region's label)
        self.speaker = speaker
        self.original = original
        self.translation = translation
        self.timestamp = timestamp
        self._compact = compact
        self._loading = False
        self._dots = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 12, 14)
        root.setSpacing(7)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.lbl_speaker = QLabel()
        header.addWidget(self.lbl_speaker)
        header.addStretch()
        if timestamp:
            self.lbl_time = QLabel(timestamp)
            self.lbl_time.setObjectName("time")
            header.addWidget(self.lbl_time)
        self.btn_copy = icon_button("copy", tr("Copy translation"), FAINT, 15)
        self.btn_copy.clicked.connect(self.copy_translation)
        header.addWidget(self.btn_copy)
        root.addLayout(header)

        self.lbl_trans = QLabel()
        self.lbl_trans.setObjectName("translation")
        self.lbl_trans.setWordWrap(True)
        self.lbl_trans.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_trans.setStyleSheet(f"font-size: {15 if compact else 19}px; font-weight: 600;")
        root.addWidget(self.lbl_trans)

        self.lbl_orig = QLabel()
        self.lbl_orig.setObjectName("original")
        self.lbl_orig.setWordWrap(True)
        self.lbl_orig.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.lbl_orig.linkActivated.connect(self._show_word)
        self._words = []
        self._popup = None
        self.lbl_orig.setStyleSheet(
            f'font-family: "Yu Gothic UI", "Meiryo UI", "Segoe UI"; font-size: {13 if compact else 14}px;'
        )
        root.addWidget(self.lbl_orig)

        self._effect = QGraphicsOpacityEffect(self.lbl_trans)
        self.lbl_trans.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(220)
        self._fade.setStartValue(0.2)
        self._fade.setEndValue(1.0)

        self._dots_timer = QTimer(self)
        self._dots_timer.setInterval(350)
        self._dots_timer.timeout.connect(self._tick_dots)

        self.set_content(speaker, original, translation, animate=False)

    def set_content(self, speaker, original, translation, animate=True):
        changed = translation != self.translation
        self.speaker, self.original, self.translation = speaker, original, translation

        if speaker:
            self.lbl_speaker.setObjectName("speakerChip")
            self.lbl_speaker.setText(speaker)
        else:
            self.lbl_speaker.setObjectName("textChip")
            self.lbl_speaker.setText(self.tag)
        self.lbl_speaker.style().unpolish(self.lbl_speaker)
        self.lbl_speaker.style().polish(self.lbl_speaker)

        self._set_original(original)
        self.lbl_orig.setVisible(bool(original))

        loading = PLACEHOLDER in (translation or "")
        self._loading = loading
        set_flag(self, "loading", loading)
        set_flag(self.lbl_trans, "loading", loading)
        self.btn_copy.setVisible(not loading)
        if loading:
            self._dots = 0
            self._tick_dots()
            self._dots_timer.start()
            self._effect.setOpacity(1.0)
        else:
            self._dots_timer.stop()
            self.lbl_trans.setText(translation)
            if animate and changed:
                self._fade.stop()
                self._fade.start()

    def retranslate(self):
        """The interface language changed: updates the texts the card itself owns."""
        self.btn_copy.setToolTip(tr("Copy translation"))
        if self.lbl_orig.toolTip():
            self.lbl_orig.setToolTip(tr("Click a word to see its reading and meaning"))

    def _set_original(self, original):
        """Original text; with the dictionary available, each word becomes a clickable link."""
        dictionary = _word_dictionary
        self._words = dictionary.words(original) if dictionary and original else []
        if not self._words:
            self.lbl_orig.setTextFormat(Qt.TextFormat.PlainText)
            self.lbl_orig.setText(original)
            self.lbl_orig.setToolTip("")
            return
        parts = []
        for i, w in enumerate(self._words):
            text = escape(w.surface)
            parts.append(f'<a href="{i}" style="color:{TEXT}; text-decoration:none;">{text}</a>'
                         if w.clickable else text)
        self.lbl_orig.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_orig.setText("".join(parts))
        self.lbl_orig.setToolTip(tr("Click a word to see its reading and meaning"))

    def _show_word(self, href):
        try:
            word = self._words[int(href)]
        except (ValueError, IndexError):
            return
        from PyQt6.QtGui import QCursor
        if self._popup is None:
            self._popup = WordPopup(self)
        pos = QCursor.pos()
        self._popup.show_word(word, _word_dictionary.lookup(word), QPointF(pos.x() + 8, pos.y() + 14).toPoint())

    def _tick_dots(self):
        self._dots = (self._dots + 1) % 4
        self.lbl_trans.setText(tr("Translating") + "." * self._dots)

    def copy_translation(self):
        if self.translation and not self._loading:
            QApplication.clipboard().setText(self.translation)
            self.btn_copy.setIcon(icon("copy", OK, 15))
            QTimer.singleShot(900, lambda: self.btn_copy.setIcon(icon("copy", FAINT, 15)))

    def matches(self, needle):
        needle = needle.lower()
        return (needle in (self.speaker or "").lower() or needle in (self.original or "").lower()
                or needle in (self.translation or "").lower())


def app_icon(size=64):
    """Application icon (system tray): rounded square with the ideogram 訳 ("translation")."""
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor(ACCENT))
    grad.setColorAt(1, QColor(ACCENT_2))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(QRectF(2, 2, size - 4, size - 4), size * 0.22, size * 0.22)
    font = QFont("Yu Gothic UI", int(size * 0.5), QFont.Weight.Bold)
    p.setFont(font)
    p.setPen(QColor("#04101f"))
    p.drawText(QRectF(0, 0, size, size), int(Qt.AlignmentFlag.AlignCenter), "訳")
    p.end()
    return QIcon(px)
