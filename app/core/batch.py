"""
Batch translation of files: reads each page with the engine already loaded for the live mode, translates it and
collects the lines for a text report. No Qt in here, so it can be tested with a fake engine; the thread that runs it
is `ui/batch_worker.py`.
"""
import csv
import os
import time

from core import inputs, outputs
from core.reading_modes import MODE_DIALOGUE, MODE_DOCUMENT
from core.outputs import unique_path
from core.logger_config import get_logger

logger = get_logger("Batch")

DONE, PARTIAL, FAILED, CANCELLED = "done", "partial", "failed", "cancelled"

CSV_COLUMNS = ("file", "page", "speaker", "original", "translation", "confidence", "source", "engine")


def crop(image, region):
    """
    Cuts the region (x, y, width, height as fractions of the page) out of an RGB image. Returns (crop, offset_x,
    offset_y); the offsets bring the boxes read in the crop back to full-page coordinates. None = the whole page.
    """
    if not region:
        return image, 0, 0
    h, w = image.shape[:2]
    fx, fy, fw, fh = region
    x1 = min(max(int(round(fx * w)), 0), w - 1)
    y1 = min(max(int(round(fy * h)), 0), h - 1)
    x2 = min(max(int(round((fx + fw) * w)), x1 + 1), w)
    y2 = min(max(int(round((fy + fh) * h)), y1 + 1), h)
    return image[y1:y2, x1:x2], x1, y1


def output_path(src, out_dir, target_lang, ext):
    """'<stem>.<target>.<ext>' inside out_dir, with a '(2)' suffix instead of overwriting."""
    stem = os.path.splitext(os.path.basename(src))[0]
    return unique_path(os.path.join(out_dir, f"{stem}.{target_lang}.{ext.lstrip('.')}"))


def text_blocks_in_region(blocks, region, width, height):
    """The lines of a text layer whose centre falls inside the region (fractions of the page); all if no region."""
    if not region:
        return blocks
    fx, fy, fw, fh = region
    x1, y1, x2, y2 = fx * width, fy * height, (fx + fw) * width, (fy + fh) * height
    kept = []
    for box, text in blocks:
        cx = sum(p[0] for p in box) / len(box)
        cy = sum(p[1] for p in box) / len(box)
        if x1 <= cx <= x2 and y1 <= cy <= y2:
            kept.append((box, text))
    return kept


def rows_from_results(path, page, results, engine_name, source="ocr"):
    """One report row per dialogue block of a page; the speaker is the name read on the same page, if any."""
    results = results or []
    speaker = next((r["original"] for r in results if r.get("is_name")), "")
    return [
        {
            "file": os.path.basename(path),
            "page": page,
            "speaker": speaker,
            "original": r["original"],
            "translation": r.get("translation") or "",
            "confidence": round(float(r.get("confidence", 0.0)), 3),
            "source": source,
            "engine": engine_name,
        }
        for r in results if not r.get("is_name")
    ]


def is_failed_translation(text):
    """Failed translations come back as bracketed strings, such as '[Translation unavailable]'."""
    text = (text or "").strip()
    return text.startswith("[")


