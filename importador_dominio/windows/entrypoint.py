"""Entrada de empacotamento; não altera leitores nem a referência."""
import argparse
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import traceback


def resource_root():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def configure_ocr(base, root=None, environ=None, require_bundled=False):
    """Aplicar depois de load(): o original pode escolher Program Files ao importar."""
    env = os.environ if environ is None else environ
    bundle = (Path(root) if root is not None else resource_root()) / "ocr"
    explicit_cmd = "TESSERACT_CMD" in env
    explicit_data = "TESSDATA_PREFIX" in env
    if explicit_cmd:
        command = env["TESSERACT_CMD"]
        origin = "TESSERACT_CMD"
        if not command:
            raise RuntimeError("OCR indisponível: TESSERACT_CMD está vazio.")
    elif (bundle / "tesseract.exe").is_file():
        command, origin = str(bundle / "tesseract.exe"), "incluído"
    elif require_bundled:
        raise RuntimeError("OCR indisponível: tesseract.exe incluído está ausente.")
    else:
        command = shutil.which("tesseract", path=env.get("PATH", ""))
        if not command:
            for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
                candidate = Path(env.get(variable, "__ausente__")) / "Tesseract-OCR/tesseract.exe"
                if candidate.is_file():
                    command = str(candidate)
                    break
        origin = "instalação externa"
    if not command or base.pytesseract is None:
        raise RuntimeError(
            "OCR indisponível: Tesseract não localizado. Restaure a pasta _internal/ocr "
            "da distribuição completa. PDFs que exigem OCR não poderão ser lidos."
        )
    base.pytesseract.pytesseract.tesseract_cmd = command
    if explicit_data and not env["TESSDATA_PREFIX"]:
        raise RuntimeError("OCR indisponível: TESSDATA_PREFIX está vazio.")
    if not explicit_data and origin == "incluído":
        if not (bundle / "tessdata/por.traineddata").is_file():
            raise RuntimeError("OCR indisponível: falta o idioma português (por.traineddata).")
        env["TESSDATA_PREFIX"] = str(bundle / "tessdata")
    # Não usar caches do pytesseract para diagnosticar executável/idioma atuais.
    try:
        result = subprocess.run(
            [command, "--list-langs"], env=dict(env), capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=20, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if "por" not in result.stdout.splitlines():
            raise RuntimeError("idioma português (por) não disponível")
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        raise RuntimeError(
            f"OCR indisponível ({origin}): {exc}. "
            "Confira TESSERACT_CMD/TESSDATA_PREFIX se definidos; "
            "configurações explícitas não são substituídas."
        ) from exc
    return {"origem": origin, "comando": command, "idioma": "por"}


def ocr_self_test(base, diagnostic):
    """Somente texto sintético: não abre PDFs nem testa cancelamento."""
    from PIL import Image, ImageDraw, ImageFont
    import unicodedata

    # Fonte do próprio Windows, não redistribuída no ZIP.
    fonts = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    font_path = next((path for path in fonts if path.is_file()), None)
    if font_path is None:
        raise RuntimeError("Teste OCR: fonte para texto português sintético não localizada.")
    expected = "AÇÃO, RECEBIMENTO E PAGAMENTO EM PORTUGUÊS"
    font = ImageFont.truetype(str(font_path), 40)
    image = Image.new("RGB", (1500, 130), "white")
    ImageDraw.Draw(image).text((30, 30), expected, font=font, fill="black")
    text = base.pytesseract.image_to_string(
        image, lang="por", config="--psm 7", timeout=30,
    ).strip()
    if unicodedata.normalize("NFC", text) != unicodedata.normalize("NFC", expected):
        raise RuntimeError(f"Teste OCR português divergente: esperado {expected!r}; obtido {text!r}")
    return {
        "status": "ok", "ocr_testado": True, "ocr": diagnostic,
        "texto_esperado": expected, "texto_reconhecido": text,
        "observacao": "Texto sintético; não homologa precisão bancária.",
    }


def self_test(base):
    """Verifica recursos empacotados. Não certifica OCR ou precisão bancária."""
    if base.tk is None:
        raise RuntimeError("Tkinter não foi incluído no executável.")
    for name in ("santander", "asaas", "cora", "mercado_pago", "document_rows"):
        importlib.import_module(name)
    import fitz
    from openpyxl import Workbook, load_workbook
    import pytesseract
    from PIL import Image, ImageEnhance, ImageOps

    root = base.tk.Tk()
    try:
        root.withdraw()
        root.update_idletasks()
        tk_version = str(root.tk.call("info", "patchlevel"))
    finally:
        root.destroy()
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        pdf_path = folder / "sintetico.pdf"
        with fitz.open() as doc:
            doc.new_page().insert_text((50, 50), "TESTE SINTETICO")
            doc.save(pdf_path)
        with fitz.open(pdf_path) as doc:
            assert "TESTE SINTETICO" in doc[0].get_text()
        book = Workbook()
        book.active.append(["TESTE SINTETICO", -1.23])
        book.save(folder / "sintetico.xlsx")
        book.close()
        check = load_workbook(folder / "sintetico.xlsx")
        try:
            assert check.active["B1"].value == -1.23
        finally:
            check.close()
        image = Image.new("RGB", (20, 20), "white")
        ImageEnhance.Contrast(ImageOps.grayscale(image)).enhance(2)
    return {
        "status": "ok",
        "referencia_v1_12_integra": True,  # load() já validou o SHA-256.
        "tk": tk_version,
        "pdf_e_xlsx_sinteticos": True,
        "leitores_importaveis": ["Santander", "Asaas", "Cora", "Mercado Pago"],
        "ocr_testado": False,
        "observacao": "Recursos do programa; o OCR tem diagnóstico separado. Não homologa os leitores.",
    }


def main(argv=None):
    # Algumas dependências esperam streams, mesmo num executável sem console.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", type=Path, help="Salvar diagnóstico de empacotamento")
    parser.add_argument("--ocr-self-test", type=Path, help="Testar texto português sintético")
    parser.add_argument("--require-bundled-ocr", action="store_true")
    args = parser.parse_args(argv)
    from app import load
    base = load()
    try:
        diagnostic = configure_ocr(base, require_bundled=args.require_bundled_ocr)
        ocr_error = None
    except RuntimeError as exc:
        diagnostic, ocr_error = None, str(exc)
    if args.ocr_self_test:
        try:
            if ocr_error:
                raise RuntimeError(ocr_error)
            result = ocr_self_test(base, diagnostic)
        except Exception as exc:
            result = {"status": "erro", "ocr_testado": False, "erro": str(exc)}
        args.ocr_self_test.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        if result["status"] != "ok":
            raise SystemExit(1)
        return
    if args.self_test:
        result = self_test(base)
        args.self_test.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        if ocr_error:
            base.messagebox.showwarning(
                "OCR indisponível",
                ocr_error + "\nA leitura de texto nativo continua disponível. "
                "Nenhum valor será preenchido por saldo.",
            )
        base.main()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        error_path = Path(tempfile.gettempdir()) / "ImportadorDominio_falha_inicializacao.log"
        error_path.write_text(traceback.format_exc(), encoding="utf-8")
        # Um erro em CI não deve deixar uma caixa de diálogo aguardando clique.
        if "--self-test" not in sys.argv and "--ocr-self-test" not in sys.argv:
            try:
                from tkinter import messagebox
                messagebox.showerror(
                    "Falha na inicialização",
                    f"O programa não iniciou. Diagnóstico em:\n{error_path}",
                )
            except Exception:
                pass
        raise SystemExit(1)
