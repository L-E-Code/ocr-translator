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
    QPainter, QColor, QFont, QFontMetricsF, QLinearGradient, QPen
)

import config_manager
from logger_config import get_logger

logger = get_logger("Overlay")

PLACEHOLDER = "[Translating with AI...]"
JP_RE = re.compile(r'[぀-ゟ゠-ヿ一-龯]')

FONT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Arial"]

# Palette (dark glass with cyan/violet accent; speaker in amber)
BG_TOP = QColor(20, 27, 45, 240)
BG_BOTTOM = QColor(12, 17, 31, 240)
EDGE = QColor(255, 255, 255, 38)
ACCENT_A = QColor(56, 189, 248)
ACCENT_B = QColor(139, 125, 250)
SPEAKER = QColor(251, 191, 36)
TEXT = QColor(244, 247, 252)

CARD_RADIUS = 12.0
SHADOW_MARGIN = 28

# Animation timings (s)
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
    """Computed layout of one overlay frame (target positions, before the animation)."""
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
    Transparent window of Ghost Mode (HUD Overlay).
    Draws the translation over the screen with native capture exclusion via Win32
    (invisible to OCR and recorders), smooth animations and two styles:
      - 'inplace':  card over the text's original box (covers the original)
      - 'subtitle': subtitle bar centered at the bottom of the screen
    Configurable in config.json: overlay_mode and overlay_opacity.
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

        # Animation state
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

        # When the screen has no more dialogue, fades the overlay out after a moment
        self.auto_clear_timer = QTimer(self)
        self.auto_clear_timer.setSingleShot(True)
        self.auto_clear_timer.timeout.connect(self._clear_texts)

        self.initUI()
        self.apply_capture_exclusion()

    # ------------------------------------------------------------------
    # Window
    # ------------------------------------------------------------------
    def initUI(self):
        # Borderless, always on top, no taskbar icon and click-through
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # Covers exactly the chosen monitor
        self.setGeometry(
            self.monitor_region['left'],
            self.monitor_region['top'],
            self.monitor_region['width'],
            self.monitor_region['height']
        )

    def apply_capture_exclusion(self):
        """
        Applies WDA_EXCLUDEFROMCAPTURE (0x00000011) via the Win32 API: the window is visible to the
        user but invisible to capture (MSS, BitBlt, OBS, print screen).
        This keeps OCR from reading the translation itself.
        """
        if sys.platform != "win32":
            return

        try:
            hwnd = int(self.winId())
            WDA_EXCLUDEFROMCAPTURE = 0x00000011
            res = ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
            if res:
                logger.info("Screen capture exclusion (SetWindowDisplayAffinity) enabled successfully.")
            else:
                err = ctypes.GetLastError()
                logger.warning(f"SetWindowDisplayAffinity returned 0 (Win32 code: {err}).")
        except Exception as e:
            logger.error(f"Failed to configure capture exclusion on the Overlay: {e}")

    def showEvent(self, event):
        super().showEvent(event)
        # Re-applies the capture exclusion on show, to make sure it is bound to the active HWND
        self.apply_capture_exclusion()

    def closeEvent(self, event):
        self._tick.stop()
        self.auto_clear_timer.stop()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Data input
    # ------------------------------------------------------------------
    def update_texts(self, new_texts):
        """
        Receives the list of translated items and updates the overlay.
        Also sends them to the translation history, if available.
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
            # First display: appears in place, without sliding
            self._rect_cur = QRectF(scene.card)
            self._text_alpha = 0.0 if not scene.loading else 1.0
        elif previous.text != scene.text and not scene.loading:
            # New text: enters with a fade
            self._text_alpha = 0.0

        self._alpha_target = 1.0
        self._start_anim()

    def _clear_texts(self):
        """Starts the fade-out; the scene is discarded when the opacity reaches zero."""
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
        combined_trans = " ".join(item['translation'].strip() for item in dialogue_items if item.get('translation'))

        if not combined_orig or not combined_trans or PLACEHOLDER in combined_trans:
            return

        similarity = 0.0
        if self.last_confirmed_original:
            similarity = SequenceMatcher(None, combined_orig, self.last_confirmed_original).ratio()

        if similarity >= 0.70:
            self.history_window.update_last_entry(
                speaker=speaker_name or self.last_confirmed_speaker,
                original=combined_orig,
                translation=combined_trans
            )
        else:
            self.history_window.add_entry(
                speaker=speaker_name,
                original=combined_orig,
                translation=combined_trans
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
        """Largest font (between max_pt and min_pt) whose wrapped text fits in budget_h."""
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
        # Speaker only, no dialogue: treats the item as dialogue
        if not dialogue and speakers:
            dialogue, speakers = speakers, []

        translated = [it.get('translation', '').strip() for it in dialogue if it.get('translation')]
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
        inset_left = 8.0  # space for the accent bar

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
            # Covers the original box and centers the card on it
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
        trans = sp.get('translation', '').strip() or orig
        if not trans:
            return None
        loading = trans == PLACEHOLDER
        label = "···" if loading else trans

        # In in-place mode, a name the game already shows in Latin letters does not need to be covered
        if self.mode == "inplace" and not loading:
            if not JP_RE.search(orig) or orig.lower() == trans.lower():
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
            # Tab over the card's top-left corner
            x = card.left() + 14.0
            y = card.top() - chip_h + 6.0

        x = min(max(x, 10.0), mon_w - chip_w - 10.0)
        y = min(max(y, 10.0), mon_h - chip_h - 10.0)
        return _Chip(QRectF(x, y, chip_w, chip_h), label, loading)

    # ------------------------------------------------------------------
    # Animation
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
            # Slides the card to the target position
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

            # Card opacity
            if self._alpha < self._alpha_target:
                self._alpha = min(self._alpha_target, self._alpha + dt / FADE_IN)
            elif self._alpha > self._alpha_target:
                self._alpha = max(self._alpha_target, self._alpha - dt / FADE_OUT)
            if self._alpha != self._alpha_target:
                busy = True

            # Text enters with a fade
            if self._text_alpha < 1.0:
                self._text_alpha = min(1.0, self._text_alpha + dt / TEXT_FADE)
                busy = True

            # Loading skeleton glow
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
        """Rectangle that contains everything the overlay draws right now (card + tab + shadow)."""
        if self._scene is None or self._rect_cur is None:
            return QRectF()
        rect = QRectF(self._rect_cur)
        if self._scene.chip:
            rect = rect.united(self._scene.chip.rect)
        return rect.adjusted(-SHADOW_MARGIN, -SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN + 6)

    def _invalidate(self):
        """Repaints only the affected area (the window covers the whole monitor)."""
        area = self._dirty.united(self._bounds())
        self._dirty = self._bounds()
        if not area.isNull():
            self.update(area.toAlignedRect())

    # ------------------------------------------------------------------
    # Painting
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
            # The text is positioned relative to the current card so it does not "shake" during the slide
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

        # Soft layered shadow
        opacity = painter.opacity()
        for grow, alpha in ((16, 7), (11, 11), (7, 16), (3, 24)):
            painter.setOpacity(opacity * alpha / 255.0 * 4.0)
            painter.setBrush(QColor(0, 0, 0))
            painter.drawRoundedRect(rect.adjusted(-grow, -grow + 4, grow, grow + 4),
                                    CARD_RADIUS + grow, CARD_RADIUS + grow)
        painter.setOpacity(opacity)

        # Dark glass body
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
        """Pulsing gray lines while the translation has not arrived."""
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
