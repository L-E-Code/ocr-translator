import os
import json
import time
from difflib import SequenceMatcher
from logger_config import get_logger

logger = get_logger("NameMemory")

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "known_names.json")


class NameMemory:
    """
    Memória dos nomes de personagens já lidos. O OCR erra o mesmo nome de formas diferentes
    como a leitura correta é a que mais
    se repete, uma leitura parecida com um nome mais frequente é trocada por ele.
    Nomes do glossário (em letras latinas) entram como referência confiável.
    """
    SNAP_RATIO = 0.78      # semelhança mínima para considerar que é o mesmo nome
    MIN_LENGTH = 4         # nomes mais curtos (Mia, Rin) nunca são trocados: seriam outro personagem
    SEED_COUNT = 50        # peso dos nomes vindos do glossário
    SAVE_INTERVAL = 10.0   # segundos entre gravações em disco

    def __init__(self, path=DEFAULT_PATH):
        self.path = path
        self.counts = {}
        self._last_save = 0.0
        self._dirty = False
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.counts = {k: int(v) for k, v in data.items() if isinstance(k, str) and isinstance(v, (int, float))}
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"Memória de nomes ignorada ({e}).")

    def save(self, force=False):
        if not self._dirty:
            return
        if not force and time.time() - self._last_save < self.SAVE_INTERVAL:
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.counts, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
            self._dirty = False
            self._last_save = time.time()
        except Exception as e:
            logger.warning(f"Não foi possível gravar a memória de nomes: {e}")

    def seed(self, names):
        """Registra nomes de referência (do glossário) com peso alto."""
        for name in names:
            if self.counts.get(name, 0) < self.SEED_COUNT:
                self.counts[name] = self.SEED_COUNT
                self._dirty = True

    def canonical(self, name):
        """Devolve a grafia mais provável do nome e contabiliza a leitura."""
        key = name.strip()
        if not key:
            return key
        if len(key) < self.MIN_LENGTH:
            self.counts[key] = self.counts.get(key, 0) + 1
            self._dirty = True
            return key
        own = self.counts.get(key, 0)
        best, best_ratio = None, 0.0
        for known, count in self.counts.items():
            if known == key or count < 2 or count <= own * 1.5:
                continue  # só adota nomes claramente mais frequentes que a leitura atual
            if abs(len(known) - len(key)) > 3 or len(known) < self.MIN_LENGTH:
                continue
            ratio = SequenceMatcher(None, key.lower(), known.lower()).ratio()
            if ratio >= self.SNAP_RATIO and ratio > best_ratio:
                best, best_ratio = known, ratio
        chosen = best or key
        self.counts[chosen] = self.counts.get(chosen, 0) + 1
        self._dirty = True
        self.save()
        return chosen
