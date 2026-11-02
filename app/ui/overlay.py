import sys
from functools import partial
import math
import time
import ctypes

from difflib import SequenceMatcher
from typing import Optional

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRectF, QTimer
from PyQt6.QtGui import QPainter, QColor

from core import config_manager
from core.logger_config import get_logger
from ui import card_render
from ui.card_render import PLACEHOLDER, TEXT, SHADOW_MARGIN

logger = get_logger("Overlay")

# Animation timings (s)
FADE_IN = 0.16
FADE_OUT = 0.28
TEXT_FADE = 0.14
MORPH_RATE = 18.0
SHIMMER_PERIOD = 1.3
CLEAR_DELAY_MS = 1500


class _View:
    """Animation state of the card of one capture region."""
    def __init__(self, parent, on_timeout):
        self.scene: Optional[card_render.Scene] = None
        self.rect_cur: Optional[QRectF] = None
        self.alpha = 0.0
        self.alpha_target = 0.0
        self.text_alpha = 1.0
        self.dirty = QRectF()
        # When the region has no more dialogue, fades the card out after a moment
        self.clear_timer = QTimer(parent)
        self.clear_timer.setSingleShot(True)
        self.clear_timer.timeout.connect(on_timeout)

    def bounds(self):
        """Rectangle that contains everything the view draws right now (card + tab + shadow)."""
        if self.scene is None or self.rect_cur is None:
            return QRectF()
        rect = QRectF(self.rect_cur)
        if self.scene.chip:
            rect = rect.united(self.scene.chip.rect)
        return rect.adjusted(-SHADOW_MARGIN, -SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN + 6)


