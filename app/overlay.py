import re
import sys
import math
import time
import ctypes
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRectF, QTimer
from PyQt6.QtGui import (
    QPainter, QColor, QFont, QFontMetricsF, QLinearGradient, QPen, QPainterPath
)

import config_manager
from logger_config import get_logger

logger = get_logger("Overlay")

PLACEHOLDER = "[Traduzindo com IA...]"
JP_RE = re.compile(r'[぀-ゟ゠-ヿ一-龯]')

FONT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Arial"]

# Paleta (vidro escuro com acento ciano/violeta; locutor em âmbar)
BG_TOP = QColor(20, 27, 45, 240)
BG_BOTTOM = QColor(12, 17, 31, 240)
EDGE = QColor(255, 255, 255, 38)
ACCENT_A = QColor(56, 189, 248)
ACCENT_B = QColor(139, 125, 250)
SPEAKER = QColor(251, 191, 36)
TEXT = QColor(244, 247, 252)

CARD_RADIUS = 12.0
SHADOW_MARGIN = 28

# Tempos de animação (s)
FADE_IN = 0.16
FADE_OUT = 0.28
TEXT_FADE = 0.14
MORPH_RATE = 18.0
SHIMMER_PERIOD = 1.3
CLEAR_DELAY_MS = 1500


@dataclass
class _Chip:
    rect: QRectF
    text: str
    loading: bool


@dataclass
class _Scene:
    """Layout calculado de um quadro do overlay (posições-alvo, antes da animação)."""
    card: QRectF
    text_rect: QRectF
    text: str
    font: QFont
    flags: int
    loading: bool
    skeleton_lines: int
    chip: Optional[_Chip]


