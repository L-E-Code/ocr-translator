import os
import json
import hashlib
from logger_config import get_logger

logger = get_logger("Glossary")

# Fica na raiz do projeto, ao lado do config.json
GLOSSARY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "glossary.json")


class Glossary:
    """
    Glossário de termos fixos editável pelo usuário (glossary.json).
    Formato: {"草薙": "Kusanagi", "魔王": "Rei Demônio"}. Aceita também seções por par de idiomas:
    {"ja-en": {"魔王": "Demon King"}, "ja-pt": {"魔王": "Rei Demônio"}}.
    O arquivo é relido sozinho quando muda, então dá para editar com o app aberto.
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
                raise ValueError("o conteúdo não é um objeto JSON")
        except Exception as e:
            logger.warning(f"Glossário ignorado ({self.path}): {e}")
            self._terms = {}
            return

        terms = {}
        for key, value in data.items():
            if isinstance(value, dict):  # seção por par de idiomas
                if key == self.pair:
                    terms.update({k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str)})
            elif isinstance(value, str):
                terms[key] = value
        # Termos mais longos primeiro, para "魔王軍" ser tratado antes de "魔王"
        self._terms = {k: terms[k] for k in sorted(terms, key=len, reverse=True) if k.strip() and terms[k].strip()}
        logger.info(f"Glossário carregado: {len(self._terms)} termos ({self.pair}).")

    def matches(self, text):
        """Termos do glossário que aparecem no texto, como {original: tradução}."""
        self._reload_if_changed()
        return {k: v for k, v in self._terms.items() if k in text}

    def latin_terms(self):
        """Termos escritos em letras latinas (nomes de personagens que o jogo mostra em inglês)."""
        self._reload_if_changed()
        return [k for k in self._terms if k.isascii() and any(c.isalpha() for c in k)]

    @staticmethod
    def fingerprint(matches):
        """Identifica o conjunto de termos aplicado, para o cache não reaproveitar tradução desatualizada."""
        if not matches:
            return ""
        raw = "|".join(f"{k}={v}" for k, v in sorted(matches.items()))
        return hashlib.blake2b(raw.encode("utf-8"), digest_size=4).hexdigest()
