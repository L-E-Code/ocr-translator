import sys
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QPainter, QColor, QFont

class OverlayWindow(QWidget):
    def __init__(self, monitor_region):
        super().__init__()
        self.monitor_region = monitor_region
        self.texts_to_draw = []
        
        self.initUI()
        
    def initUI(self):
        # 1. Remover bordas, manter no topo e ignorar cliques
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Window |
            Qt.WindowType.WindowTransparentForInput
        )
        
        # 2. Fundo totalmente transparente
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 3. Posicionar a janela
        self.setGeometry(
            self.monitor_region['left'], 
            self.monitor_region['top'], 
            self.monitor_region['width'], 
            self.monitor_region['height']
        )
        
    def update_texts(self, new_texts):
        self.texts_to_draw = new_texts
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        font = QFont("Arial", 14, QFont.Weight.Bold)
        
        for item in self.texts_to_draw:
            box = item['box']
            traducao = item['traducao']
            
            top_left_x = int(box[0][0])
            top_left_y = int(box[0][1])
            bottom_right_x = int(box[2][0])
            bottom_right_y = int(box[2][1])
            
            width = bottom_right_x - top_left_x
            height = bottom_right_y - top_left_y
            
            painter.setBrush(QColor(0, 0, 0, 220))
            painter.setPen(Qt.PenStyle.NoPen)
            rect = QRect(top_left_x, top_left_y, width, height)
            painter.drawRect(rect)
            
            painter.setPen(QColor(255, 255, 255))
            
            font_size = max(8, int(height * 0.6))
            font.setPointSize(font_size)
            painter.setFont(font)
            
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap), traducao)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    fake_monitor = {'left': 0, 'top': 0, 'width': 1920, 'height': 1080}
    
    overlay = OverlayWindow(fake_monitor)
    
    fake_texts = [
        {
            'box': [[100, 100], [400, 100], [400, 150], [100, 150]],
            'traducao': 'Teste de Traducao 1'
        },
        {
            'box': [[800, 500], [1200, 500], [1200, 600], [800, 600]],
            'traducao': 'Menu Principal do Jogo'
        }
    ]
    
    overlay.update_texts(fake_texts)
    overlay.show()
    
    print("Overlay iniciado! Procure por dois blocos pretos com texto branco flutuando na sua tela.")
    print("Para fechar o overlay, aperte Ctrl+C neste terminal (a janela fantasma ignora cliques!).", flush=True)
    sys.exit(app.exec())

