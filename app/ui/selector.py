import sys
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QRect, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from ui.i18n import tr

class ScreenSelector(QWidget):
    """
    Interactive window that covers the monitor with a semi-transparent veil
    and lets the user click and drag with the mouse to select
    the exact screen area where the texts to translate appear.
    """
    def __init__(self, monitor_region):
        super().__init__()
        self.monitor_region = monitor_region
        self.start_pos = None
        self.current_pos = None
        self.selected_rect = None
        
        self.initUI()
        
    def initUI(self):
        # Borderless window, always on top
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        
        # Positions itself over the chosen monitor
        self.setGeometry(
            self.monitor_region['left'],
            self.monitor_region['top'],
            self.monitor_region['width'],
            self.monitor_region['height']
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = event.pos()
            self.current_pos = event.pos()
            self.update()

    def mouseMoveEvent(self, event):
        if self.start_pos is not None:
            self.current_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.start_pos is not None:
            self.current_pos = event.pos()
            
            x1 = min(self.start_pos.x(), self.current_pos.x())
            y1 = min(self.start_pos.y(), self.current_pos.y())
            x2 = max(self.start_pos.x(), self.current_pos.x())
            y2 = max(self.start_pos.y(), self.current_pos.y())
            
            width = x2 - x1
            height = y2 - y1
            
            # Only accepts the area if it has a reasonable minimum size (avoids accidental clicks)
            if width > 30 and height > 20:
                self.selected_rect = {
                    'left': self.monitor_region['left'] + x1,
                    'top': self.monitor_region['top'] + y1,
                    'width': width,
                    'height': height,
                    'offset_x': x1,
                    'offset_y': y1
                }
                self.close()
            else:
                self.start_pos = None
                self.current_pos = None
                self.update()

    def keyPressEvent(self, event):
        # ESC key cancels the selection
        if event.key() == Qt.Key.Key_Escape:
            self.selected_rect = None
            self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor(56, 189, 248)

        # 1. Dark veil over the screen
        painter.fillRect(self.rect(), QColor(6, 10, 22, 150))

        # 2. Instruction in a pill at the top
        font = QFont("Segoe UI", 12, QFont.Weight.DemiBold)
        painter.setFont(font)
        info_text = tr("Click and drag over the text area to translate   ·   Esc cancels")
        text_w = painter.fontMetrics().horizontalAdvance(info_text)
        pill = QRectF((self.width() - text_w) / 2 - 22, 34, text_w + 44, 40)
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
        painter.setBrush(QColor(15, 22, 42, 235))
        painter.drawRoundedRect(pill, 20, 20)
        painter.setPen(QColor(232, 237, 247))
        painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), info_text)

        # 3. Selection rectangle
        if self.start_pos and self.current_pos:
            x = min(self.start_pos.x(), self.current_pos.x())
            y = min(self.start_pos.y(), self.current_pos.y())
            w = abs(self.current_pos.x() - self.start_pos.x())
            h = abs(self.current_pos.y() - self.start_pos.y())
            rect = QRect(x, y, w, h)

            # Clear interior to see the content
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(accent, 2))
            painter.drawRect(rect)

            # Corner handles
            painter.setBrush(accent)
            painter.setPen(Qt.PenStyle.NoPen)
            for cx, cy in ((x, y), (x + w, y), (x, y + h), (x + w, y + h)):
                painter.drawEllipse(QPointF(cx, cy), 5, 5)

            # Dimensions in a label
            label = f"{w} × {h} px"
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            lw = painter.fontMetrics().horizontalAdvance(label) + 18
            ly = y - 30 if y > 40 else y + h + 8
            tag = QRectF(x, ly, lw, 24)
            painter.setBrush(accent)
            painter.drawRoundedRect(tag, 8, 8)
            painter.setPen(QColor(4, 16, 31))
            painter.drawText(tag, int(Qt.AlignmentFlag.AlignCenter), label)

def select_region_interactive(monitor_region, app=None):
    """
    Helper function that creates the selection window and returns
    the dictionary of the region selected by the user.
    """
    should_exec = False
    if app is None:
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
            should_exec = True

    selector = ScreenSelector(monitor_region)
    selector.show()
    
    if should_exec:
        app.exec()
    else:
        # Local event loop until the user closes it
        while selector.isVisible():
            app.processEvents()
            
    return selector.selected_rect

