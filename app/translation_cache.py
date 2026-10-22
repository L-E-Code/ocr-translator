import os
import sqlite3
import threading
import time
from logger_config import get_logger

logger = get_logger("TranslationCache")

DEFAULT_DB_PATH = os.path.join("cache", "translations.db")


class PersistentTranslationCache:
    """
    Cache de traduções em SQLite, compartilhado entre execuções.
    Chave: (idioma origem, idioma destino, tipo, texto original).
    Mantém no máximo `max_entries` linhas, descartando as menos usadas recentemente.
    """
    def __init__(self, path=DEFAULT_DB_PATH, max_entries=20000):
        self.max_entries = max_entries
        self._lock = threading.Lock()
        self._conn = None
        try:
            folder = os.path.dirname(path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            self._conn = sqlite3.connect(path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS translations ("
                "src TEXT, tgt TEXT, kind TEXT, original TEXT, translated TEXT, last_used REAL, "
                "PRIMARY KEY (src, tgt, kind, original))"
            )
            self._conn.commit()
        except Exception as e:
            logger.warning(f"Cache em disco indisponível ({e}). Usando apenas memória.")
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
            logger.warning(f"Falha ao ler cache: {e}")
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
                self._conn.execute(
                    "DELETE FROM translations WHERE rowid IN (SELECT rowid FROM translations "
                    "ORDER BY last_used DESC LIMIT -1 OFFSET ?)",
                    (self.max_entries,),
                )
                self._conn.commit()
        except Exception as e:
            logger.warning(f"Falha ao gravar cache: {e}")

    def clear(self):
        if not self._conn:
            return
        try:
            with self._lock:
                self._conn.execute("DELETE FROM translations")
                self._conn.commit()
        except Exception as e:
            logger.warning(f"Falha ao limpar cache: {e}")
