import os
import sys
import logging
import subprocess
from datetime import datetime
from pathlib import Path

# Raiz do projeto (um nível acima da pasta app)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "log"

_CURRENT_LOG_FILE = None
_LOGGER_INITIALIZED = False


class SafeStreamHandler(logging.StreamHandler):
    """
    Handler para console seguro contra UnicodeEncodeError no Windows (cp1252/cp850).
    Caracteres incompatíveis com o terminal atual não causam quebra.
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
                # Se o console não suporta kanji/caracteres exóticos, substitui os irrepresentáveis
                encoding = getattr(stream, "encoding", "utf-8") or "utf-8"
                safe_msg = msg.encode(encoding, errors="replace").decode(encoding, errors="replace")
                stream.write(safe_msg + self.terminator)
                self.flush()
        except Exception:
            self.handleError(record)


class _StreamToLogger:
    """
    Redireciona saídas de streams (stdout/stderr e prints legados)
    para o arquivo de log com proteção estrita contra recursão.
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
            # Envia para o stream original no terminal se existir
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

            # Acumula e quebra por linhas para enviar ao log
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
    """Mantém apenas os arquivos de log mais recentes para não acumular lixo no disco."""
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
    Inicializa o sistema de logging do OCR Translator.
    Cria um novo arquivo .log com data e hora a cada inicialização na pasta 'log/'.
    """
    global _CURRENT_LOG_FILE, _LOGGER_INITIALIZED

    if _LOGGER_INITIALIZED:
        return logging.getLogger("OCRTranslator")

    # Configura streams do Python para UTF-8 seguro se disponível
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

    # Garante a existência da pasta log/
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Limpeza preventiva de logs muito antigos (mantém os últimos 50)
    _cleanup_old_logs(max_files=50)

    # Gera o nome do arquivo com timestamp da inicialização
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_filename = f"app_{timestamp}.log"
    _CURRENT_LOG_FILE = LOG_DIR / log_filename

    # Configuração do Logger Raiz
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Limpa handlers anteriores
    root_logger.handlers.clear()

    # Formato com data, hora, nível e módulo
    log_format = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)-7s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 1. File Handler (UTF-8 obrigatório para japonês e acentos)
    file_handler = logging.FileHandler(
        filename=str(_CURRENT_LOG_FILE),
        encoding="utf-8",
        mode="w"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(log_format)
    root_logger.addHandler(file_handler)

    # 2. Console Handler seguro para terminal
    if sys.stdout and hasattr(sys.stdout, "write"):
        console_handler = SafeStreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(log_format)
        root_logger.addHandler(console_handler)

    # 3. Gancho global para capturar exceções não tratadas (evita fechamentos silenciosos)
    def handle_unhandled_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        crash_logger = logging.getLogger("CRASH")
        crash_logger.critical("Exceção não tratada detectada no sistema:", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_unhandled_exception

    # 4. Redirecionamento de stdout e stderr para capturar prints legados
    orig_stdout = sys.stdout
    orig_stderr = sys.stderr

    stdout_logger = logging.getLogger("STDOUT")
    stderr_logger = logging.getLogger("STDERR")

    sys.stdout = _StreamToLogger(stdout_logger, logging.INFO, orig_stdout)
    sys.stderr = _StreamToLogger(stderr_logger, logging.ERROR, orig_stderr)

    _LOGGER_INITIALIZED = True

    app_logger = logging.getLogger("OCRTranslator")
    app_logger.info("=" * 60)
    app_logger.info("Iniciando sessão do OCR Translator")
    app_logger.info(f"Arquivo de log: {_CURRENT_LOG_FILE.name}")
    app_logger.info(f"Diretório raiz: {PROJECT_ROOT}")
    app_logger.info(f"Data e Hora de Inicialização: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    app_logger.info("=" * 60)

    return app_logger


def get_logger(name="OCRTranslator"):
    """Retorna uma instância nomeada de logger."""
    if not _LOGGER_INITIALIZED:
        setup_logger()
    return logging.getLogger(name)


def get_current_log_path():
    """Retorna o caminho do arquivo de log da sessão atual."""
    return _CURRENT_LOG_FILE


def open_log_folder():
    """Abre a pasta de logs no Explorador de Arquivos do Windows."""
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
        get_logger().error(f"Erro ao abrir pasta de logs: {e}")
        return False

