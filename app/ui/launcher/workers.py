"""Background threads of the launcher (model loading, runtime probe, update check, GPU probe)."""
from PyQt6.QtCore import QThread, pyqtSignal

from core import config_manager, updater
from core.device import available_gpus, installed_gpu_names
from core.logger_config import get_logger

logger = get_logger("Launcher")


class ModelInitWorker(QThread):
    """
    Background thread that initializes the OCR/Translation models
    without freezing the user interface.
    """
    finished_signal = pyqtSignal(object)
    error_signal = pyqtSignal(str)

    def __init__(self, source_lang, target_lang, device_preference="auto"):
        super().__init__()
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.device_preference = device_preference

    def run(self):
        logger.info(f"ModelInitWorker: Loading OCR/Translation engines ({self.source_lang} -> {self.target_lang})...")
        try:
            from core.ocr import OCRTranslator  # heavy import: only here, outside the interface thread
            config = config_manager.load_config()
            regions = [config.get("last_custom_roi")] + list(config.get("extra_regions") or [])
            engine = OCRTranslator(
                source_lang=self.source_lang,
                target_lang=self.target_lang,
                device_preference=self.device_preference,
                groq_models=config.get("groq_models"),
                context_lines=config.get("translation_context", 3),
                warm_shapes=[(r["width"], r["height"]) for r in regions if r and r.get("width") and r.get("height")],
            )
            logger.info("ModelInitWorker: Engines initialized successfully.")
            self.finished_signal.emit(engine)
        except Exception as e:
            logger.error(f"ModelInitWorker: Failed to load engines: {e}", exc_info=True)
            self.error_signal.emit(str(e))


class RuntimeProbe(QThread):
    """
    Imports PyTorch and the OCR engine in the background right after the window opens, and reports the usable
    GPUs. By the time the user clicks start, the heavy libraries are usually already loaded.
    """
    gpus_ready = pyqtSignal(list)

    def run(self):
        try:
            self.gpus_ready.emit(available_gpus())
        except Exception as e:
            logger.warning(f"Failed to query the GPUs: {e}")
            self.gpus_ready.emit([])
        try:
            from core import ocr  # noqa: F401  (warms up the OCR imports for the start of the translation)
        except Exception as e:
            logger.warning(f"OCR preload failed: {e}")


class UpdateCheck(QThread):
    """Asks GitHub for the latest release in the background (only reads the version)."""
    found = pyqtSignal(dict)

    def run(self):
        release = updater.check_for_update()
        if release:
            self.found.emit(release)


class GpuProbe(QThread):
    """Queries the system's graphics cards without freezing the interface."""
    finished_signal = pyqtSignal(list)

    def run(self):
        self.finished_signal.emit(installed_gpu_names())
