import sys
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QRect, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen, QFont

class ScreenSelector(QWidget):
    """
    Janela interativa que cobre o monitor com um véu semi-transparente
    e permite ao usuário clicar e arrastar com o mouse para selecionar
    a área exata da tela onde as falas do jogo aparecem.
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
        
        # 1. Fundo escuro semi-transparente cobrindo a tela
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
        
        # 2. Desenha instruções no topo
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        info_text = "CLIQUE E ARRASTE sobre a caixa de diálogo do jogo (ESC para cancelar)"
        painter.drawText(0, 40, self.width(), 40, Qt.AlignmentFlag.AlignHCenter, info_text)
        
        # 3. Desenha o retângulo de seleção aberto pelo mouse
        if self.start_pos and self.current_pos:
            x = min(self.start_pos.x(), self.current_pos.x())
            y = min(self.start_pos.y(), self.current_pos.y())
            w = abs(self.current_pos.x() - self.start_pos.x())
            h = abs(self.current_pos.y() - self.start_pos.y())
            
            rect = QRect(x, y, w, h)
            
            # Deixa o interior do retângulo transparente/nítido para ver o jogo
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, Qt.GlobalColor.transparent)
            
            # Desenha borda ciano brilhante
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            pen = QPen(QColor(0, 230, 255), 2, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.drawRect(rect)
            
            # Exibe dimensões no canto da caixa
            painter.setPen(QColor(0, 230, 255))
            painter.setFont(QFont("Arial", 10))
            painter.drawText(x + 5, y + 18, f"{w}x{h} px")

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

if __name__ == "__main__":
    fake_mon = {'left': 0, 'top': 0, 'width': 1920, 'height': 1080}
    rect = select_region_interactive(fake_mon)
    print("Região selecionada:", rect)

