"""
Check of the packaged program: loads the OCR engines and reads a test image, then writes `selftest.txt` next to the
program. Run it with `"OCR Translator.exe" --selftest` (or `python app/main.py --selftest`); the exit code is 0 when
everything works. It exists because a frozen build can miss a data file or a DLL that only a real read would need.
"""
import traceback

import cv2
import numpy as np

from core.paths import root_path


def _test_image(text):
    canvas = np.full((120, 560, 3), 255, dtype=np.uint8)
    cv2.putText(canvas, text, (15, 82), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 4)
    return canvas


def _imports():
    import PyQt6.QtWidgets  # noqa: F401
    import keyring  # noqa: F401
    import manga_ocr  # noqa: F401
    import fugashi  # noqa: F401
    import jamdict  # noqa: F401
    return "PyQt6, keyring, manga_ocr, fugashi, jamdict"


def _rapidocr(lang):
    from core.ocr import RapidOCREngine
    engine = RapidOCREngine(lang=lang)
    engine.warm_up()
    gray = cv2.cvtColor(_test_image("HELLO 2024"), cv2.COLOR_BGR2GRAY)
    text = " ".join(t for _, t, _ in engine._read_raw(gray))
    assert "2024" in text.replace(" ", ""), f"unexpected reading: {text!r}"
    return f"read {text!r}"


def _easyocr():
    from core.ocr import EasyOCREngine
    engine = EasyOCREngine(lang="en", device="cpu")
    engine.warm_up()
    text = " ".join(t for _, t, _ in engine._read_raw(cv2.cvtColor(_test_image("HELLO 2024"), cv2.COLOR_BGR2GRAY)))
    assert "2024" in text.replace(" ", ""), f"unexpected reading: {text!r}"
    return f"read {text!r}"


def run():
    """Runs every check, writes selftest.txt and returns the exit code."""
    lines, ok = [], True
    checks = (
        ("imports", _imports),
        ("RapidOCR (Chinese, zh-cn and zh-tw)", lambda: _rapidocr("zh-cn")),
        ("RapidOCR (Korean)", lambda: _rapidocr("ko")),
        ("RapidOCR (Latin: en, pt and es)", lambda: _rapidocr("en")),
        ("EasyOCR (detector of the Japanese reader)", _easyocr),
    )
    for name, check in checks:
        try:
            lines.append(f"OK    {name}: {check()}")
        except Exception:
            ok = False
            lines.append(f"FAIL  {name}\n{traceback.format_exc()}")
    lines.append("RESULT: " + ("all checks passed" if ok else "something failed"))
    with open(root_path("selftest.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return 0 if ok else 1
