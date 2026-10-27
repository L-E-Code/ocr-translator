import os
import sqlite3
import threading
import time
from core.logger_config import get_logger
from core.paths import root_path

logger = get_logger("TranslationCache")

DEFAULT_DB_PATH = root_path("cache", "translations.db")


class PersistentTranslationCache:
    """
    SQLite translation cache, shared between runs.
    Key: (source language, target language, kind, original text).
    Keeps at most `max_entries` rows, discarding the least recently used.
    """
    def __init__(self, path=DEFAULT_DB_PATH, max_entries=20000):
        self.max_entries = max_entries
        # Trimming sorts the table, so it runs every ~1% of the limit instead of on every write
        self._prune_every = max(1, max_entries // 100)
        self._puts = 0
        self._lock = threading.Lock()
        self._conn = None
        try:
            folder = os.path.dirname(path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            self._conn = sqlite3.connect(path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            # With WAL, NORMAL only syncs to disk at checkpoints: a commit per read/write no longer waits for the disk
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS translations ("
                "src TEXT, tgt TEXT, kind TEXT, original TEXT, translated TEXT, last_used REAL, "
                "PRIMARY KEY (src, tgt, kind, original))"
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS translations_last_used ON translations(last_used)")
            self._conn.commit()
        except Exception as e:
            logger.warning(f"Disk cache unavailable ({e}). Using memory only.")
            self._conn = None

    def get(self, src, tgt, kind, original):
        if not self._conn:
            return None
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT translated FROM translations WHERE src=? AND tgt=? AND kind=? AND original=?",
                    (src, tgt, kind, original),
                ).fetchone()
                if row:
                    self._conn.execute(
                        "UPDATE translations SET last_used=? WHERE src=? AND tgt=? AND kind=? AND original=?",
                        (time.time(), src, tgt, kind, original),
                    )
                    self._conn.commit()
                    return row[0]
        except Exception as e:
            logger.warning(f"Failed to read cache: {e}")
        return None

    def put(self, src, tgt, kind, original, translated):
        if not self._conn:
            return
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO translations VALUES (?, ?, ?, ?, ?, ?)",
                    (src, tgt, kind, original, translated, time.time()),
                )
                self._puts += 1
                if self._puts % self._prune_every == 0:
                    self._conn.execute(
                        "DELETE FROM translations WHERE rowid IN (SELECT rowid FROM translations "
                        "ORDER BY last_used DESC LIMIT -1 OFFSET ?)",
                        (self.max_entries,),
                    )
                self._conn.commit()
        except Exception as e:
            logger.warning(f"Failed to write cache: {e}")

    def clear(self):
        if not self._conn:
            return
        try:
            with self._lock:
                self._conn.execute("DELETE FROM translations")
                self._conn.commit()
        except Exception as e:
            logger.warning(f"Failed to clear cache: {e}")
