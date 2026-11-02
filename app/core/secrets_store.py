"""
Groq API key storage. The keys live in the Windows Credential Manager (through `keyring`) instead of a text file; the
`GROQ_API_KEY` of the .env file keeps working as a fallback. Several keys can be saved: the translation uses the first
one and moves to the next when it reaches its limit. A key is never logged or written anywhere else.
"""
import json
import os

from core.logger_config import get_logger

logger = get_logger("Secrets")

SERVICE = "OCR Translator"
ACCOUNT = "GROQ_API_KEY"        # the single key saved by older versions
KEYS_ACCOUNT = "GROQ_API_KEYS"  # a JSON list of keys, in the order they are used

SOURCE_STORE = "store"  # Windows Credential Manager
SOURCE_ENV = "env"      # .env file / environment variable

MAX_KEYS = 8


def _keyring():
    try:
        import keyring
        return keyring
    except Exception as e:  # not installed or no usable backend
        logger.debug(f"keyring unavailable: {e}")
        return None


def _unique(keys):
    seen, result = set(), []
    for key in keys:
        key = (key or "").strip()
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result


def _env_keys():
    """GROQ_API_KEY and, if present, GROQ_API_KEYS (separated by commas) from the .env file or the environment."""
    raw = [os.getenv("GROQ_API_KEY", "")] + os.getenv("GROQ_API_KEYS", "").split(",")
    return _unique(k for k in raw if not k.strip().startswith("your_"))


def _stored_keys():
    """The keys of the credential store in use order: the saved list, or the single key of an older version."""
    kr = _keyring()
    if kr is None:
        return []
    try:
        listed = kr.get_password(SERVICE, KEYS_ACCOUNT)
        if listed:
            data = json.loads(listed)
            if isinstance(data, list):
                return _unique(k for k in data if isinstance(k, str))
        return _unique([kr.get_password(SERVICE, ACCOUNT)])
    except Exception as e:
        logger.warning(f"Could not read the keys from the credential store: {type(e).__name__}")
        return []


def _delete(kr, account):
    try:
        kr.delete_password(SERVICE, account)
    except Exception:
        pass  # nothing saved there


def _write_keys(keys):
    """Saves the whole list (and drops the single-key entry of older versions). Returns (ok, error message)."""
    kr = _keyring()
    if kr is None:
        return False, "the keyring package is not installed"
    try:
        if keys:
            kr.set_password(SERVICE, KEYS_ACCOUNT, json.dumps(keys))
            _delete(kr, ACCOUNT)
        else:
            _delete(kr, KEYS_ACCOUNT)
            _delete(kr, ACCOUNT)
    except Exception as e:
        logger.warning(f"Could not save the keys in the credential store: {type(e).__name__}")
        return False, str(e)
    return True, ""


def saved_groq_keys():
    """Only the keys saved in the credential store, in order (the ones from the .env file are not included)."""
    return _stored_keys()


def groq_keys():
    """The keys to use, in order ([] if there are none): credential store first, then the .env file."""
    return _stored_keys() or _env_keys()


def groq_key():
    """The first key ('' if there is none)."""
    keys = groq_keys()
    return keys[0] if keys else ""


def groq_key_source():
    """Where the keys in use come from: SOURCE_STORE, SOURCE_ENV or None."""
    if _stored_keys():
        return SOURCE_STORE
    if _env_keys():
        return SOURCE_ENV
    return None


def store_available():
    return _keyring() is not None


def mask_key(key):
    """'gsk_…a1b2': enough to tell the keys apart without showing them."""
    key = (key or "").strip()
    return f"{key[:4]}…{key[-4:]}" if len(key) > 10 else "…"


def add_groq_key(key):
    """Adds a key at the end of the list (it is used after the ones before it). Returns (ok, error message)."""
    key = (key or "").strip()
    if not key:
        return False, "empty key"
    keys = _stored_keys()
    if key in keys:
        return False, "this key is already saved"
    if len(keys) >= MAX_KEYS:
        return False, f"at most {MAX_KEYS} keys can be saved"
    ok, error = _write_keys(keys + [key])
    if ok:
        logger.info(f"Groq key saved in the credential store ({len(keys) + 1} in total).")
    return ok, error


def set_groq_key(key):
    """Saves the key as the only one (replacing the others). Returns (ok, error message)."""
    key = (key or "").strip()
    if not key:
        return False, "empty key"
    ok, error = _write_keys([key])
    if ok:
        logger.info("Groq key saved in the credential store.")
    return ok, error


def remove_groq_key(key):
    """Removes one saved key. Returns True if it was there."""
    keys = _stored_keys()
    if key not in keys:
        return False
    ok, _ = _write_keys([k for k in keys if k != key])
    if ok:
        logger.info("A Groq key was removed from the credential store.")
    return ok


def move_groq_key(key, step):
    """Moves a saved key up (step -1) or down (+1) in the order of use. Returns True if it moved."""
    keys = _stored_keys()
    if key not in keys:
        return False
    i, j = keys.index(key), keys.index(key) + step
    if not 0 <= j < len(keys):
        return False
    keys[i], keys[j] = keys[j], keys[i]
    return _write_keys(keys)[0]


def delete_groq_key():
    """Removes every key saved in the credential store (the .env file is never touched). Returns True if there was one."""
    if not _stored_keys():
        return False
    ok, _ = _write_keys([])
    if ok:
        logger.info("Groq keys removed from the credential store.")
    return ok
