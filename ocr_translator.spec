# PyInstaller spec for the portable build (folder with OCR Translator.exe).
# Build with build_exe.bat; the PyTorch installed in the build environment decides CPU or GPU.
import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.dirname(os.path.abspath(SPEC))

datas, binaries, hiddenimports = [], [], []

# Packages that load data files or modules by name at run time
for package in ("easyocr", "manga_ocr", "jamdict", "jamdict_data", "fugashi", "unidic_lite", "keyring"):
    try:
        d, b, h = collect_all(package)
    except Exception as error:  # optional ones (dictionary) may be missing: the app works without them
        print(f"[spec] {package} not collected: {error}")
        continue
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += ["keyring.backends.Windows", "win32ctypes.core"]
datas += [(os.path.join(ROOT, "glossary.example.json"), "."), (os.path.join(ROOT, ".env.example"), ".")]

a = Analysis(
    [os.path.join(ROOT, "app", "main.py")],
    pathex=[os.path.join(ROOT, "app")],  # `core` and `ui` are packages inside app/
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "IPython", "pytest", "matplotlib", "notebook"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OCR Translator",
    console=False,  # no black window
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="OCR Translator",
    upx=False,
)
