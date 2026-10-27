import os
import json
import time
from difflib import SequenceMatcher
from core.logger_config import get_logger
from core.paths import root_path

logger = get_logger("NameMemory")

DEFAULT_PATH = root_path("cache", "known_names.json")


class NameMemory:
    """
    Memory of the character names already read. OCR misreads the same name in different ways,
    and since the correct reading is the one that repeats the most, a reading similar to a
    more frequent name is replaced by it.
    Glossary names (in Latin letters) enter as a trusted reference.
    """
    SNAP_RATIO = 0.78      # minimum similarity to consider it the same name
    MIN_LENGTH = 4         # shorter names (Mia, Rin) are never replaced: they would be another character
    SEED_COUNT = 50        # weight of names coming from the glossary
    SAVE_INTERVAL = 10.0   # seconds between disk writes

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
            logger.warning(f"Name memory ignored ({e}).")

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
            logger.warning(f"Could not write the name memory: {e}")

    def seed(self, names):
        """Registers reference names (from the glossary) with high weight."""
        for name in names:
            if self.counts.get(name, 0) < self.SEED_COUNT:
                self.counts[name] = self.SEED_COUNT
                self._dirty = True

    def canonical(self, name):
        """Returns the most likely spelling of the name and counts the reading."""
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
                continue  # only adopts names that are clearly more frequent than the current reading
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
