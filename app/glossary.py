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