def run_batch(engine, files, region=None, share_context=True, on_progress=None, on_page=None, on_file=None,
              is_cancelled=None, render=None, out_dir=None, target_lang="", pdf_dpi=inputs.DEFAULT_PDF_DPI,
              pages=None, also_png=False, mode=MODE_DIALOGUE, always_ocr=False):
    """
    Translates every page of every file with `engine` (an OCRTranslator) and returns a summary:
    {'rows': [...], 'status': {path: DONE|PARTIAL|FAILED|CANCELLED}, 'errors': {path: message}, 'seconds': float,
     'engines': [...], 'images': [translated files written], 'outputs': {path: [its translated files]},
     'cancelled': bool}.

    With `render(image_rgb, results) -> image_rgb` and `out_dir`, the translated pages are also written in the format
    of each input (PNG, PDF, CBZ); `also_png` adds a PNG per page to a PDF or CBZ. `pdf_dpi` and `pages` ("1-5, 8")
    apply to PDFs. With `mode=MODE_DOCUMENT` every block of text of a page is translated (no speaker), and a PDF page that
    carries real text is read from its text layer instead of OCR, unless `always_ocr`. A file that stops halfway (cancel, error) still leaves what was done, named '….partial.*'.

    Callbacks: on_progress(file_n, file_count, page_n, page_count, label), on_page(path, page_index, rows),
    on_file(path, status, message). Cancelling is checked between pages.
    """
    started = time.time()
    summary = {"rows": [], "status": {}, "errors": {}, "engines": [], "images": [], "outputs": {}, "cancelled": False}
    engines_used = set()
    cancelled = is_cancelled or (lambda: False)
    notify_progress = on_progress or (lambda *a: None)
    notify_page = on_page or (lambda *a: None)
    notify_file = on_file or (lambda *a: None)

    def finish_file(path, status, message=""):
        summary["status"][path] = status
        if message:
            summary["errors"][path] = message
        notify_file(path, status, message)

    for file_n, path in enumerate(files, start=1):
        if cancelled():
            summary["cancelled"] = True
            finish_file(path, CANCELLED)
            continue
        # One region per file keeps the context lines of unrelated files apart; one shared region follows a story
        region_key = "batch" if share_context else f"file:{path}"
        pages_done = pages_failed = 0
        partial = False
        error = ""
        file_error = ""
        stopped = False
        writer = None
        try:
            page_pages = pages if inputs.is_pdf(path) else None  # the range is a PDF option
            page_count = inputs.count_pages(path, page_pages)
            if render and out_dir:
                writer = outputs.writer_for(path, out_dir, target_lang, also_png)
            use_layer = mode == MODE_DOCUMENT and not always_ocr
            for page_n, page in enumerate(inputs.iter_pages(path, pdf_dpi, page_pages, use_layer), start=1):
                if cancelled():
                    summary["cancelled"] = stopped = True
                    break
                notify_progress(file_n, len(files), page_n, page_count, page.label)
                try:
                    if page.text_blocks:  # real text of the PDF: no OCR
                        height, width = page.image.shape[:2]
                        blocks = text_blocks_in_region(page.text_blocks, region, width, height)
                        results = engine.process_text_blocks(blocks, width, region_key=region_key)
                        source = "pdf-text"
                    else:
                        image, offset_x, offset_y = crop(page.image, region)
                        extra = {} if mode == MODE_DIALOGUE else {"mode": mode}
                        results = engine.process_image(image, offset_x=offset_x, offset_y=offset_y,
                                                       region_key=region_key, scene_lock=False, **extra)
                        source = "ocr"
                    info = getattr(engine, "last_translation_info", None) or {}
                    engine_name = info.get("engine", "cache")
                    engines_used.add(engine_name)
                    rows = rows_from_results(path, page.index + 1, results, engine_name, source)
                except Exception as e:
                    logger.error(f"{page.label} page {page.index + 1}: {e}", exc_info=True)
                    pages_failed += 1
                    error = str(e)
                    continue
                pages_done += 1
                partial = partial or any(is_failed_translation(r["translation"]) for r in rows)
                summary["rows"].extend(rows)
                if writer:
                    try:
                        writer.add(page, render(page.image, results or []))
                    except Exception as e:  # the text is kept in the report even if the image could not be drawn
                        logger.error(f"{page.label}: could not write the page: {e}", exc_info=True)
                        partial = True
                        error = str(e)
                notify_page(path, page.index, rows)
        except Exception as e:  # the file could not be opened, or stopped being readable halfway
            logger.error(f"{os.path.basename(path)}: {e}", exc_info=True)
            file_error = str(e)
        finally:
            if writer:
                try:
                    writer.close(complete=not (stopped or file_error or pages_failed or error))
                except Exception as e:
                    logger.error(f"{os.path.basename(path)}: could not finish the output: {e}", exc_info=True)
                    partial = True
                    error = error or str(e)
                summary["images"].extend(writer.written)
                summary["outputs"][path] = list(writer.written)

        if file_error and pages_done == 0:
            finish_file(path, FAILED, file_error)
        elif stopped and pages_done == 0 and pages_failed == 0:
            finish_file(path, CANCELLED)
        elif pages_done == 0 and pages_failed:
            finish_file(path, FAILED, error)
        elif pages_failed or partial or stopped or file_error:
            finish_file(path, PARTIAL, error or file_error)
        else:
            finish_file(path, DONE)

    summary["seconds"] = time.time() - started
    summary["engines"] = sorted(engines_used)
    return summary


def _text_report(rows):
    blocks, last = [], None
    for row in rows:
        header = f"[{row['file']} — {row['page']}]"
        if row["speaker"]:
            header += f" {row['speaker']}"
        if header != last:
            blocks.append(header)
            last = header
        blocks.append(f"{row['original']}\n{row['translation']}\n")
    return "\n".join(blocks)


def write_text_report(rows, out_dir, txt=True, csv_file=True):
    """Writes translations.txt and/or translations.csv (UTF-8 with BOM so Excel opens it). Returns the paths."""
    os.makedirs(out_dir, exist_ok=True)
    written = []
    if txt:
        path = unique_path(os.path.join(out_dir, "translations.txt"))
        with open(path, "w", encoding="utf-8") as f:
            f.write(_text_report(rows))
        written.append(path)
    if csv_file:
        path = unique_path(os.path.join(out_dir, "translations.csv"))
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        written.append(path)
    return written
