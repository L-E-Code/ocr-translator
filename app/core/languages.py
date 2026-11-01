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
    "es": Language("Spanish", "Spanish", "es", "es-ES", "es", None),
    "zh-tw": Language("Chinese (Traditional)", "Traditional Chinese", None, "zh-TW", "zh-TW", r"[㐀-鿿]"),
    "zh-cn": Language("Chinese (Simplified)", "Simplified Chinese", None, "zh-CN", "zh-CN", r"[㐀-鿿]"),
    "ko": Language("Korean", "Korean", None, "ko-KR", "ko", r"[가-힯ᄀ-ᇿ㄰-㆏]"),
}

_RAPIDOCR = {"zh-cn": "CH", "zh-tw": "CH", "ko": "KOREAN", "en": "LATIN", "pt": "LATIN", "es": "LATIN"}

# Languages that put spaces between words: pieces of one line are joined with a space
_SPACED = {"ko", "en", "pt", "es"}


def language_code(code):
    """Code as the app stores it: an exact key of LANGUAGES, otherwise the first two letters (e.g. 'pt-BR' -> 'pt')."""
    code = code or ""
    return code if code in LANGUAGES else code[:2].lower()


def language(code):
    """Language data; unknown codes become a generic language so the flow does not break."""
    code = language_code(code)
    return LANGUAGES.get(code) or Language(code, code, code, code, code, None)


def rapidocr_language(code):
    """Name of the RapidOCR recognizer for a language, or None if the language is read by another engine."""
    return _RAPIDOCR.get(language_code(code))


def joins_with_space(code):
    """True if the language separates words with spaces (unlike Chinese and Japanese)."""
    return language_code(code) in _SPACED


def easyocr_languages(code):
    """List of languages for `easyocr.Reader`."""
    return [language(code).easyocr]


def has_script(text, code):
    """True if the text has characters from the language's script (Latin languages accept anything)."""
    pattern = language(code).script
    return bool(pattern and re.search(pattern, text)) if pattern else True
