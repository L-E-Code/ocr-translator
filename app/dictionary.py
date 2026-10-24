"""
Japanese word dictionary for the panel: splits the sentence into words (fugashi + UniDic)
and looks up the reading and meaning in JMdict (jamdict). The dependencies are optional:
without them the panel shows the original text normally, with no clickable words.
"""
import re
import threading
from collections import namedtuple

from logger_config import get_logger

logger = get_logger("Dictionary")

Word = namedtuple("Word", "surface lemma reading clickable")
Entry = namedtuple("Entry", "reading pos glosses")

# Conjugated verbs and adjectives: the ending (ます, た, ない, て...) is part of the same word
_STEMS = {"動詞", "形容詞", "助動詞"}
_NOT_WORDS = {"補助記号", "空白"}
MAX_SENSES = 3
MAX_GLOSSES = 3


class WordDictionary:
    def __init__(self):
        self._tagger = None
        self._jmdict = None
        self._ready = threading.Event()
        self._failed = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def load_async(self):
        """Loads the tokenizer and the dictionary in the background (takes about 1 s)."""
        if self._ready.is_set() or getattr(self, "_thread", None):
            return
        self._thread = threading.Thread(target=self._load, name="dictionary-load", daemon=True)
        self._thread.start()

    def _load(self):
        try:
            import fugashi
            from jamdict import Jamdict
            self._tagger = fugashi.Tagger()
            self._jmdict = Jamdict()
            self._jmdict.lookup("日本")  # opens the database right at load time
            logger.info("JMdict dictionary ready.")
        except Exception as e:
            self._failed = True
            logger.warning(f"Dictionary unavailable ({e}). Install 'fugashi', 'unidic-lite', 'jamdict' and "
                           f"'jamdict-data-fix' to see the meaning of the words.")
        finally:
            self._ready.set()

    @property
    def available(self):
        """True once the dictionary has loaded and can be used."""
        return self._ready.is_set() and not self._failed

    # ------------------------------------------------------------------
    def words(self, text):
        """Splits the text into words [Word]; an empty list means it cannot be segmented."""
        if not self.available or not text:
            return []
        words = []
        last_pos = ""
        for tok in self._tagger(text):
            feat = tok.feature
            pos = getattr(feat, "pos1", "") or ""
            lemma = (getattr(feat, "lemma", None) or tok.surface).split("-")[0]
            reading = getattr(feat, "kana", None) or ""
            attaches = pos == "助動詞" or (pos == "助詞" and getattr(feat, "pos2", "") == "接続助詞")
            if words and attaches and last_pos in _STEMS:
                prev = words[-1]
                words[-1] = Word(prev.surface + tok.surface, prev.lemma, prev.reading, True)
            else:
                words.append(Word(tok.surface, lemma, reading, pos not in _NOT_WORDS and bool(tok.surface.strip())))
            last_pos = pos
        return words

    def lookup(self, word):
        """JMdict entries for the word (dictionary form first, then the original spelling)."""
        if not self.available:
            return []
        entries = []
        with self._lock:
            for key in dict.fromkeys((word.lemma, word.surface)):
                try:
                    result = self._jmdict.lookup(key)
                except Exception as e:
                    logger.debug(f"Failed to look up '{key}': {e}")
                    continue
                if result.entries:
                    for entry in result.entries[:4]:
                        kana = "・".join(k.text for k in entry.kana_forms[:2])
                        for sense in entry.senses[:MAX_SENSES]:
                            glosses = [g.text for g in sense.gloss[:MAX_GLOSSES]]
                            pos = re.sub(r"\s*\([a-z]+\)$", "", sense.pos[0]) if sense.pos else ""
                            entries.append(Entry(kana, pos, glosses))
                    break
        return entries


_instance = None


def get_dictionary():
    """Dictionary shared by the whole program (created on first call)."""
    global _instance
    if _instance is None:
        _instance = WordDictionary()
    return _instance
