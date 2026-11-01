# Compilar no Windows. A referência é um arquivo de dados para preservar seu hash.
from pathlib import Path
import os
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
datas = [(str(root / "reference" / "importador_v1_12.py"), "reference")]
# O gerador já conferiu procedência, licenças, hashes e completude do inventário.
# Dados, não binaries: preservar EXE/DLLs byte a byte e no mesmo diretório.
ocr_stage = Path(os.environ["IMPORTADOR_OCR_STAGE"])
if not (ocr_stage / "OCR_MANIFEST.json").is_file():
    raise RuntimeError("OCR revisado ausente; execute windows/build_windows.py.")
datas += [(str(ocr_stage), "ocr")]
binaries = []
hiddenimports = [
    "tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox",
    "fitz", "pymupdf", "openpyxl", "openpyxl.styles.numbers",
    "pytesseract", "PIL.Image", "PIL.ImageEnhance", "PIL.ImageOps",
    "re", "sys", "os", "unicodedata", "pathlib", "datetime",
    "santander", "asaas", "cora", "mercado_pago", "document_rows",
]
for package in ("pymupdf", "pytesseract"):
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports

a = Analysis(
    [str(root / "windows" / "entrypoint.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="ImportadorDominio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, name="ImportadorDominio",
)
