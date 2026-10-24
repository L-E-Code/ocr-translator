import os
import json
import copy
import tempfile
from languages import LANGUAGES as SUPPORTED_LANGUAGES
from logger_config import get_logger
from paths import root_path

logger = get_logger("Config")

# The file lives at the project root, regardless of the folder the app was opened from
CONFIG_FILE = root_path("config.json")

# File format version; bump it when renaming/removing keys and add the migration to _MIGRATIONS
CONFIG_VERSION = 1

DEFAULT_CONFIG = {
    "config_version": CONFIG_VERSION,
    "monitor_index": 0,
    "roi_mode": "bottom_third",  # 'custom', 'bottom_third', 'bottom_half', 'full'
    "last_custom_roi": None,
    "display_mode": "sidebar",  # 'sidebar' or 'overlay'
    "source_lang": "ja",
    "target_lang": "en",
    "minimize_on_start": True,
    "debounce_ms": 200,  # wait for the text to settle (50 = ultra fast, 400 = conservative)
    "compute_device": "auto",  # 'auto' (GPU if available), 'gpu' or 'cpu'
    "overlay_mode": "inplace",  # 'inplace' (covers the original text) or 'subtitle' (bottom subtitle)
    "overlay_opacity": 1.0,  # 0.3 a 1.0
    "groq_models": None,  # e.g. ["llama-3.1-8b-instant"] for lower latency; None uses the default
    "extra_regions": [],  # additional capture regions (each one with a 'label'), besides last_custom_roi
    "window_title": "",  # part of the game window title (follow the window and automatic profile)
    "track_window": False,  # True: the custom areas follow the game window
    "profiles": {},  # named profiles: {name: {PROFILE_KEYS key: value}}
    "active_profile": None,
    "auto_profile": True,  # switches profile on its own according to the active window
    "translation_context": 3,  # how many previous lines the AI receives as context (0 disables)
    "glossary_file": None,  # alternative glossary (file name at the root); comes from the active profile
    "check_updates": True,  # looks for a newer release on GitHub when the app opens (only reads the version)
    "ui_language": "en",  # interface language: 'en' or 'pt' (applied on the next start)
    "hotkeys": {  # global hotkeys (work while the game is in the foreground)
        "pause": "Ctrl+Alt+P", "reload": "Ctrl+Alt+R", "toggle_ui": "Ctrl+Alt+H",
        "history": "Ctrl+Alt+J", "clear": "Ctrl+Alt+L",
    },
}

# Settings each profile stores (the rest, such as processing device and windows, is global)
PROFILE_KEYS = (
    "monitor_index", "roi_mode", "last_custom_roi", "extra_regions", "window_title", "track_window",
    "source_lang", "target_lang", "display_mode", "overlay_mode", "overlay_opacity", "debounce_ms",
    "glossary_file",  # optional, hand-edited: glossary file used only by this profile
)

HOTKEY_ACTIONS = ("pause", "reload", "toggle_ui", "history", "clear")
MAX_REGIONS = 6

LANGUAGES = set(SUPPORTED_LANGUAGES)


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------
def _choice(options):
    def check(v):
        try:
            return v if v in options else _INVALID
        except TypeError:  # unhashable value (list/dict)
            return _INVALID
    return check

def _int_range(low, high):
    def check(v):
        if isinstance(v, bool):
            return _INVALID
        try:
            n = int(v)
        except (TypeError, ValueError):
            return _INVALID
        return min(high, max(low, n))
    return check

def _float_range(low, high):
    def check(v):
        if isinstance(v, bool):
            return _INVALID
        try:
            n = float(v)
        except (TypeError, ValueError):
            return _INVALID
        if n != n:  # NaN
            return _INVALID
        return min(high, max(low, n))
    return check

def _boolean(v):
    return v if isinstance(v, bool) else _INVALID

def _roi(v):
    """Custom area: None or a dictionary with positive integer left/top/width/height."""
    if v is None:
        return None
    if not isinstance(v, dict):
        return _INVALID
    out = {}
    for key in ("left", "top", "width", "height"):
        val = v.get(key)
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return _INVALID
        out[key] = int(val)
    if out["width"] <= 0 or out["height"] <= 0:
        return _INVALID
    for key, fallback in (("offset_x", "left"), ("offset_y", "top")):
        val = v.get(key, out[fallback])
        out[key] = int(val) if isinstance(val, (int, float)) and not isinstance(val, bool) else out[fallback]
    if isinstance(v.get("label"), str) and v["label"].strip():
        out["label"] = v["label"].strip()[:30]
    rel, title = v.get("rel"), v.get("window_title")
    if (isinstance(title, str) and title.strip() and isinstance(rel, list) and len(rel) == 4
            and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in rel)):
        out["rel"] = [float(x) for x in rel]
        out["window_title"] = title.strip()
    return out

def _region_list(v):
    """List of areas (up to MAX_REGIONS); invalid areas are discarded."""
    if not isinstance(v, list):
        return _INVALID
    regions = []
    for item in v:
        region = _roi(item)
        if isinstance(region, dict):
            regions.append(region)
    return regions[:MAX_REGIONS]

def _text(max_len):
    def check(v):
        return v.strip()[:max_len] if isinstance(v, str) else _INVALID
    return check

def _optional_text(max_len):
    def check(v):
        return None if v is None else _text(max_len)(v)
    return check

