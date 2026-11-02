"""
Input files of a batch translation. Every file becomes a sequence of `Page` objects, so the rest of the pipeline only
knows about pages: still images (one page), TIFF (one page per frame), GIF (first frame), PDF (rendered page by page)
and CBZ (the images of a comic archive).
"""
import os
import re
import zipfile
from collections import namedtuple

import cv2
import numpy as np

# image: RGB numpy array; text_blocks: None, or [(box, text)] when the page carries its own text (PDF text layer);
# size: (width, height) in PDF points for a PDF page, so the translated PDF keeps the page size.
# `index` is the position in the file (0-based, the real page number - 1), `count` the number of pages being read.
Page = namedtuple("Page", "source index count label image text_blocks size", defaults=(None,))

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
FRAME_EXTENSIONS = (".tif", ".tiff", ".gif")
PDF_EXTENSIONS = (".pdf",)
CBZ_EXTENSIONS = (".cbz",)
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS + FRAME_EXTENSIONS + PDF_EXTENSIONS + CBZ_EXTENSIONS

PDF_DPIS = (100, 150, 300)
DEFAULT_PDF_DPI = 150
PDF_MAX_SIDE = 2500  # longest side of a rendered page in pixels: bounds the OCR time of large formats
MAX_ARCHIVE_IMAGE_BYTES = 100 * 1024 * 1024  # a member of a CBZ larger than this is refused
MIN_TEXT_LAYER_CHARS = 15  # a PDF page with fewer characters of text than this is a picture (a scan)


def _ext(path):
    return os.path.splitext(path)[1].lower()


def is_supported(path):
    return _ext(path) in SUPPORTED_EXTENSIONS


def is_pdf(path):
    return _ext(path) in PDF_EXTENSIONS


def is_archive(path):
    return _ext(path) in CBZ_EXTENSIONS


def natural_key(path):
    """Sort key that orders 'shot2.png' before 'shot10.png' (story order for numbered screenshots)."""
    name = os.path.basename(path).lower()
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)]


def list_folder(folder):
    """Supported files directly inside a folder (not recursive), in natural name order."""
    names = [os.path.join(folder, n) for n in os.listdir(folder)]
    return sorted((p for p in names if os.path.isfile(p) and is_supported(p)), key=natural_key)


# ----------------------------------------------------------------------
# Page range ("1-5, 8, 12-")
# ----------------------------------------------------------------------
def parse_ranges(text):
    """
    Syntax of a page range, 1-based: '3', '1-5', '12-' (to the end), '-4' (up to page 4), separated by commas.
    Returns [(first, last_or_None)]; None for an empty text (every page). Raises ValueError on a malformed one.
    """
    text = (text or "").strip()
    if not text:
        return None
    ranges = []
    for part in re.split(r"[,;]", text):
        part = part.strip()
        if not part:
            continue
        single = re.fullmatch(r"(\d+)", part)
        span = re.fullmatch(r"(\d*)\s*-\s*(\d*)", part)
        if single:
            first = last = int(single.group(1))
        elif span and (span.group(1) or span.group(2)):
            first = int(span.group(1)) if span.group(1) else 1
            last = int(span.group(2)) if span.group(2) else None
        else:
            raise ValueError(f"Invalid page range: '{part}'")
        if first < 1 or (last is not None and last < first):
            raise ValueError(f"Invalid page range: '{part}'")
        ranges.append((first, last))
    if not ranges:
        raise ValueError(f"Invalid page range: '{text}'")
    return ranges


def select_pages(text, count):
    """0-based indexes of the pages chosen by `text` in a file of `count` pages (all of them for an empty text)."""
    ranges = parse_ranges(text)
    if ranges is None:
        return list(range(count))
    chosen = set()
    for first, last in ranges:
        chosen.update(range(first - 1, min(last if last is not None else count, count)))
    if not chosen:
        raise ValueError(f"No page of '{text}' exists: the file has {count} pages")
    return sorted(chosen)


# ----------------------------------------------------------------------
# Reading
# ----------------------------------------------------------------------
def _decode(data, name):
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR) if len(data) else None
    if image is None:
        raise ValueError(f"Could not read the image: {name}")
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def load_image(path):
    """
    Reads an image as RGB. Goes through `np.fromfile` because `cv2.imread` fails on Windows for paths with accents
    (C:\\Users\\João\\Área de Trabalho\\...).
    """
    return _decode(np.fromfile(path, dtype=np.uint8), os.path.basename(path))


def _open_pdf(path):
    import pypdfium2 as pdfium
    try:
        return pdfium.PdfDocument(path)
    except pdfium.PdfiumError as e:
        if "password" in str(e).lower():
            raise ValueError(f"The PDF is protected by a password: {os.path.basename(path)}") from e
        raise ValueError(f"Could not open the PDF {os.path.basename(path)}: {e}") from e


def _archive_images(zf):
    names = [i for i in zf.infolist()
             if not i.is_dir() and _ext(i.filename) in IMAGE_EXTENSIONS
             and not i.filename.startswith("__MACOSX") and not os.path.basename(i.filename).startswith(".")]
    return sorted(names, key=lambda i: natural_key(i.filename))


def count_pages(path, pages=None):
    """Number of pages that `iter_pages` will give (for the progress bar and the warnings)."""
    if is_pdf(path):
        pdf = _open_pdf(path)
        try:
            return len(select_pages(pages, len(pdf)))
        finally:
            pdf.close()
    if is_archive(path):
        with zipfile.ZipFile(path) as zf:
            return len(_archive_images(zf))
    if _ext(path) in (".tif", ".tiff"):
        from PIL import Image
        with Image.open(path) as im:
            return getattr(im, "n_frames", 1)
    return 1


