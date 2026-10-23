"""
Idiomas suportados: nome na interface, nome usado no prompt da IA e códigos de cada motor.
"""
import re
from collections import namedtuple

Language = namedtuple("Language", "label prompt easyocr mymemory google script")

# `script`: expressão que um texto lido precisa conter para ser considerado do idioma (None = qualquer)
LANGUAGES = {
    "ja": Language("Japonês", "japonês", "ja", "ja-JP", "ja", r"[぀-ゟ゠-ヿ一-龯]"),
    "en": Language("Inglês", "inglês", "en", "en-US", "en", None),
    "pt": Language("Português (BR)", "português do Brasil", "pt", "pt-BR", "pt", None),
}

# Alfabetos que o EasyOCR só lê junto com o inglês (os latinos funcionam sozinhos)
_NEEDS_ENGLISH = {"ko", "zh", "ru"}


def language(code):
    """Dados do idioma; códigos desconhecidos viram um idioma genérico para não quebrar o fluxo."""
    code = (code or "")[:2].lower() if code not in LANGUAGES else code
    return LANGUAGES.get(code) or Language(code, code, code, code, code, None)


def easyocr_languages(code):
    """Lista de idiomas para o `easyocr.Reader`."""
    main = language(code).easyocr
    if code in _NEEDS_ENGLISH:
        return [main, "en"]
    return [main]


def has_script(text, code):
    """True se o texto tem caracteres do alfabeto do idioma (idiomas latinos aceitam qualquer um)."""
    pattern = language(code).script
    return bool(pattern and re.search(pattern, text)) if pattern else True