def _hotkeys(v):
    if not isinstance(v, dict):
        return _INVALID
    out = dict(DEFAULT_CONFIG["hotkeys"])
    for action in HOTKEY_ACTIONS:
        value = v.get(action)
        if isinstance(value, str):
            out[action] = value.strip()  # empty = hotkey disabled
    return out

def _profiles(v):
    """Valid profiles: name of up to 40 characters and only the PROFILE_KEYS keys with accepted values."""
    if not isinstance(v, dict):
        return _INVALID
    out = {}
    for name, data in v.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(data, dict):
            continue
        clean = {}
        for key in PROFILE_KEYS:
            if key in data:
                value = _VALIDATORS[key](data[key])
                if value is not _INVALID:
                    clean[key] = value
        out[name.strip()[:40]] = clean
    return out

def _model_list(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = [v]
    if isinstance(v, list):
        models = [m.strip() for m in v if isinstance(m, str) and m.strip()]
        return models or None
    return _INVALID

_INVALID = object()

_VALIDATORS = {
    "config_version": _int_range(0, 10_000),
    "monitor_index": _int_range(0, 64),
    "roi_mode": _choice({"custom", "bottom_third", "bottom_half", "full"}),
    "last_custom_roi": _roi,
    "display_mode": _choice({"sidebar", "overlay"}),
    "source_lang": _choice(LANGUAGES),
    "target_lang": _choice(LANGUAGES),
    "minimize_on_start": _boolean,
    "debounce_ms": _int_range(50, 400),
    "compute_device": _choice({"auto", "gpu", "cpu"}),
    "overlay_mode": _choice({"inplace", "subtitle"}),
    "overlay_opacity": _float_range(0.3, 1.0),
    "groq_models": _model_list,
    "extra_regions": _region_list,
    "window_title": _text(120),
    "track_window": _boolean,
    "profiles": _profiles,
    "active_profile": _optional_text(40),
    "auto_profile": _boolean,
    "translation_context": _int_range(0, 6),
    "hotkeys": _hotkeys,
    "glossary_file": _optional_text(200),
    "ui_language": _choice({"en", "pt"}),
    "check_updates": _boolean,
}


def validate_config(config):
    """
    Returns (fixed_config, fixed_keys). Invalid values go back to the default;
    out-of-range numbers are clamped; unknown keys are preserved.
    """
    fixed = []
    result = {}
    for key, value in config.items():
        check = _VALIDATORS.get(key)
        if check is None:
            result[key] = value
            continue
        cleaned = check(value)
        if cleaned is _INVALID:
            result[key] = copy.deepcopy(DEFAULT_CONFIG[key])
            fixed.append(key)
        else:
            if cleaned != value:
                fixed.append(key)
            result[key] = cleaned
    for key, default in DEFAULT_CONFIG.items():
        result.setdefault(key, copy.deepcopy(default))
    return result, fixed


# ----------------------------------------------------------------------
# Migration of old file versions
# ----------------------------------------------------------------------
def _migrate_0_to_1(data):
    # Files created before versioning: the format is the same, the version stamp is just missing
    return data

_MIGRATIONS = {0: _migrate_0_to_1}  # source version -> function that takes it to the next version

def _migrate(data):
    version = data.get("config_version", 0)
    if not isinstance(version, int) or isinstance(version, bool):
        version = 0
    while version < CONFIG_VERSION:
        step = _MIGRATIONS.get(version)
        if step:
            data = step(dict(data))
        version += 1
        logger.info(f"Configuration migrated to version {version}.")
    data["config_version"] = CONFIG_VERSION
    return data


# ----------------------------------------------------------------------
# Reading and writing
# ----------------------------------------------------------------------
def _backup_corrupt_file():
    """Keeps a copy of the unreadable file so the user can recover something from it."""
    try:
        os.replace(CONFIG_FILE, CONFIG_FILE + ".corrupt")
        logger.warning(f"Unreadable file preserved at {CONFIG_FILE}.corrupt")
    except OSError:
        pass

def _write_atomic(data):
    """Writes to a temporary file and swaps it in one go, so a crash midway does not corrupt the config."""
    folder = os.path.dirname(CONFIG_FILE)
    fd, tmp_path = tempfile.mkstemp(dir=folder, prefix=".config_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CONFIG_FILE)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

def load_config():
    """Loads the saved settings (migrated and validated) or returns the defaults."""
    data = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = _migrate(loaded)
            else:
                raise ValueError("the content is not a JSON object")
        except Exception as e:
            logger.error(f"Error reading {CONFIG_FILE}: {e}")
            _backup_corrupt_file()
            data = {}
    config, fixed = validate_config(data)
    if fixed:
        logger.warning(f"Invalid values fixed in the configuration: {', '.join(fixed)}")
    return config

def save_config(config_dict):
    """Merges the changes into the saved settings, validates and writes atomically."""
    try:
        current = load_config()
        current.update(config_dict)
        current["config_version"] = CONFIG_VERSION
        current, _ = validate_config(current)
        _write_atomic(current)
        return True
    except Exception as e:
        logger.error(f"Error saving {CONFIG_FILE}: {e}")
        return False

def reset_config():
    """Restores every preference to its default value and returns the resulting configuration."""
    defaults = copy.deepcopy(DEFAULT_CONFIG)
    # Profiles are the user's work: restoring the settings must not erase them
    defaults["profiles"] = load_config().get("profiles", {})
    try:
        _write_atomic(defaults)
    except Exception as e:
        logger.error(f"Error restoring {CONFIG_FILE}: {e}")
    return defaults
