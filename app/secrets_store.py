"""
Groq API key storage. The key lives in the Windows Credential Manager (through `keyring`) instead of a text file;
the `GROQ_API_KEY` of the .env file keeps working as a fallback. The key is never logged or written anywhere else.
"""
import os

from logger_config import get_logger

logger = get_logger("Secrets")

SERVICE = "OCR Translator"
ACCOUNT = "GROQ_API_KEY"

SOURCE_STORE = "store"  # Windows Credential Manager
SOURCE_ENV = "env"      # .env file / environment variable


def _keyring():
    try:
        import keyring
        return keyring
    except Exception as e:  # not installed or no usable backend
        logger.debug(f"keyring unavailable: {e}")
        return None


def _env_key():
    key = os.getenv("GROQ_API_KEY", "").strip()
    return "" if key.startswith("your_") else key


def _stored_key():
    kr = _keyring()
    if kr is None:
        return ""
    try:
        return (kr.get_password(SERVICE, ACCOUNT) or "").strip()
    except Exception as e:
        logger.warning(f"Could not read the key from the credential store: {e}")
        return ""


def groq_key():
    """The key to use ('' if there is none): credential store first, then the .env file."""
    return _stored_key() or _env_key()


def groq_key_source():
    """Where the key in use comes from: SOURCE_STORE, SOURCE_ENV or None."""
    if _stored_key():
        return SOURCE_STORE
    if _env_key():
        return SOURCE_ENV
    return None


def store_available():
    return _keyring() is not None


def set_groq_key(key):
    """Saves the key in the credential store. Returns (ok, error message)."""
    key = (key or "").strip()
    if not key:
        return False, "empty key"
    kr = _keyring()
    if kr is None:
        return False, "the keyring package is not installed"
    try:
        kr.set_password(SERVICE, ACCOUNT, key)
    except Exception as e:
        logger.warning(f"Could not save the key in the credential store: {type(e).__name__}")
        return False, str(e)
    logger.info("Groq key saved in the credential store.")
    return True, ""


def delete_groq_key():
    """Removes the key from the credential store (the .env file is never touched). Returns True if there was one."""
    kr = _keyring()
    if kr is None or not _stored_key():
        return False
    try:
        kr.delete_password(SERVICE, ACCOUNT)
    except Exception as e:
        logger.warning(f"Could not remove the key from the credential store: {type(e).__name__}")
        return False
    logger.info("Groq key removed from the credential store.")
    return True
