import os
import json
import hashlib
from logger_config import get_logger

logger = get_logger("Glossary")

# Lives at the project root, next to config.json
GLOSSARY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "glossary.json")


class Glossary:
    """
    User-editable glossary of fixed terms (glossary.json).
    Format: {"草薙": "Kusanagi", "魔王": "Demon King"}. Also accepts per-language-pair sections:
    {"ja-en": {"魔王": "Demon King"}, "ja-pt": {"魔王": "Demon King"}}.
    The file is re-read automatically when it changes, so it can be edited while the app is open.
    """
    def __init__(self, source, target, path=GLOSSARY_FILE):
        self.pair = f"{source}-{target}"
        self.path = path
        self._mtime = None
        self._terms = {}

    def _reload_if_changed(self):
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            if self._terms:
                self._terms = {}
            self._mtime = None
            return
        if mtime == self._mtime:
            return
        self._mtime = mtime
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("the content is not a JSON object")
        except Exception as e:
            logger.warning(f"Glossary ignored ({self.path}): {e}")
            self._terms = {}
            return

        terms = {}
        for key, value in data.items():
            if isinstance(value, dict):  # language-pair section
                if key == self.pair:
                    terms.update({k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str)})
            elif isinstance(value, str):
                terms[key] = value
        # Longest terms first, so "魔王軍" is handled before "魔王"
        self._terms = {k: terms[k] for k in sorted(terms, key=len, reverse=True) if k.strip() and terms[k].strip()}
        logger.info(f"Glossary loaded: {len(self._terms)} terms ({self.pair}).")

    def matches(self, text):
        """Glossary terms that appear in the text, as {original: translation}."""
        self._reload_if_changed()
        return {k: v for k, v in self._terms.items() if k in text}

    def latin_terms(self):
        """Terms written in Latin letters (character names that the game shows in English)."""
        self._reload_if_changed()
        return [k for k in self._terms if k.isascii() and any(c.isalpha() for c in k)]

    @staticmethod
    def fingerprint(matches):
        """Identifies the set of applied terms, so the cache does not reuse a stale translation."""
        if not matches:
            return ""
        raw = "|".join(f"{k}={v}" for k, v in sorted(matches.items()))
        return hashlib.blake2b(raw.encode("utf-8"), digest_size=4).hexdigest()


# ----------------------------------------------------------------------
# Editing (used by the glossary editor in the interface)
# ----------------------------------------------------------------------
def glossary_path(filename=None):
    """Full path of a glossary file at the project root (None = the default glossary.json)."""
    if not filename:
        return GLOSSARY_FILE
    return os.path.join(os.path.dirname(GLOSSARY_FILE), os.path.basename(filename))


def list_glossary_files():
    """Names of the glossary files at the project root (glossary*.json, except the example), default first."""
    root = os.path.dirname(GLOSSARY_FILE)
    names = []
    try:
        for name in os.listdir(root):
            low = name.lower()
            if low.startswith("glossary") and low.endswith(".json") and "example" not in low:
                names.append(name)
    except OSError:
        pass
    default = os.path.basename(GLOSSARY_FILE)
    return sorted(names, key=lambda n: (n != default, n.lower()))


def read_terms(path, source, target):
    """
    Terms of a file that apply to a language pair, as [(original, translation, in_pair_section)].
    Flat entries apply to every pair; the pair's own section ('ja-en') comes after them.
    """
    pair = f"{source}-{target}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    if not isinstance(data, dict):
        raise ValueError("the content is not a JSON object")
    rows = [(k, v, False) for k, v in data.items() if isinstance(v, str)]
    section = data.get(pair)
    if isinstance(section, dict):
        rows += [(k, v, True) for k, v in section.items() if isinstance(k, str) and isinstance(v, str)]
    return rows


def write_terms(path, source, target, rows):
    """
    Saves the terms edited for a language pair, keeping everything else in the file (other pairs' sections).
    `rows` is [(original, translation, in_pair_section)]: rows that were flat stay flat; the new ones go to the pair's section.
    """
    pair = f"{source}-{target}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except (FileNotFoundError, ValueError):
        data = {}

    kept = {k: v for k, v in data.items() if not isinstance(v, str) and k != pair}  # other pairs' sections
    flat = {o: t for o, t, in_pair in rows if not in_pair}
    section = {o: t for o, t, in_pair in rows if in_pair}

    out = dict(flat)
    out.update(kept)
    if section:
        out[pair] = section
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    logger.info(f"Glossary saved: {path} ({len(rows)} terms, {pair}).")
