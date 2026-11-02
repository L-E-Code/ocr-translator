"""
Output files of a batch translation. `writer_for` returns an object with `add(page, image_rgb)` and `close(complete)`,
so a failure or a cancel in the middle of a long file still leaves a valid result with the pages done so far, named
'….partial.pdf' / '….partial.cbz'. No Qt in here: the rendered page arrives as an RGB array.

  image, TIFF, GIF -> one PNG per page      PDF -> a PDF (JPEG pages)      CBZ -> a CBZ (PNG pages)
"""
import io
import os
import zipfile

import cv2

from core import inputs

PDF_JPEG_QUALITY = 90


def unique_path(path):
    """`path` itself, or 'name (2).ext', 'name (3).ext'... so a previous result is never overwritten."""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{stem} ({n}){ext}"):
        n += 1
    return f"{stem} ({n}){ext}"


def _png_bytes(image_rgb):
    ok, data = cv2.imencode(".png", cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR))
    if not ok:
        raise ValueError("Could not encode the page as PNG")
    return data


class _Writer:
    def __init__(self, source, out_dir, target_lang):
        self.stem = os.path.splitext(os.path.basename(source))[0]
        self.out_dir = out_dir
        self.target_lang = target_lang or "translated"
        self.written = []
        os.makedirs(out_dir, exist_ok=True)

    def _path(self, ext, partial=False):
        suffix = ".partial" if partial else ""
        return unique_path(os.path.join(self.out_dir, f"{self.stem}.{self.target_lang}{suffix}.{ext}"))


class PngWriter(_Writer):
    """One PNG per page: '<stem>.<target>.png', or '<stem>.p03.<target>.png' when the input has several pages."""
    def add(self, page, image_rgb):
        part = f".p{page.index + 1:02d}" if page.count > 1 else ""
        path = unique_path(os.path.join(self.out_dir, f"{self.stem}{part}.{self.target_lang}.png"))
        _png_bytes(image_rgb).tofile(path)  # unicode-safe, unlike cv2.imwrite on Windows
        self.written.append(path)
        return path

    def close(self, complete=True):
        pass


class PdfWriter(_Writer):
    """
    A PDF made of the translated pages as JPEG images, at the size of the original pages. The text of the result is
    not selectable. Pages are added one at a time; the document is saved when it closes.
    """
    def __init__(self, source, out_dir, target_lang):
        super().__init__(source, out_dir, target_lang)
        self.pdf = None

    def add(self, page, image_rgb):
        import pypdfium2 as pdfium
        h, w = image_rgb.shape[:2]
        ok, jpeg = cv2.imencode(".jpg", cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, PDF_JPEG_QUALITY])
        if not ok:
            raise ValueError("Could not encode the page as JPEG")
        width_pt = page.size[0] if page.size else w * 72.0 / inputs.DEFAULT_PDF_DPI
        height_pt = width_pt * h / w  # follows the picture: the text strip style makes it taller than the page
        if self.pdf is None:
            self.pdf = pdfium.PdfDocument.new()
        pdf_page = self.pdf.new_page(width_pt, height_pt)
        image = pdfium.PdfImage.new(self.pdf)
        image.load_jpeg(io.BytesIO(jpeg.tobytes()), inline=False)
        image.set_matrix(pdfium.PdfMatrix().scale(width_pt, height_pt))
        pdf_page.insert_obj(image)
        pdf_page.gen_content()
        pdf_page.close()

    def close(self, complete=True):
        if self.pdf is None:
            return
        path = self._path("pdf", partial=not complete)
        try:
            self.pdf.save(path)
            self.written.append(path)
        finally:
            self.pdf.close()
            self.pdf = None


class CbzWriter(_Writer):
    """A comic archive with one PNG per page, named by page number so every reader keeps the order."""
    def __init__(self, source, out_dir, target_lang):
        super().__init__(source, out_dir, target_lang)
        self.path = self._path("cbz")
        self.zip = None

    def add(self, page, image_rgb):
        if self.zip is None:
            self.zip = zipfile.ZipFile(self.path, "w", zipfile.ZIP_STORED)  # PNG is already compressed
        self.zip.writestr(f"{page.index + 1:04d}.png", _png_bytes(image_rgb).tobytes())

    def close(self, complete=True):
        if self.zip is None:
            return
        self.zip.close()
        self.zip = None
        if not complete:
            partial = self._path("cbz", partial=True)
            os.replace(self.path, partial)
            self.path = partial
        self.written.append(self.path)


class CompositeWriter:
    """Several writers fed with the same pages (the PDF or CBZ plus a PNG of each page)."""
    def __init__(self, writers):
        self.writers = writers

    def add(self, page, image_rgb):
        for writer in self.writers:
            writer.add(page, image_rgb)

    def close(self, complete=True):
        for writer in self.writers:
            writer.close(complete)

    @property
    def written(self):
        return [path for writer in self.writers for path in writer.written]


def writer_for(source, out_dir, target_lang, also_png=False):
    """The writer for the format of `source`; `also_png` adds a PNG per page to a PDF or CBZ result."""
    if inputs.is_pdf(source):
        main = PdfWriter(source, out_dir, target_lang)
    elif inputs.is_archive(source):
        main = CbzWriter(source, out_dir, target_lang)
    else:
        return PngWriter(source, out_dir, target_lang)
    return CompositeWriter([main, PngWriter(source, out_dir, target_lang)]) if also_png else main
