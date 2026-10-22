import sys
import ctypes
from difflib import SequenceMatcher
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRect, QRectF, QTimer
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QFontMetrics
from logger_config import get_logger

logger = get_logger("Overlay")

class OverlayWindow(QWidget):
    """
    Janela transparente do Modo Fantasma (HUD Overlay).
    Renderiza legendas e caixas de tradução flutuantes diretamente sobre a tela,
    com exclusão nativa de captura via Win32 (invisível para o OCR e capturadores),
    dimensionamento dinâmico sem corte de texto e integração com o histórico.
    """
    def __init__(self, monitor_region, history_window=None):
        super().__init__()
        self.monitor_region = monitor_region
        self.history_window = history_window
        
        self.texts_to_draw = []
        self.last_confirmed_original = ""
        self.last_confirmed_speaker = ""
        
        # Timer para esmaecer/limpar o overlay quando a tela não tiver mais diálogo
        self.auto_clear_timer = QTimer(self)
        self.auto_clear_timer.setSingleShot(True)
        self.auto_clear_timer.timeout.connect(self._clear_texts)
        
        self.initUI()
        self.apply_capture_exclusion()
        
    def initUI(self):
        # 1. Flags: sem borda, sempre no topo, tipo Tool (sem poluir barra de tarefas), transparente para cliques
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        
        # 2. Atributos de transparência e mouse
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        # 3. Posicionamento cobrindo exatamente o monitor escolhido
        self.setGeometry(
            self.monitor_region['left'], 
            self.monitor_region['top'], 
            self.monitor_region['width'], 
            self.monitor_region['height']
        )

    def apply_capture_exclusion(self):
        """
        Aplica WDA_EXCLUDEFROMCAPTURE (0x00000011) via Win32 API.
        Faz com que a janela do overlay seja renderizada na tela para o usuário,
        mas fique 100% invisível para captura de tela (GDI BitBlt, MSS, OBS, print screen).
        Isso impede a retroalimentação onde o OCR capturava a própria tarja.
        """
        if sys.platform != "win32":
            return
            
        try:
            hwnd = int(self.winId())
            WDA_EXCLUDEFROMCAPTURE = 0x00000011
            res = ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
            if res:
                logger.info("Exclusão de captura de tela (SetWindowDisplayAffinity) ativada com sucesso.")
            else:
                err = ctypes.GetLastError()
                logger.warning(f"SetWindowDisplayAffinity retornou 0 (código Win32: {err}).")
        except Exception as e:
            logger.error(f"Falha ao configurar exclusão de captura no Overlay: {e}")

    def showEvent(self, event):
        super().showEvent(event)
        # Re-aplica a exclusão de captura ao exibir para garantir vínculo com o HWND ativo
        self.apply_capture_exclusion()

    def update_texts(self, new_texts):
        """
        Recebe a lista de itens traduzidos e atualiza o overlay na tela.
        Também envia para o histórico de traduções se disponível.
        """
        if not new_texts:
            # Se recebeu lista vazia, agenda a limpeza suave em 1.5s
            if not self.auto_clear_timer.isActive() and self.texts_to_draw:
                self.auto_clear_timer.start(1500)
            return

        self.auto_clear_timer.stop()
        self.texts_to_draw = new_texts
        self.update()

        # Alimenta o Histórico se configurado
        self._record_to_history(new_texts)

    def _clear_texts(self):
        """Limpa as tarjas quando o diálogo sumiu da cena."""
        if self.texts_to_draw:
            self.texts_to_draw = []
            self.update()

    def _record_to_history(self, items):
        if not self.history_window or not items:
            return

        speakers = [item['original'].strip() for item in items if item.get('is_name')]
        speaker_name = speakers[0] if speakers else ""

        dialogue_items = [item for item in items if not item.get('is_name')]
        if not dialogue_items and speakers:
            dialogue_items = [item for item in items]
            speaker_name = ""

        if not dialogue_items:
            return

        combined_orig = " ".join(item['original'].strip() for item in dialogue_items if item.get('original'))
        combined_trad = " ".join(item['traducao'].strip() for item in dialogue_items if item.get('traducao'))

        if not combined_orig or not combined_trad or "[Traduzindo com IA...]" in combined_trad:
            return

        similarity = 0.0
        if self.last_confirmed_original:
            similarity = SequenceMatcher(None, combined_orig, self.last_confirmed_original).ratio()

        if similarity >= 0.70:
            self.history_window.update_last_entry(
                speaker=speaker_name or self.last_confirmed_speaker,
                original=combined_orig,
                traducao=combined_trad
            )
        else:
            self.history_window.add_entry(
                speaker=speaker_name,
                original=combined_orig,
                traducao=combined_trad
            )

        self.last_confirmed_original = combined_orig
        self.last_confirmed_speaker = speaker_name

    def paintEvent(self, event):
        if not self.texts_to_draw:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        mon_w = self.width()
        mon_h = self.height()

        # Separa locutor e diálogo
        speaker_items = [it for it in self.texts_to_draw if it.get('is_name')]
        dialogue_items = [it for it in self.texts_to_draw if not it.get('is_name')]

        # Se houver apenas speaker sem diálogo, trata o item como diálogo
        if not dialogue_items and speaker_items:
            dialogue_items = speaker_items
            speaker_items = []

        # =========================================================================
        # 1. PARTE 1: NOME DO PERSONAGEM (Item Independente no seu próprio local)
        # =========================================================================
        if speaker_items:
            sp_item = speaker_items[0]
            sp_orig = sp_item.get('original', '').strip()
            sp_trad = sp_item.get('traducao', '').strip() or sp_orig
            sp_box = sp_item.get('box')

            # Verifica se contém japonês
            import re
            has_jp = bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]', sp_orig))
            is_already_translated = not has_jp or (sp_orig.lower() == sp_trad.lower())

            # Só renderiza a tarja de nome se o original era em japonês e precisou de tradução.
            # Se o jogo já exibia o nome em alfabeto latino/inglês, não cobre desnecessariamente!
            if not is_already_translated and sp_trad and sp_box and len(sp_box) >= 3:
                name_x1 = int(sp_box[0][0])
                name_y1 = int(sp_box[0][1])
                name_x2 = int(sp_box[2][0])
                name_y2 = int(sp_box[2][1])

                font_name = QFont("Segoe UI", 11, QFont.Weight.Bold)
                fm_name = QFontMetrics(font_name)
                name_text_w = fm_name.horizontalAdvance(sp_trad)

                pad_nx = 10
                pad_ny = 4
                name_card_w = max(name_x2 - name_x1 + (pad_nx * 2), name_text_w + (pad_nx * 2))
                name_card_h = max(name_y2 - name_y1 + (pad_ny * 2), 26)

                name_card_x = max(10, min(name_x1 - pad_nx, mon_w - name_card_w - 10))
                name_card_y = max(10, min(name_y1 - pad_ny, mon_h - name_card_h - 10))
                name_rect = QRectF(name_card_x, name_card_y, name_card_w, name_card_h)

                # Tarja independente do locutor (Estilo Badge Âmbar / Dark Slate)
                painter.setPen(QPen(QColor(245, 158, 11, 200), 1.5))
                painter.setBrush(QColor(15, 23, 42, 230))
                painter.drawRoundedRect(name_rect, 6.0, 6.0)

                painter.setFont(font_name)
                painter.setPen(QColor(251, 191, 36)) # Dourado/Âmbar
                painter.drawText(name_rect, int(Qt.AlignmentFlag.AlignCenter), sp_trad)

        # =========================================================================
        # 2. PARTE 2: TEXTO DO DIÁLOGO (Posicionado EXATAMENTE sobre o texto original)
        # =========================================================================
        if not dialogue_items:
            return

        combined_trad = " ".join(it.get('traducao', '').strip() for it in dialogue_items if it.get('traducao'))
        if not combined_trad:
            return

        is_preliminary = "[Traduzindo com IA...]" in combined_trad

        # Localização exata da caixa original na tela
        first_box = dialogue_items[0].get('box')
        if first_box and len(first_box) >= 3:
            orig_x1 = int(first_box[0][0])
            orig_y1 = int(first_box[0][1])
            orig_x2 = int(first_box[2][0])
            orig_y2 = int(first_box[2][1])
        else:
            orig_x1 = int(mon_w * 0.15)
            orig_x2 = int(mon_w * 0.85)
            orig_y1 = int(mon_h * 0.72)
            orig_y2 = int(mon_h * 0.85)

        orig_w = max(20, orig_x2 - orig_x1)
        orig_h = max(20, orig_y2 - orig_y1)

        # Configura tipografia do diálogo
        font_dialogue = QFont("Segoe UI", 13, QFont.Weight.Bold)
        fm = QFontMetrics(font_dialogue)

        pad_x = 12
        pad_y = 8

        # A largura parte da largura original do texto na tela, garantindo no mínimo 340px
        card_w = max(orig_w + (pad_x * 2), 340)
        card_w = min(card_w, mon_w - 40)
        text_w = card_w - (pad_x * 2)

        # Mede a altura necessária para quebrar as linhas confortavelmente sem truncar
        bounding_text_rect = fm.boundingRect(
            0, 0, text_w, 2000,
            int(Qt.AlignmentFlag.AlignLeft) | int(Qt.TextFlag.TextWordWrap),
            combined_trad
        )
        text_h = max(22, bounding_text_rect.height())
        card_h = max(orig_h + (pad_y * 2), text_h + (pad_y * 2))

        # Posicionamento fiel: alinha diretamente na coordenada original (orig_x1, orig_y1)
        card_x = orig_x1 - pad_x
        card_y = orig_y1 - pad_y

        # Garante que a tarja não vaze para fora dos limites do monitor
        if card_x + card_w > mon_w - 15:
            card_x = mon_w - card_w - 15
        if card_x < 15:
            card_x = 15

        if card_y + card_h > mon_h - 15:
            card_y = mon_h - card_h - 15
        if card_y < 15:
            card_y = 15

        card_rect = QRectF(card_x, card_y, card_w, card_h)

        # Fundo elegante Dark Slate com transparência
        painter.setPen(QPen(QColor(56, 189, 248, 140), 1.5))
        painter.setBrush(QColor(15, 23, 42, 225))
        painter.drawRoundedRect(card_rect, 8.0, 8.0)

        # Fala traduzida (alinhada exatamente na posição original)
        dialogue_rect = QRectF(card_x + pad_x, card_y + pad_y, text_w, text_h + 4)
        painter.setFont(font_dialogue)

        # Leve sombra de texto
        shadow_rect = QRectF(dialogue_rect.x() + 1, dialogue_rect.y() + 1, dialogue_rect.width(), dialogue_rect.height())
        painter.setPen(QColor(0, 0, 0, 180))
        painter.drawText(
            shadow_rect, 
            int(Qt.AlignmentFlag.AlignLeft) | int(Qt.TextFlag.TextWordWrap), 
            combined_trad
        )

        # Texto principal
        text_color = QColor(148, 163, 184) if is_preliminary else QColor(248, 250, 252)
        painter.setPen(text_color)
        painter.drawText(
            dialogue_rect, 
            int(Qt.AlignmentFlag.AlignLeft) | int(Qt.TextFlag.TextWordWrap), 
            combined_trad
        )
