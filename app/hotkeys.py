"""
Global hotkeys (work while the game is in the foreground) via the Windows RegisterHotKey API.
The thread that owns the hotkeys runs its own message loop, and every triggered hotkey becomes a Qt signal.
"""
import ctypes
import sys
import threading
from ctypes import wintypes

from PyQt6.QtCore import QObject, pyqtSignal

from logger_config import get_logger

logger = get_logger("Hotkeys")

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

_MODIFIERS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT,
              "meta": MOD_WIN, "win": MOD_WIN}
_NAMED_KEYS = {
    "space": 0x20, "return": 0x0D, "enter": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09,
    "backspace": 0x08, "ins": 0x2D, "insert": 0x2D, "del": 0x2E, "delete": 0x2E,
    "home": 0x24, "end": 0x23, "pgup": 0x21, "pageup": 0x21, "pgdown": 0x22, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
}


def parse_hotkey(text):
    """
    Converts "Ctrl+Alt+P" into (modifiers, virtual key code). Returns None if the text is empty,
    invalid or has no modifier at all (a bare key would take that key away from the game).
    """
    if not text or not text.strip():
        return None
    mods, vk = 0, None
    for part in (p.strip().lower() for p in text.split("+")):
        if part in _MODIFIERS:
            mods |= _MODIFIERS[part]
        elif part in _NAMED_KEYS:
            vk = _NAMED_KEYS[part]
        elif len(part) == 1 and part.isalnum() and part.isascii():
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            vk = 0x70 + int(part[1:]) - 1
        else:
            return None
    if vk is None or not mods:
        return None
    return mods, vk


class GlobalHotkeys(QObject):
    """Registers global hotkeys {action: "Ctrl+Alt+P"}; `triggered(action)` is emitted when they are pressed."""
    triggered = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._thread_id = None
        self.failed = []  # actions whose hotkey is invalid or already in use by another program

    def start(self, bindings):
        """Registers the hotkeys; returns the list of actions that could not be registered."""
        self.stop()
        self.failed = []
        if sys.platform != "win32":
            return self.failed
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(dict(bindings), ready),
                                        name="global-hotkeys", daemon=True)
        self._thread.start()
        ready.wait(2.0)
        return list(self.failed)

    def stop(self):
        if self._thread and self._thread.is_alive() and self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(1.0)
        self._thread = None
        self._thread_id = None

    def _run(self, bindings, ready):
        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        ids = {}
        try:
            for index, (action, text) in enumerate(bindings.items(), start=1):
                parsed = parse_hotkey(text)
                if parsed is None:
                    if text and text.strip():
                        self.failed.append(action)
                    continue
                mods, vk = parsed
                if user32.RegisterHotKey(None, index, mods | MOD_NOREPEAT, vk):
                    ids[index] = action
                else:
                    logger.warning(f"Hotkey '{text}' ({action}) is already in use by another program.")
                    self.failed.append(action)
        finally:
            ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in ids:
                self.triggered.emit(ids[msg.wParam])
        for index in ids:
            user32.UnregisterHotKey(None, index)
