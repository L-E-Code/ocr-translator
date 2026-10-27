import ctypes
import sys
from ctypes import wintypes

import mss
import numpy as np
import cv2

def get_available_monitors():
    """
    Returns the list of available monitors (skipping index 0, which is the union of all of them).
    """
    with mss.MSS() as sct:
        return sct.monitors[1:]

def capture_screen_raw(region, sct=None):
    """
    Captures the given region as a BGRA NumPy array straight in RAM, without copying or converting it:
    most frames only feed the change detection, so the RGB conversion is left for the ones that go to OCR.
    """
    if sct is None:
        with mss.MSS() as local_sct:
            return np.asarray(local_sct.grab(region))
    return np.asarray(sct.grab(region))


def bgra_to_rgb(frame):
    return cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)

# ----------------------------------------------------------------------
# Windows (Win32): lets the capture area follow the game window
# ----------------------------------------------------------------------
_user32 = ctypes.windll.user32 if sys.platform == "win32" else None


def _window_title(hwnd):
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def list_windows(exclude_pid=None):
    """Visible windows with a title, front to back: [(hwnd, title)]."""
    if _user32 is None:
        return []
    found = []
    pid = wintypes.DWORD()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if _user32.IsWindowVisible(hwnd) and not _user32.IsIconic(hwnd):
            title = _window_title(hwnd)
            if title.strip():
                _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if exclude_pid is None or pid.value != exclude_pid:
                    found.append((hwnd, title))
        return True

    _user32.EnumWindows(visit, 0)
    return found


def foreground_window_title(exclude_pid=None):
    """Title of the foreground window ('' if it belongs to this program or there is none)."""
    if _user32 is None:
        return ""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return ""
    if exclude_pid is not None:
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == exclude_pid:
            return ""
    return _window_title(hwnd)


def find_window(title_part):
    """First visible window (top to bottom) whose title contains the text, ignoring case."""
    needle = (title_part or "").strip().lower()
    if not needle:
        return None
    for hwnd, title in list_windows():
        if needle in title.lower():
            return hwnd
    return None


def window_client_rect(hwnd):
    """Client area of the window in screen coordinates: (left, top, width, height), or None if minimized/empty."""
    if _user32 is None or not hwnd or _user32.IsIconic(hwnd):
        return None
    rect = wintypes.RECT()
    if not _user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    origin = wintypes.POINT(0, 0)
    if not _user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width < 16 or height < 16:
        return None
    return origin.x, origin.y, width, height


def region_to_window_relative(region, title_part):
    """
    Converts an absolute screen region into proportions of the game window.
    Returns a copy of the region with 'window_title' and 'rel', or None if the window is not found.
    """
    rect = window_client_rect(find_window(title_part))
    if rect is None:
        return None
    wl, wt, ww, wh = rect
    out = dict(region)
    out["window_title"] = title_part
    out["rel"] = [
        (region["left"] - wl) / ww, (region["top"] - wt) / wh,
        region["width"] / ww, region["height"] / wh,
    ]
    return out


def resolve_region(region):
    """
    Current capture region. Regions attached to a window are recomputed on every call,
    following its movement and resizing; returns None if the window is gone or minimized.
    """
    title, rel = region.get("window_title"), region.get("rel")
    if not title or not rel:
        return region
    rect = window_client_rect(find_window(title))
    if rect is None:
        return None
    wl, wt, ww, wh = rect
    left, top = wl + int(rel[0] * ww), wt + int(rel[1] * wh)
    width, height = max(1, int(rel[2] * ww)), max(1, int(rel[3] * wh))
    mon_left = region["left"] - region.get("offset_x", 0)
    mon_top = region["top"] - region.get("offset_y", 0)
    out = dict(region)
    out.update(left=left, top=top, width=width, height=height, offset_x=left - mon_left, offset_y=top - mon_top)
    return out


def save_custom_roi(roi):
    """
    Saves the custom area selected with the mouse for future use.
    """
    from core.config_manager import save_config
    save_config({"last_custom_roi": roi})

def get_roi_region(monitor, roi_type="full"):
    """
    Computes the capture sub-region based on the desired focus area:
    - 'full': Entire screen
    - 'bottom_third': Bottom third (typical dialogue boxes)
    - 'bottom_half': Bottom half
    """
    left = monitor['left']
    top = monitor['top']
    width = monitor['width']
    height = monitor['height']
    
    if roi_type == "bottom_third":
        new_top = top + int(height * 0.65)
        new_height = int(height * 0.33)
        return {'left': left, 'top': new_top, 'width': width, 'height': new_height, 'offset_y': int(height * 0.65), 'offset_x': 0}
    elif roi_type == "bottom_half":
        new_top = top + int(height * 0.50)
        new_height = int(height * 0.48)
        return {'left': left, 'top': new_top, 'width': width, 'height': new_height, 'offset_y': int(height * 0.50), 'offset_x': 0}
    else:
        reg = dict(monitor)
        reg['offset_x'] = 0
        reg['offset_y'] = 0
        return reg
