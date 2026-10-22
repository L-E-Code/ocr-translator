import sys
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QRect, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QFont

class ScreenSelector(QWidget):
    """
    Janela interativa que cobre o monitor com um véu semi-transparente
    e permite ao usuário clicar e arrastar com o mouse para selecionar
    a área exata da tela onde os textos a traduzir aparecem.
    """
    def __init__(self, monitor_region):
        super().__init__()
        self.monitor_region = monitor_region
        self.start_pos = None
        self.current_pos = None
        self.selected_rect = None
        
        self.initUI()
        
    def initUI(self):
        # Janela sem borda, sempre no topo
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        
        # Posiciona sobre o monitor escolhido
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
            
            # Só aceita se a área tiver um tamanho mínimo razoável (evita cliques acidentais)
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
        # Tecla ESC cancela a seleção
        if event.key() == Qt.Key.Key_Escape:
            self.selected_rect = None
            self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor(56, 189, 248)

        # 1. Véu escuro sobre a tela
        painter.fillRect(self.rect(), QColor(6, 10, 22, 150))

        # 2. Instrução em uma pílula no topo
        font = QFont("Segoe UI", 12, QFont.Weight.DemiBold)
        painter.setFont(font)
        info_text = "Clique e arraste sobre a área do texto a traduzir   ·   Esc cancela"
        text_w = painter.fontMetrics().horizontalAdvance(info_text)
        pill = QRectF((self.width() - text_w) / 2 - 22, 34, text_w + 44, 40)
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
        painter.setBrush(QColor(15, 22, 42, 235))
        painter.drawRoundedRect(pill, 20, 20)
        painter.setPen(QColor(232, 237, 247))
        painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), info_text)

        # 3. Retângulo de seleção
        if self.start_pos and self.current_pos:
            x = min(self.start_pos.x(), self.current_pos.x())
            y = min(self.start_pos.y(), self.current_pos.y())
            w = abs(self.current_pos.x() - self.start_pos.x())
            h = abs(self.current_pos.y() - self.start_pos.y())
            rect = QRect(x, y, w, h)

            # Interior limpo para ver o conteúdo
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(accent, 2))
            painter.drawRect(rect)

            # Alças nos cantos
            painter.setBrush(accent)
            painter.setPen(Qt.PenStyle.NoPen)
            for cx, cy in ((x, y), (x + w, y), (x, y + h), (x + w, y + h)):
                painter.drawEllipse(QPointF(cx, cy), 5, 5)

            # Dimensões em uma etiqueta
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
    Função auxiliar que instancia a janela de seleção e retorna
    o dicionário da região selecionada pelo usuário.
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
        # Loop local de eventos até o usuário fechar
        while selector.isVisible():
            app.processEvents()
            
    return selector.selected_rect

