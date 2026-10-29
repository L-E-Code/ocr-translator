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
    "zh-tw": Language("Chinese (Traditional)", "Traditional Chinese", "ch_tra", "zh-TW", "zh-TW", r"[㐀-鿿]"),
}

# Languages whose EasyOCR reader is loaded together with English (games mix Latin names and numbers in the text)
_WITH_ENGLISH = {"zh-tw"}


def language_code(code):
    """Code as the app stores it: an exact key of LANGUAGES, otherwise the first two letters (e.g. 'pt-BR' -> 'pt')."""
    code = code or ""
    return code if code in LANGUAGES else code[:2].lower()


def language(code):
    """Language data; unknown codes become a generic language so the flow does not break."""
    code = language_code(code)
    return LANGUAGES.get(code) or Language(code, code, code, code, code, None)


def easyocr_languages(code):
    """List of languages for `easyocr.Reader`."""
    main = language(code).easyocr
    return [main, "en"] if language_code(code) in _WITH_ENGLISH else [main]


def has_script(text, code):
    """True if the text has characters from the language's script (Latin languages accept anything)."""
    pattern = language(code).script
    return bool(pattern and re.search(pattern, text)) if pattern else True
