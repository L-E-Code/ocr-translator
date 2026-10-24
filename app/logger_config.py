import os
import sys
import logging
import subprocess
from datetime import datetime
from pathlib import Path

# Project root (one level above the app folder)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "log"

_CURRENT_LOG_FILE = None
_LOGGER_INITIALIZED = False


class SafeStreamHandler(logging.StreamHandler):
    """
    Console handler that is safe against UnicodeEncodeError on Windows (cp1252/cp850).
    Characters the current terminal cannot display do not cause a crash.
    """
    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            if stream is None:
                return
            try:
                stream.write(msg + self.terminator)
                self.flush()
            except UnicodeEncodeError:
                # If the console does not support kanji/exotic characters, replaces the unrepresentable ones
                encoding = getattr(stream, "encoding", "utf-8") or "utf-8"
                safe_msg = msg.encode(encoding, errors="replace").decode(encoding, errors="replace")
                stream.write(safe_msg + self.terminator)
                self.flush()
        except Exception:
            self.handleError(record)


class _StreamToLogger:
    """
    Redirects stream output (stdout/stderr and legacy prints)
    to the log file with strict protection against recursion.
    """
    def __init__(self, logger, level, original_stream=None):
        self.logger = logger
        self.level = level
        self.original_stream = original_stream
        self.buffer = ""
        self._in_write = False

    def write(self, message):
        if self._in_write:
            if self.original_stream:
                try:
                    self.original_stream.write(message)
                except Exception:
                    pass
            return

        if not message:
            return

        self._in_write = True
        try:
            # Sends to the original terminal stream if it exists
            if self.original_stream:
                try:
                    self.original_stream.write(message)
                    self.original_stream.flush()
                except UnicodeEncodeError:
                    encoding = getattr(self.original_stream, "encoding", "utf-8") or "utf-8"
                    safe_msg = message.encode(encoding, errors="replace").decode(encoding, errors="replace")
                    self.original_stream.write(safe_msg)
                    self.original_stream.flush()
                except Exception:
                    pass

            # Accumulates and splits by lines to send to the log
            self.buffer += message
            while "\n" in self.buffer:
                line, self.buffer = self.buffer.split("\n", 1)
                line = line.strip()
                if line:
                    self.logger.log(self.level, line)
        finally:
            self._in_write = False

    def flush(self):
        if self._in_write:
            return

        self._in_write = True
        try:
            if self.buffer.strip():
                self.logger.log(self.level, self.buffer.strip())
                self.buffer = ""
            if self.original_stream:
                try:
                    self.original_stream.flush()
                except Exception:
                    pass
        finally:
            self._in_write = False


def _cleanup_old_logs(max_files=50):
    """Keeps only the most recent log files so they do not pile up on disk."""
    try:
        log_files = sorted(
            LOG_DIR.glob("app_*.log"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        for old_file in log_files[max_files:]:
            try:
                old_file.unlink()
            except Exception:
                pass
    except Exception:
        pass


def setup_logger():
    """
    Initializes the OCR Translator logging system.
    Creates a new .log file with date and time on every startup, in the 'log/' folder.
    """
    global _CURRENT_LOG_FILE, _LOGGER_INITIALIZED

    if _LOGGER_INITIALIZED:
        return logging.getLogger("OCRTranslator")

    # Configures Python streams to safe UTF-8 if available
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Makes sure the log/ folder exists
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Preventive cleanup of very old logs (keeps the last 50)
    _cleanup_old_logs(max_files=50)

    # Builds the file name with the startup timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_filename = f"app_{timestamp}.log"
    _CURRENT_LOG_FILE = LOG_DIR / log_filename

    # Root Logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Limpa handlers anteriores
    root_logger.handlers.clear()

    # Format with date, time, level and module
    log_format = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)-7s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 1. File Handler (UTF-8 required for Japanese and accents)
    file_handler = logging.FileHandler(
        filename=str(_CURRENT_LOG_FILE),
        encoding="utf-8",
        mode="w"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(log_format)
    root_logger.addHandler(file_handler)

    # 2. Safe Console Handler for the terminal
    if sys.stdout and hasattr(sys.stdout, "write"):
        console_handler = SafeStreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(log_format)
        root_logger.addHandler(console_handler)

    # 3. Global hook to catch unhandled exceptions (avoids silent shutdowns)
    def handle_unhandled_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        crash_logger = logging.getLogger("CRASH")
        crash_logger.critical("Unhandled exception detected in the system:", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_unhandled_exception

    # 4. Redirects stdout and stderr to capture legacy prints
    orig_stdout = sys.stdout
    orig_stderr = sys.stderr

    stdout_logger = logging.getLogger("STDOUT")
    stderr_logger = logging.getLogger("STDERR")

    sys.stdout = _StreamToLogger(stdout_logger, logging.INFO, orig_stdout)
    sys.stderr = _StreamToLogger(stderr_logger, logging.ERROR, orig_stderr)

    _LOGGER_INITIALIZED = True

    app_logger = logging.getLogger("OCRTranslator")
    app_logger.info("=" * 60)
    app_logger.info("Starting OCR Translator session")
    app_logger.info(f"Log file: {_CURRENT_LOG_FILE.name}")
    app_logger.info(f"Root directory: {PROJECT_ROOT}")
    app_logger.info(f"Startup date and time: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    app_logger.info("=" * 60)

    return app_logger


def get_logger(name="OCRTranslator"):
    """Returns a named logger instance."""
    if not _LOGGER_INITIALIZED:
        setup_logger()
    return logging.getLogger(name)


def get_current_log_path():
    """Returns the path of the current session's log file."""
    return _CURRENT_LOG_FILE


def open_log_folder():
    """Opens the log folder in Windows File Explorer."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(LOG_DIR))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(LOG_DIR)])
        else:
            subprocess.Popen(["xdg-open", str(LOG_DIR)])
        return True
    except Exception as e:
        get_logger().error(f"Error opening the log folder: {e}")
        return False

