import time
import mss
import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from core.capture import bgra_to_rgb, capture_screen_raw, resolve_region
from core.logger_config import get_logger

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
# Consecutive failures from which the user is warned (capture or OCR); a success clears the warning
FAILURE_ALERT = 3
# Wait after a failed cycle, so a persistent error does not spin the CPU
FAILURE_PAUSE = 0.5


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
    region_cleared = pyqtSignal(object)  # label of a region where no text was found on the screen
    health_signal = pyqtSignal(str, bool, str)  # (kind 'capture' | 'ocr', working, error message): failing for several cycles in a row
    capture_status = pyqtSignal(bool, str)  # (window available, window title): the followed game window went away / came back

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
        self._missing = set()  # regions whose window is not available right now
        self._failures = {"capture": 0, "ocr": 0}  # consecutive failures per kind
        self._alerted = set()  # kinds currently reported to the user
        self._reset_capture = False  # recreate the screen grabber (monitors may have changed)

    def set_paused(self, is_paused):
        self.paused = is_paused

    def request_reload(self):
        """Requests a re-read of the screen and a new translation."""
        self.force_reload = True

    def _report(self, kind, error=None):
        """Counts a failure (error given) or a success of a kind; warns the user when it persists and when it recovers."""
        if error is None:
            self._failures[kind] = 0
            if kind in self._alerted:
                self._alerted.discard(kind)
                self.health_signal.emit(kind, True, "")
            return
        self._failures[kind] += 1
        if self._failures[kind] >= FAILURE_ALERT and kind not in self._alerted:
            self._alerted.add(kind)
            self.health_signal.emit(kind, False, str(error)[:120])

    @staticmethod
    def _thumb(frame):
        # Shrinks the BGRA frame first: only the tiny thumbnail goes through the grayscale conversion
        return cv2.cvtColor(cv2.resize(frame, (128, 64)), cv2.COLOR_BGRA2GRAY)

    @staticmethod
    def _thumb_diff(a, b):
        return float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))))

    def _grab(self, sct, state):
        """Captures the region as BGRA (already resolved against the window, if applicable); (None, None) if there is nothing to capture."""
        region = resolve_region(state.base)
        title = state.base.get('window_title', '')
        if region is None:
            if not state.missing_logged:
                logger.info(f"Region '{state.label or 'main'}' window not found or minimized; waiting.")
                state.missing_logged = True
                if not self._missing:
                    self.capture_status.emit(False, title)
                self._missing.add(id(state))
            return None, None
        if state.missing_logged:
            logger.info(f"Region '{state.label or 'main'}' window is back.")
            state.missing_logged = False
            self._missing.discard(id(state))
            if not self._missing:
                self.capture_status.emit(True, title)
        return capture_screen_raw(region, sct=sct), region

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
            self._report("capture", cap_err)
            if self._failures["capture"] == FAILURE_ALERT:
                self._reset_capture = True  # a monitor that was unplugged or changed leaves the grabber stale
            time.sleep(FAILURE_PAUSE)
            return False

        if frame_np is None or frame_np.size == 0:
            return False
        self._report("capture")

        # 2. Screen change detection (grayscale thumbnail)
        thumb = self._thumb(frame_np)
        if not is_reload:
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
                frame_np, thumb = self._wait_until_settled(sct, state, frame_np, thumb)
                state.prev_thumb = thumb

        # Settled frame equal to the last one already processed (e.g. a background animation that went back to the
        # same state): there is nothing new to read
        if not is_reload and state.last_processed_thumb is not None:
            if self._thumb_diff(thumb, state.last_processed_thumb) < CHANGE_DIFF:
                return False
        state.last_processed_thumb = thumb

        # 3. The panel updates as soon as OCR captures the sentence
        def tagged(items):
            for item in items:
                item['region'] = state.label
            return items

        def on_intermediate(prelim):
            if self.running and prelim:
                self.update_signal.emit(tagged(prelim))

        def on_translated(results, info):
            # Comes from a translation thread once the API answers; meanwhile this loop keeps reading the screen
            if not self.running:
                return
            if results:
                self.update_signal.emit(tagged(results))
            if info:
                self.info_signal.emit(dict(info))

        # 4. OCR and translation
        try:
            results = self.ocr_engine.process_image(
                bgra_to_rgb(frame_np),
                offset_x=region.get('offset_x', 0),
                offset_y=region.get('offset_y', 0),
                on_intermediate=on_intermediate,
                on_translated=on_translated,
                force_reload=is_reload,
                should_abort_translation=lambda: self._should_defer(sct, state),
                region_key=state.label,
            )
        except Exception as ocr_err:
            # One bad frame must not end the translation: logs it, warns if it keeps happening and goes on
            logger.error(f"Error while reading/translating the screen: {ocr_err}", exc_info=True)
            self._report("ocr", ocr_err)
            state.last_processed_thumb = None  # the same frame is tried again
            time.sleep(FAILURE_PAUSE)
            return False
        self._report("ocr")

        # 5. Final result (None: deferred, or the translation arrives later through on_translated)
        if results is not None:
            state.deferred_last_cycle = False
            if results:
                self.update_signal.emit(tagged(results))
            else:
                self.region_cleared.emit(state.label)
            info = getattr(self.ocr_engine, 'last_translation_info', None)
            if info:
                self.info_signal.emit(dict(info))
        return True

    def run(self):
        logger.info(f"WorkerThread started ({len(self.regions)} region(s)).")

        try:
            while self.running:
                self._reset_capture = False
                with mss.MSS() as sct:
                    while self.running and not self._reset_capture:
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
                if self.running:
                    logger.info("Recreating the screen grabber after repeated capture failures.")

        except Exception as e:
            logger.error(f"Unexpected error in WorkerThread: {e}", exc_info=True)
        finally:
            logger.info("WorkerThread finished.")

    def stop(self):
        logger.info("Stop requested for WorkerThread.")
        self.running = False
