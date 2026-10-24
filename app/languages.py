"""
Supported languages: UI name, name used in the AI prompt and the code for each engine.
"""
import re
from collections import namedtuple

Language = namedtuple("Language", "label prompt easyocr mymemory google script")

# `script`: expression a read text must contain to be considered part of the language (None = any)
LANGUAGES = {
    "ja": Language("Japanese", "Japanese", "ja", "ja-JP", "ja", r"[぀-ゟ゠-ヿ一-龯]"),
    "en": Language("English", "English", "en", "en-US", "en", None),
    "pt": Language("Portuguese (BR)", "Brazilian Portuguese", "pt", "pt-BR", "pt", None),
}

# Scripts that EasyOCR only reads together with English (Latin ones work alone)
_NEEDS_ENGLISH = {"ko", "zh", "ru"}


def language(code):
    """Language data; unknown codes become a generic language so the flow does not break."""
    code = (code or "")[:2].lower() if code not in LANGUAGES else code
    return LANGUAGES.get(code) or Language(code, code, code, code, code, None)


def easyocr_languages(code):
    """List of languages for `easyocr.Reader`."""
    main = language(code).easyocr
    if code in _NEEDS_ENGLISH:
        return [main, "en"]
    return [main]


def has_script(text, code):
    """True if the text has characters from the language's script (Latin languages accept anything)."""
    pattern = language(code).script
    return bool(pattern and re.search(pattern, text)) if pattern else True
