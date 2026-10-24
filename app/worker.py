import time
import mss
import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from capture import capture_screen_np, resolve_region
from logger_config import get_logger

logger = get_logger("WorkerThread")

# Average brightness difference (thumbnail) from which we consider a full scene/line change
SCENE_CHANGE_DIFF = 8.0
# Polling interval when the screen did not change / between cycles
IDLE_POLL = 0.05
# Sampling while waiting for the text to stop being typed, and the limit of that wait
SETTLE_POLL = 0.06
MAX_SETTLE_WAIT = 2.5
# Minimum thumbnail difference to consider that the screen changed
CHANGE_DIFF = 0.8
# Minimum difference to defer the translation after OCR (higher: ignores subtle animations)
DEFER_DIFF = 2.0
CYCLE_PAUSE = 0.03


class _RegionState:
    """Tracking state of one capture region."""
    def __init__(self, base):
        self.base = base
        self.label = base.get('label')
        self.prev_thumb = None
        self.last_processed_thumb = None  # thumbnail of the last frame that went through OCR
        self.deferred_last_cycle = False
        self.missing_logged = False


class WorkerThread(QThread):
    """
    Thread that captures frames straight into RAM
    and sends them to the AI for processing. Accepts several capture regions (each with its own label),
    read in turns; regions attached to a window follow its movement.
    """
    update_signal = pyqtSignal(list)
    info_signal = pyqtSignal(dict)  # translation engine used and latency of the last cycle

    def __init__(self, capture_region, ocr_engine, debounce_ms=200):
        super().__init__()
        # Maximum wait for the typewriter effect to settle (abrupt screen changes skip the wait)
        self.debounce = max(0, int(debounce_ms)) / 1000.0
        regions = capture_region if isinstance(capture_region, (list, tuple)) else [capture_region]
        self.regions = [_RegionState(dict(r)) for r in regions if r]
        self.ocr_engine = ocr_engine
        self.running = True
        self.paused = False
        self.force_reload = False

    def set_paused(self, is_paused):
        self.paused = is_paused

    def request_reload(self):
        """Requests a re-read of the screen and a new translation."""
        self.force_reload = True

    @staticmethod
    def _thumb(frame):
        return cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (128, 64))

    @staticmethod
    def _thumb_diff(a, b):
        return float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))))

    def _grab(self, sct, state):
        """Captures the region (already resolved against the window, if applicable); (None, None) if there is nothing to capture."""
        region = resolve_region(state.base)
        if region is None:
            if not state.missing_logged:
                logger.info(f"Region '{state.label or 'main'}' window not found or minimized; waiting.")
                state.missing_logged = True
            return None, None
        state.missing_logged = False
        return capture_screen_np(region, sct=sct), region

    def _wait_until_settled(self, sct, state, frame, thumb):
        """
        Samples the screen until it stays still for `debounce` seconds (end of typing),
        limited to MAX_SETTLE_WAIT. Cheap: only compares thumbnails, no OCR.
        """
        start = last_change = time.time()
        while self.running and time.time() - last_change < self.debounce and time.time() - start < MAX_SETTLE_WAIT:
            time.sleep(SETTLE_POLL)
            try:
                nxt, _ = self._grab(sct, state)
            except Exception:
                continue
            if nxt is None or nxt.size == 0:
                continue
            nxt_thumb = self._thumb(nxt)
            if self._thumb_diff(nxt_thumb, thumb) >= CHANGE_DIFF:
                last_change = time.time()
            frame, thumb = nxt, nxt_thumb
        return frame, thumb

    def _should_defer(self, sct, state):
        """Defers the translation at most once in a row, so background animations do not stall the cycle."""
        if state.deferred_last_cycle:
            state.deferred_last_cycle = False
            return False
        state.deferred_last_cycle = self._frame_changed(sct, state)
        return state.deferred_last_cycle

    def _frame_changed(self, sct, state):
        """True if the current screen already differs from the frame being translated."""
        if state.last_processed_thumb is None:
            return False
        try:
            current, _ = self._grab(sct, state)
        except Exception:
            return False
        if current is None or current.size == 0:
            return False
        return self._thumb_diff(self._thumb(current), state.last_processed_thumb) >= DEFER_DIFF

    def _process_region(self, sct, state, is_reload):
        """One cycle of a region. Returns True if OCR ran, False if there was nothing new."""
        if is_reload:
            state.prev_thumb = None
            state.last_processed_thumb = None

        # 1. Capture
        try:
            frame_np, region = self._grab(sct, state)
        except Exception as cap_err:
            logger.warning(f"Momentary error capturing the screen: {cap_err}")
            time.sleep(0.5)
            return False

        if frame_np is None or frame_np.size == 0:
            return False

        # 2. Screen change detection (grayscale thumbnail)
        if not is_reload:
            thumb = self._thumb(frame_np)

            if state.prev_thumb is not None:
                diff = self._thumb_diff(thumb, state.prev_thumb)
                # Practically identical screen
                if diff < CHANGE_DIFF:
                    return False
                is_scene_change = diff >= SCENE_CHANGE_DIFF
            else:
                is_scene_change = True

            state.prev_thumb = thumb

            # Adaptive debounce: an abrupt screen change goes straight to OCR;
            # small changes (typing) wait for the text to settle
            if not is_scene_change and self.debounce > 0:
                frame_np, state.prev_thumb = self._wait_until_settled(sct, state, frame_np, thumb)

        # Settled frame equal to the last one already processed (e.g. a background animation that went back to the
        # same state): there is nothing new to read
        settled_thumb = self._thumb(frame_np)
        if not is_reload and state.last_processed_thumb is not None:
            if self._thumb_diff(settled_thumb, state.last_processed_thumb) < CHANGE_DIFF:
                return False
        state.last_processed_thumb = settled_thumb

        # 3. The panel updates as soon as OCR captures the sentence
        def tagged(items):
            for item in items:
                item['region'] = state.label
            return items

        def on_intermediate(prelim):
            if self.running and prelim:
                self.update_signal.emit(tagged(prelim))

        # 4. OCR and translation
        results = self.ocr_engine.process_image(
            frame_np,
            offset_x=region.get('offset_x', 0),
            offset_y=region.get('offset_y', 0),
            on_intermediate=on_intermediate,
            force_reload=is_reload,
            should_abort_translation=lambda: self._should_defer(sct, state),
            region_key=state.label,
        )

        # 5. Final translated result
        if results is not None:
            state.deferred_last_cycle = False
            self.update_signal.emit(tagged(results))
            info = getattr(self.ocr_engine, 'last_translation_info', None)
            if info:
                self.info_signal.emit(dict(info))
        return True

    def run(self):
        logger.info(f"WorkerThread started ({len(self.regions)} region(s)).")

        try:
            with mss.MSS() as sct:
                while self.running:
                    is_reload = self.force_reload
                    if is_reload:
                        self.force_reload = False

                    if self.paused and not is_reload:
                        time.sleep(0.5)
                        continue

                    worked = False
                    for state in self.regions:
                        if not self.running:
                            break
                        worked |= self._process_region(sct, state, is_reload)

                    # No news in any region: short wait; otherwise, interval between cycles
                    time.sleep(CYCLE_PAUSE if worked else IDLE_POLL)

        except Exception as e:
            logger.error(f"Unexpected error in WorkerThread: {e}", exc_info=True)
        finally:
            logger.info("WorkerThread finished.")

    def stop(self):
        logger.info("Stop requested for WorkerThread.")
        self.running = False