class OverlayWindow(QWidget):
    """
    Janela transparente do Modo Fantasma (HUD Overlay).
    Desenha a tradução sobre a tela com exclusão nativa de captura via Win32
    (invisível ao OCR e a gravadores), animações suaves e dois estilos:
      - 'inplace':  cartão sobre a caixa original do texto (cobre o original)
      - 'subtitle': barra de legenda centralizada na parte inferior da tela
    Configurável em config.json: overlay_mode e overlay_opacity.
    """
    def __init__(self, monitor_region, history_window=None):
        super().__init__()
        self.monitor_region = monitor_region
        self.history_window = history_window

        self.last_confirmed_original = ""
        self.last_confirmed_speaker = ""

        cfg = config_manager.load_config()
        self.mode = cfg.get("overlay_mode", "inplace")
        if self.mode not in ("inplace", "subtitle"):
            self.mode = "inplace"
        try:
            self.global_opacity = min(1.0, max(0.3, float(cfg.get("overlay_opacity", 1.0))))
        except (TypeError, ValueError):
            self.global_opacity = 1.0

        # Estado de animação
        self._scene: Optional[_Scene] = None
        self._rect_cur: Optional[QRectF] = None
        self._alpha = 0.0
        self._alpha_target = 0.0
        self._text_alpha = 1.0
        self._phase = 0.0
        self._dirty = QRectF()
        self._last_tick = 0.0

        self._tick = QTimer(self)
        self._tick.setInterval(16)
        self._tick.timeout.connect(self._on_tick)

        # Quando a tela não tem mais diálogo, esmaece o overlay após um instante
        self.auto_clear_timer = QTimer(self)
        self.auto_clear_timer.setSingleShot(True)
        self.auto_clear_timer.timeout.connect(self._clear_texts)

        self.initUI()
        self.apply_capture_exclusion()

    # ------------------------------------------------------------------
    # Janela
    # ------------------------------------------------------------------
    def initUI(self):
        # Sem borda, sempre no topo, sem ícone na barra de tarefas e transparente a cliques
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # Cobre exatamente o monitor escolhido
        self.setGeometry(
            self.monitor_region['left'],
            self.monitor_region['top'],
            self.monitor_region['width'],
            self.monitor_region['height']
        )

    def apply_capture_exclusion(self):
        """
        Aplica WDA_EXCLUDEFROMCAPTURE (0x00000011) via Win32 API: a janela aparece para o
        usuário, mas fica invisível para captura (MSS, BitBlt, OBS, print screen).
        Isso impede que o OCR leia a própria tradução.
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
        # Re-aplica a exclusão de captura ao exibir, para garantir vínculo com o HWND ativo
        self.apply_capture_exclusion()

    def closeEvent(self, event):
        self._tick.stop()
        self.auto_clear_timer.stop()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Entrada de dados
    # ------------------------------------------------------------------
    def update_texts(self, new_texts):
        """
        Recebe a lista de itens traduzidos e atualiza o overlay.
        Também envia para o histórico de traduções, se disponível.
        """
        if not new_texts:
            if not self.auto_clear_timer.isActive() and self._scene is not None:
                self.auto_clear_timer.start(CLEAR_DELAY_MS)
            return

        self.auto_clear_timer.stop()

        scene = self._build_scene(new_texts)
        if scene is not None:
            self._apply_scene(scene)

        self._record_to_history(new_texts)

    def _apply_scene(self, scene):
        previous = self._scene
        self._scene = scene

        if self._rect_cur is None or previous is None:
            # Primeira exibição: nasce no lugar, sem deslizar
            self._rect_cur = QRectF(scene.card)
            self._text_alpha = 0.0 if not scene.loading else 1.0
        elif previous.text != scene.text and not scene.loading:
            # Texto novo: entra com fade
            self._text_alpha = 0.0

        self._alpha_target = 1.0
        self._start_anim()

    def _clear_texts(self):
        """Inicia o esmaecimento; a cena é descartada quando a opacidade chega a zero."""
        if self._scene is not None:
            self._alpha_target = 0.0
            self._start_anim()

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

        if not combined_orig or not combined_trad or PLACEHOLDER in combined_trad:
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

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    @staticmethod
    def _make_font(pt, weight=QFont.Weight.DemiBold):
        font = QFont()
        font.setFamilies(FONT_FAMILIES)
        font.setPointSizeF(float(pt))
        font.setWeight(weight)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        return font

    def _fit_text(self, text, width, budget_h, max_pt, min_pt, flags):
        """Maior fonte (entre max_pt e min_pt) cujo texto quebrado cabe em budget_h."""
        height = 0.0
        font = self._make_font(min_pt)
        for pt in range(max_pt, min_pt - 1, -1):
            font = self._make_font(pt)
            height = QFontMetricsF(font).boundingRect(QRectF(0, 0, width, 10000), flags, text).height()
            if height <= budget_h:
                break
        return font, height

    @staticmethod
    def _union_box(items):
        xs, ys = [], []
        for it in items:
            for pt in (it.get('box') or []):
                xs.append(pt[0])
                ys.append(pt[1])
        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)

    def _build_scene(self, items):
        mon_w, mon_h = self.width(), self.height()

        speakers = [it for it in items if it.get('is_name')]
        dialogue = [it for it in items if not it.get('is_name')]
        # Só locutor sem diálogo: trata o item como diálogo
        if not dialogue and speakers:
            dialogue, speakers = speakers, []

        translated = [it.get('traducao', '').strip() for it in dialogue if it.get('traducao')]
        if not translated:
            return None
        text = " ".join(translated)
        loading = PLACEHOLDER in text

        box = self._union_box(dialogue)
        if box is None:
            box = (mon_w * 0.15, mon_h * 0.72, mon_w * 0.85, mon_h * 0.85)
        ox1, oy1, ox2, oy2 = box
        orig_w = max(20.0, ox2 - ox1)
        orig_h = max(20.0, oy2 - oy1)

        pad_x, pad_y = 20.0, 12.0
        inset_left = 8.0  # espaço da barra de acento

        if self.mode == "subtitle":
            flags = int(Qt.AlignmentFlag.AlignHCenter) | int(Qt.AlignmentFlag.AlignVCenter) | int(Qt.TextFlag.TextWordWrap)
            card_w = min(mon_w * 0.74, mon_w - 80)
            text_w = card_w - 2 * pad_x - inset_left
            font, text_h = self._fit_text(text, text_w, 3.2 * 30, 22, 14, flags)
            card_h = max(text_h + 2 * pad_y, 52.0)
            card_x = (mon_w - card_w) / 2
            card_y = mon_h * 0.93 - card_h
            lines = 2
        else:
            flags = int(Qt.AlignmentFlag.AlignLeft) | int(Qt.AlignmentFlag.AlignVCenter) | int(Qt.TextFlag.TextWordWrap)
            card_w = min(max(orig_w + 2 * pad_x, 380.0), mon_w - 48)
            text_w = card_w - 2 * pad_x - inset_left
            budget = max(orig_h * 1.35, 56.0)
            font, text_h = self._fit_text(text, text_w, budget, 20, 12, flags)
            # Cobre a caixa original e centraliza o cartão nela
            card_h = max(text_h + 2 * pad_y, orig_h + 10)
            card_x = ox1 - pad_x
            card_y = (oy1 + oy2) / 2 - card_h / 2
            line_h = QFontMetricsF(font).lineSpacing()
            lines = max(1, min(3, round(orig_h / max(line_h, 1.0))))

        margin = 16.0
        card_x = min(max(card_x, margin), mon_w - card_w - margin)
        card_y = min(max(card_y, margin), mon_h - card_h - margin)
        card = QRectF(card_x, card_y, card_w, card_h)
        text_rect = QRectF(card_x + pad_x + inset_left, card_y + pad_y, text_w, card_h - 2 * pad_y)

        chip = self._build_chip(speakers, card, mon_w, mon_h)
        return _Scene(card, text_rect, text, font, flags, loading, lines, chip)

    def _build_chip(self, speakers, card, mon_w, mon_h):
        if not speakers:
            return None
        sp = speakers[0]
        orig = sp.get('original', '').strip()
        trad = sp.get('traducao', '').strip() or orig
        if not trad:
            return None
        loading = trad == PLACEHOLDER
        label = "···" if loading else trad

        # No modo in-place, o nome que o jogo já mostra em alfabeto latino não precisa ser coberto
        if self.mode == "inplace" and not loading:
            if not JP_RE.search(orig) or orig.lower() == trad.lower():
                return None

        fm = QFontMetricsF(self._make_font(10.5, QFont.Weight.Bold))
        text_w = fm.horizontalAdvance(label)
        chip_h = 28.0
        chip_w = text_w + 30.0

        box = self._union_box([sp])
        if self.mode == "inplace" and box is not None:
            x1, y1, x2, y2 = box
            chip_w = max(chip_w, x2 - x1 + 20.0)
            chip_h = max(chip_h, y2 - y1 + 8.0)
            x = x1 - 10.0
            y = (y1 + y2) / 2 - chip_h / 2
        else:
            # Aba sobre o canto superior esquerdo do cartão
            x = card.left() + 14.0
            y = card.top() - chip_h + 6.0

        x = min(max(x, 10.0), mon_w - chip_w - 10.0)
        y = min(max(y, 10.0), mon_h - chip_h - 10.0)
        return _Chip(QRectF(x, y, chip_w, chip_h), label, loading)

    # ------------------------------------------------------------------
    # Animação
    # ------------------------------------------------------------------
    def _start_anim(self):
        if not self._tick.isActive():
            self._last_tick = time.perf_counter()
            self._tick.start()
        self._invalidate()

    def _on_tick(self):
        now = time.perf_counter()
        dt = min(0.05, now - self._last_tick)
        self._last_tick = now
        busy = False

        scene = self._scene
        if scene is not None:
            # Desliza o cartão até a posição-alvo
            cur, tgt = self._rect_cur, scene.card
            k = 1.0 - math.exp(-dt * MORPH_RATE)
            nxt = QRectF(
                cur.x() + (tgt.x() - cur.x()) * k,
                cur.y() + (tgt.y() - cur.y()) * k,
                cur.width() + (tgt.width() - cur.width()) * k,
                cur.height() + (tgt.height() - cur.height()) * k,
            )
            delta = max(abs(nxt.x() - tgt.x()), abs(nxt.y() - tgt.y()),
                        abs(nxt.width() - tgt.width()), abs(nxt.height() - tgt.height()))
            if delta < 0.4:
                nxt = QRectF(tgt)
            else:
                busy = True
            self._rect_cur = nxt

            # Opacidade do cartão
            if self._alpha < self._alpha_target:
                self._alpha = min(self._alpha_target, self._alpha + dt / FADE_IN)
            elif self._alpha > self._alpha_target:
                self._alpha = max(self._alpha_target, self._alpha - dt / FADE_OUT)
            if self._alpha != self._alpha_target:
                busy = True

            # Texto entra com fade
            if self._text_alpha < 1.0:
                self._text_alpha = min(1.0, self._text_alpha + dt / TEXT_FADE)
                busy = True

            # Brilho do esqueleto de carregamento
            if scene.loading:
                self._phase = (self._phase + dt / SHIMMER_PERIOD) % 1.0
                busy = True

            if self._alpha <= 0.0 and self._alpha_target <= 0.0:
                self._invalidate()
                self._scene = None
                self._rect_cur = None
                busy = False

        self._invalidate()
        if not busy:
            self._tick.stop()

    def _bounds(self):
        """Retângulo que contém tudo que o overlay desenha agora (cartão + aba + sombra)."""
        if self._scene is None or self._rect_cur is None:
            return QRectF()
        rect = QRectF(self._rect_cur)
        if self._scene.chip:
            rect = rect.united(self._scene.chip.rect)
        return rect.adjusted(-SHADOW_MARGIN, -SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN + 6)

    def _invalidate(self):
        """Repinta só a área afetada (a janela cobre o monitor inteiro)."""
        area = self._dirty.united(self._bounds())
        self._dirty = self._bounds()
        if not area.isNull():
            self.update(area.toAlignedRect())

    # ------------------------------------------------------------------
    # Pintura
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        scene = self._scene
        if scene is None or self._rect_cur is None or self._alpha <= 0.0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        base = self._alpha * self.global_opacity
        card = self._rect_cur

        painter.setOpacity(base)
        self._draw_panel(painter, card, with_accent=True)

        if scene.loading:
            self._draw_skeleton(painter, card, scene)
        else:
            # O texto é posicionado em relação ao cartão atual para não "tremer" durante o deslize
            shift = card.center() - scene.card.center()
            text_rect = scene.text_rect.translated(shift)
            painter.setFont(scene.font)
            painter.setOpacity(base * self._text_alpha)
            painter.setPen(QColor(0, 0, 0, 150))
            painter.drawText(text_rect.translated(0, 1.2), scene.flags, scene.text)
            painter.setPen(TEXT)
            painter.drawText(text_rect, scene.flags, scene.text)

        if scene.chip:
            painter.setOpacity(base)
            self._draw_chip(painter, scene.chip)

        painter.end()

    def _draw_panel(self, painter, rect, with_accent):
        painter.setPen(Qt.PenStyle.NoPen)

        # Sombra suave em camadas
        opacity = painter.opacity()
        for grow, alpha in ((16, 7), (11, 11), (7, 16), (3, 24)):
            painter.setOpacity(opacity * alpha / 255.0 * 4.0)
            painter.setBrush(QColor(0, 0, 0))
            painter.drawRoundedRect(rect.adjusted(-grow, -grow + 4, grow, grow + 4),
                                    CARD_RADIUS + grow, CARD_RADIUS + grow)
        painter.setOpacity(opacity)

        # Corpo em vidro escuro
        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        grad.setColorAt(0.0, BG_TOP)
        grad.setColorAt(1.0, BG_BOTTOM)
        painter.setBrush(grad)
        painter.setPen(QPen(EDGE, 1.0))
        painter.drawRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)

        if with_accent:
            painter.setPen(Qt.PenStyle.NoPen)
            bar = QRectF(rect.left() + 9, rect.top() + 11, 3.5, max(8.0, rect.height() - 22))
            accent = QLinearGradient(bar.topLeft(), bar.bottomLeft())
            accent.setColorAt(0.0, ACCENT_A)
            accent.setColorAt(1.0, ACCENT_B)
            painter.setBrush(accent)
            painter.drawRoundedRect(bar, 1.75, 1.75)

    def _draw_skeleton(self, painter, card, scene):
        """Linhas cinzas pulsantes enquanto a tradução não chega."""
        shift = card.center() - scene.card.center()
        area = scene.text_rect.translated(shift)
        lines = scene.skeleton_lines
        bar_h = 9.0
        gap = 11.0
        total = lines * bar_h + (lines - 1) * gap
        top = area.center().y() - total / 2
        widths = [1.0, 0.72, 0.5]

        painter.setPen(Qt.PenStyle.NoPen)
        span = area.width()
        center_x = area.left() + (self._phase * 1.6 - 0.3) * span
        for i in range(lines):
            w = area.width() * widths[i % len(widths)]
            bar = QRectF(area.left(), top + i * (bar_h + gap), w, bar_h)
            grad = QLinearGradient(center_x - span * 0.25, 0, center_x + span * 0.25, 0)
            grad.setColorAt(0.0, QColor(148, 163, 184, 55))
            grad.setColorAt(0.5, QColor(186, 230, 253, 150))
            grad.setColorAt(1.0, QColor(148, 163, 184, 55))
            painter.setBrush(grad)
            painter.drawRoundedRect(bar, bar_h / 2, bar_h / 2)

    def _draw_chip(self, painter, chip):
        rect = chip.rect
        opacity = painter.opacity()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setOpacity(opacity * 0.35)
        painter.setBrush(QColor(0, 0, 0))
        painter.drawRoundedRect(rect.adjusted(-3, -1, 3, 5), 10, 10)
        painter.setOpacity(opacity)

        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        grad.setColorAt(0.0, QColor(38, 30, 14, 245))
        grad.setColorAt(1.0, QColor(24, 19, 9, 245))
        painter.setBrush(grad)
        painter.setPen(QPen(QColor(SPEAKER.red(), SPEAKER.green(), SPEAKER.blue(), 170), 1.2))
        painter.drawRoundedRect(rect, rect.height() / 2.2, rect.height() / 2.2)

        painter.setFont(self._make_font(10.5, QFont.Weight.Bold))
        painter.setPen(SPEAKER)
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), chip.text)