class OverlayWindow(QWidget):
    """
    Transparent window of Ghost Mode (HUD Overlay).
    Draws the translation over the screen with native capture exclusion via Win32
    (invisible to OCR and recorders) and smooth animations. Each card goes over the text's
    original box (covers the original); with several capture regions, each one gets its own card.
    Configurable in config.json: overlay_opacity and overlay_padding.
    """
    def __init__(self, monitor_region, history_window=None):
        super().__init__()
        self.monitor_region = monitor_region
        self.history_window = history_window

        self.confirmed = {}  # region -> (last confirmed line, speaker)
        self.last_region_in_history = None

        cfg = config_manager.load_config()
        try:
            self.global_opacity = min(1.0, max(0.3, float(cfg.get("overlay_opacity", 1.0))))
        except (TypeError, ValueError):
            self.global_opacity = 1.0
        text_color = QColor(str(cfg.get("overlay_text_color", "")))
        self.text_color = text_color if text_color.isValid() else QColor(TEXT)
        try:
            self.pad_x = float(min(40, max(0, int(cfg.get("overlay_padding", 20)))))
        except (TypeError, ValueError):
            self.pad_x = 20.0

        # Animation state: one view per capture region (the single region uses the None key)
        self._views = {}
        self._phase = 0.0
        self._last_tick = 0.0

        self._tick = QTimer(self)
        self._tick.setInterval(16)
        self._tick.timeout.connect(self._on_tick)

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
        for view in self._views.values():
            view.clear_timer.stop()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Data input
    # ------------------------------------------------------------------
    def _view(self, region, index=0):
        view = self._views.get((region, index))
        if view is None:
            view = _View(self, partial(self.clear_region, region, True))
            self._views[(region, index)] = view
        return view

    def _region_views(self, region):
        return [(key, v) for key, v in self._views.items() if key[0] == region]

    def _build_scenes(self, items):
        """One scene per block of text (menus, buttons); a single scene for a plain dialogue."""
        return card_render.build_scenes(items, self.width(), self.height(), self.pad_x)

    def update_texts(self, new_texts):
        """
        Receives the list of translated items (preliminary or final) and updates the card of each region
        they belong to. Also sends them to the translation history, if available.
        """
        if not new_texts:
            return

        groups = {}
        for item in new_texts:
            groups.setdefault(item.get('region'), []).append(item)

        for region, items in groups.items():
            for _, view in self._region_views(region):
                view.clear_timer.stop()
            scenes = self._build_scenes(items)
            for i, scene in enumerate(scenes):
                self._apply_scene(self._view(region, i), scene)
            # Cards from an earlier reading that no longer have a block fade out
            for (_, index), view in self._region_views(region):
                if index >= len(scenes) and view.scene is not None:
                    view.alpha_target = 0.0
            self._start_anim()
            self._record_to_history(region, items)

    def _apply_scene(self, view, scene):
        previous = view.scene
        view.scene = scene

        if view.rect_cur is None or previous is None:
            # First display: appears in place, without sliding
            view.rect_cur = QRectF(scene.card)
            view.text_alpha = 0.0 if not scene.loading else 1.0
        elif previous.text != scene.text and not scene.loading:
            # New text: enters with a fade
            view.text_alpha = 0.0

        view.alpha_target = 1.0
        self._start_anim()

    def clear_region(self, region, now=False):
        """The region has no more dialogue: its card fades out after a moment (or right away with now=True)."""
        for _, view in self._region_views(region):
            if view.scene is None:
                continue
            if now:
                view.alpha_target = 0.0
            elif not view.clear_timer.isActive():
                view.clear_timer.start(CLEAR_DELAY_MS)
        if now:
            self._start_anim()

    def _clear_texts(self):
        """Starts the fade-out of every card; each scene is discarded when its opacity reaches zero."""
        for region in {key[0] for key in self._views}:
            self.clear_region(region, now=True)

    def _record_to_history(self, region, items):
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

        last_original, last_speaker = self.confirmed.get(region, ("", ""))
        similarity = 0.0
        if last_original:
            similarity = SequenceMatcher(None, combined_orig, last_original).ratio()

        # Continuation of the same line, as long as the last history entry still belongs to this region
        if similarity >= 0.70 and self.last_region_in_history == region:
            self.history_window.update_last_entry(
                speaker=speaker_name or last_speaker,
                original=combined_orig,
                translation=combined_trans
            )
        else:
            self.history_window.add_entry(
                speaker=speaker_name,
                original=combined_orig,
                translation=combined_trans
            )

        self.confirmed[region] = (combined_orig, speaker_name)
        self.last_region_in_history = region

    # ------------------------------------------------------------------
    # Animation
    # ------------------------------------------------------------------
    def _start_anim(self):
        if not self._tick.isActive():
            self._last_tick = time.perf_counter()
            self._tick.start()
        for view in self._views.values():
            self._invalidate(view)

    def _on_tick(self):
        now = time.perf_counter()
        dt = min(0.05, now - self._last_tick)
        self._last_tick = now
        busy = False
        shimmer = False

        for view in self._views.values():
            scene = view.scene
            if scene is None:
                continue

            # Slides the card to the target position
            cur, tgt = view.rect_cur, scene.card
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
            view.rect_cur = nxt

            # Card opacity
            if view.alpha < view.alpha_target:
                view.alpha = min(view.alpha_target, view.alpha + dt / FADE_IN)
            elif view.alpha > view.alpha_target:
                view.alpha = max(view.alpha_target, view.alpha - dt / FADE_OUT)
            if view.alpha != view.alpha_target:
                busy = True

            # Text enters with a fade
            if view.text_alpha < 1.0:
                view.text_alpha = min(1.0, view.text_alpha + dt / TEXT_FADE)
                busy = True

            # Loading skeleton glow
            if scene.loading:
                shimmer = True
                busy = True

            self._invalidate(view)
            if view.alpha <= 0.0 and view.alpha_target <= 0.0:
                view.scene = None
                view.rect_cur = None
                self._invalidate(view)

        if shimmer:
            self._phase = (self._phase + dt / SHIMMER_PERIOD) % 1.0
        if not busy:
            self._tick.stop()

    def _invalidate(self, view):
        """Repaints only the affected area (the window covers the whole monitor)."""
        bounds = view.bounds()
        area = view.dirty.united(bounds)
        view.dirty = bounds
        if not area.isNull():
            self.update(area.toAlignedRect())

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        views = [v for v in self._views.values() if v.scene is not None and v.rect_cur is not None and v.alpha > 0.0]
        if not views:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        for view in views:
            self._paint_view(painter, view)
        painter.end()

    def _paint_view(self, painter, view):
        # The fade animation is `alpha`; the opacity setting only affects the backgrounds (see card_render.paint_card)
        card_render.paint_card(painter, view.scene, view.rect_cur, view.alpha, view.text_alpha,
                               self.global_opacity, self.text_color, self._phase)
