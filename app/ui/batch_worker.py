"""Thread that translates a batch of files without freezing the interface (the logic is in core/batch.py)."""
from PyQt6.QtCore import QThread, pyqtSignal

from core import batch, inputs
from core.reading_modes import MODE_DIALOGUE
from core.logger_config import get_logger

logger = get_logger("Batch")


class BatchWorker(QThread):
    # file n, file count, page n, page count, label of the page
    progress = pyqtSignal(int, int, int, int, str)
    page_done = pyqtSignal(str, int, list)  # path, page index, report rows of the page
    file_done = pyqtSignal(str, str, str)  # path, status (batch.DONE...), message
    finished_signal = pyqtSignal(dict)  # the summary of batch.run_batch

    def __init__(self, engine, files, region=None, share_context=True, render=None, out_dir=None, target_lang="",
                 pdf_dpi=inputs.DEFAULT_PDF_DPI, pages=None, also_png=False,
                 mode=MODE_DIALOGUE, always_ocr=False):
        super().__init__()
        self.engine = engine
        self.files = list(files)
        self.region = region
        self.share_context = share_context
        self.render = render
        self.out_dir = out_dir
        self.target_lang = target_lang
        self.pdf_dpi = pdf_dpi
        self.pages = pages
        self.also_png = also_png
        self.mode = mode
        self.always_ocr = always_ocr
        self._cancel = False

    def cancel(self):
        """Stops between pages; what was already translated is kept."""
        self._cancel = True

    def run(self):
        try:
            summary = batch.run_batch(
                self.engine, self.files, region=self.region, share_context=self.share_context,
                on_progress=self.progress.emit,
                on_page=lambda path, index, rows: self.page_done.emit(path, index, rows),
                on_file=self.file_done.emit,
                is_cancelled=lambda: self._cancel,
                render=self.render, out_dir=self.out_dir, target_lang=self.target_lang,
                pdf_dpi=self.pdf_dpi, pages=self.pages, also_png=self.also_png,
                mode=self.mode, always_ocr=self.always_ocr,
            )
        except Exception as e:  # run_batch handles each file; this is a bug, but the dialog must not hang
            logger.error(f"BatchWorker failed: {e}", exc_info=True)
            summary = {"rows": [], "status": {}, "errors": {"": str(e)}, "engines": [], "images": [], "outputs": {}, "cancelled": False, "seconds": 0.0}
        self.finished_signal.emit(summary)