def iter_pages(path, pdf_dpi=DEFAULT_PDF_DPI, pages=None, use_text_layer=True):
    """
    Pages of a file, one at a time (lazy, so a long document never sits in memory at once). With `use_text_layer`, a
    PDF page that carries real text brings it as `text_blocks` (exact, no OCR needed).
    """
    name = os.path.basename(path)
    ext = _ext(path)
    if ext in IMAGE_EXTENSIONS:
        yield Page(path, 0, 1, name, load_image(path), None)
    elif ext in FRAME_EXTENSIONS:
        yield from _iter_frames(path, name)
    elif ext in PDF_EXTENSIONS:
        yield from _iter_pdf(path, name, pdf_dpi, pages, use_text_layer)
    elif ext in CBZ_EXTENSIONS:
        yield from _iter_archive(path)
    else:
        raise ValueError(f"Unsupported file type: {name}")


def _iter_frames(path, name):
    from PIL import Image
    with Image.open(path) as im:
        total = 1 if _ext(path) == ".gif" else getattr(im, "n_frames", 1)  # a GIF is read as its first frame
        for index in range(total):
            im.seek(index)
            yield Page(path, index, total, name, np.array(im.convert("RGB")), None)


def _is_wide(char):
    """True for characters that are written without spaces between them (Chinese, Japanese, Korean)."""
    return ord(char) >= 0x2E80


def merge_runs(blocks):
    """
    Joins the runs of a text layer into lines. Many PDFs do not keep a line as one piece: it comes in runs of a few
    characters (split by a change of font, by kerning, by a dash drawn as its own thin box). The runs that sit on the same
    row, close to each other, become one line; a wide gap (a table, two columns) starts a new one.
    `blocks` is [(box, text)], the result the same, ordered from the top of the page down.
    """
    runs = []
    for box, text in blocks:
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        runs.append([min(xs), min(ys), max(xs), max(ys), text])
    if len(runs) < 2:
        return blocks
    heights = [r[3] - r[1] for r in runs]
    tall = [h for h in heights if h >= 0.5 * float(np.percentile(heights, 90))]  # the thin box of a dash is no measure
    ref = max(1.0, float(np.median(tall)))

    rows = []  # [centre, [runs]]
    for run in sorted(runs, key=lambda r: (r[1] + r[3]) / 2):
        centre = (run[1] + run[3]) / 2
        for row in rows:
            if abs(centre - row[0]) <= 0.45 * ref:
                row[1].append(run)
                row[0] = sum((r[1] + r[3]) / 2 for r in row[1]) / len(row[1])
                break
        else:
            rows.append([centre, [run]])

    lines = []
    for _, members in rows:
        members.sort(key=lambda r: r[0])
        current = [members[0]]
        for run in members[1:]:
            gap = run[0] - current[-1][2]
            if gap > 2.5 * ref:
                lines.append(current)
                current = []
            current.append(run)
        lines.append(current)

    merged = []
    for line in lines:
        text = line[0][4]
        for before, after in zip(line, line[1:]):
            gap = after[0] - before[2]
            # Latin words are separated by spaces that the text layer does not always give; CJK text has none
            if gap > 0.2 * ref and before[4][-1:] != " " and not _is_wide(before[4][-1:] or "a") and not _is_wide(after[4][:1] or "a"):
                text += " "
            text += after[4]
        x1, y1 = min(r[0] for r in line), min(r[1] for r in line)
        x2, y2 = max(r[2] for r in line), max(r[3] for r in line)
        merged.append(([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], text.strip()))
    return sorted((m for m in merged if m[1]), key=lambda m: (m[0][0][1], m[0][0][0]))


def text_layer(page, scale):
    """
    The lines of real text of a PDF page as [(box, text)], with the boxes in the pixels of the rendered image, or None
    when the page has (almost) no text: a scan, whose text has to be read with OCR. A rotated page also returns None
    (its text coordinates would need converting): it is read with OCR.
    """
    try:
        if page.get_rotation() != 0:
            return None
        _, height = page.get_size()
        textpage = page.get_textpage()
        try:
            blocks = []
            for i in range(textpage.count_rects()):
                left, bottom, right, top = textpage.get_rect(i)
                text = textpage.get_text_bounded(left, bottom, right, top).replace("\r", " ").replace("\n", " ").strip()
                if not text:
                    continue
                x1, x2 = left * scale, right * scale
                y1, y2 = (height - top) * scale, (height - bottom) * scale  # PDF's origin is the bottom-left corner
                blocks.append(([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], text))
        finally:
            textpage.close()
    except Exception:
        return None
    blocks = merge_runs(blocks)
    return blocks if sum(len(t.replace(" ", "")) for _, t in blocks) >= MIN_TEXT_LAYER_CHARS else None


def _iter_pdf(path, name, dpi, pages, use_text_layer=True):
    pdf = _open_pdf(path)
    try:
        chosen = select_pages(pages, len(pdf))
        for index in chosen:
            page = pdf[index]
            try:
                width, height = page.get_size()
                scale = min(dpi / 72.0, PDF_MAX_SIDE / max(width, height, 1.0))
                image = np.array(page.render(scale=scale).to_pil().convert("RGB"))
                blocks = text_layer(page, scale) if use_text_layer else None
            finally:
                page.close()
            yield Page(path, index, len(chosen), name, image, blocks, (float(width), float(height)))
    finally:
        pdf.close()


def _iter_archive(path):
    with zipfile.ZipFile(path) as zf:
        members = _archive_images(zf)
        for index, info in enumerate(members):
            if info.file_size > MAX_ARCHIVE_IMAGE_BYTES:
                raise ValueError(f"The image {info.filename} inside {os.path.basename(path)} is too large")
            image = _decode(zf.read(info), info.filename)
            yield Page(path, index, len(members), info.filename, image, None)
