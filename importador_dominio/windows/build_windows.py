"""Gerar distribuição nativa no Windows; não compila um EXE no Linux."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys
import tempfile
import zipfile

# Também permitir importação isolada do gerador pelos testes.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ocr_bundle import stage_bundle, validate_bundle

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_SHA = "7b7556c4a257ef6a6b5ee7e151916a1bee7cdb5e4eb5ab984a97794c76f8a98b"


def validate_reference(root):
    path = Path(root) / "reference" / "importador_v1_12.py"
    if hashlib.sha256(path.read_bytes()).hexdigest() != REFERENCE_SHA:
        raise RuntimeError("v1.12 alterada. Geração interrompida; nenhum leitor será substituído.")


def make_distribution_zip(folder, archive):
    folder, archive = Path(folder), Path(archive)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as result:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and not path.is_symlink():
                result.write(path, Path(folder.name) / path.relative_to(folder))
    with zipfile.ZipFile(archive) as result:
        if result.testzip() is not None:
            raise RuntimeError("Falha de integridade no ZIP da distribuição.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-install", action="store_true",
                        help="Usar dependências já instaladas, sem executar pip")
    parser.add_argument("--ocr-bundle", type=Path, default=ROOT / "windows" / "ocr-runtime",
                        help="Runtime Windows com OCR_MANIFEST.json e licenças revisados")
    args = parser.parse_args(argv)
    # Este teste deve acontecer antes de instalar dependências ou criar saídas.
    if os.name != "nt":
        raise SystemExit("Geração nativa exige Windows. Nenhum executável foi criado.")
    if sys.version_info < (3, 11) or struct.calcsize("P") != 8:
        raise SystemExit("Use Python 3.11+ de 64 bits; recomendado Python 3.13.")
    validate_reference(ROOT)
    # Não instalar/redistribuir nada antes de verificar a documentação do OCR.
    validate_bundle(args.ocr_bundle)
    try:
        import tkinter
    except ImportError:
        raise SystemExit("Reinstale/modifique o Python com a opção Tcl/Tk habilitada.")
    if not args.skip_install:
        subprocess.run([
            sys.executable, "-m", "pip", "install", "-r",
            str(ROOT / "windows" / "requirements-build.txt"),
        ], cwd=ROOT, check=True)
    output = ROOT / "generated-artifacts" / "windows"
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "ImportadorDominio_Windows.zip"
    archive.unlink(missing_ok=True)
    archive.with_suffix(".zip.sha256").unlink(missing_ok=True)
    staged = stage_bundle(args.ocr_bundle, output / "ocr-stage")
    build_env = dict(os.environ, IMPORTADOR_OCR_STAGE=str(staged.resolve()))
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(output / "dist"),
        "--workpath", str(output / "build"),
        str(ROOT / "windows" / "ImportadorDominio.spec"),
    ], cwd=ROOT, check=True, env=build_env)
    folder = output / "dist" / "ImportadorDominio"
    executable = folder / "ImportadorDominio.exe"
    if not executable.is_file():
        raise RuntimeError("PyInstaller não entregou o executável esperado.")
    # Conferir o arquivo realmente distribuído, não apenas o original no fonte.
    validate_reference(folder / "_internal")
    validate_bundle(folder / "_internal" / "ocr")
    report = output / "verificacao_empacotamento.json"
    report.unlink(missing_ok=True)  # não aceitar resultado de uma geração anterior.
    subprocess.run([str(executable), "--self-test", str(report)], check=True, timeout=120)
    result = json.loads(report.read_text(encoding="utf-8"))
    if result.get("status") != "ok":
        raise RuntimeError("A verificação do programa empacotado falhou.")
    # Testar cópia extraída, caminho com espaços/acentos, sem OCR do construtor.
    # Não duplicar abertura de PDF/cancelamento da homologação desktop.
    with tempfile.TemporaryDirectory(prefix="OCR português ", dir=output) as temporary:
        temporary = Path(temporary)
        probe_zip = temporary / "transporte.zip"
        make_distribution_zip(folder, probe_zip)
        with zipfile.ZipFile(probe_zip) as zipped:
            zipped.extractall(temporary)
        moved = temporary / folder.name
        clean_env = {
            key: value for key, value in os.environ.items()
            if key.upper() not in {"TESSERACT_CMD", "TESSDATA_PREFIX", "IMPORTADOR_OCR_STAGE"}
        }
        clean_env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
        ocr_report = temporary / "ocr.json"
        command = [
            str(moved / executable.name), "--require-bundled-ocr",
            "--ocr-self-test", str(ocr_report),
        ]
        subprocess.run(command, env=clean_env, cwd=temporary, check=True, timeout=120)
        ocr_result = json.loads(ocr_report.read_text(encoding="utf-8"))
        if ocr_result.get("status") != "ok" or ocr_result.get("ocr", {}).get("origem") != "incluído":
            raise RuntimeError("OCR incluído não comprovado no pacote extraído.")
        (moved / "_internal/ocr/tesseract.exe").unlink()
        ocr_report.unlink()
        missing = subprocess.run(command, env=clean_env, cwd=temporary, timeout=120)
        missing_result = json.loads(ocr_report.read_text(encoding="utf-8"))
        if (missing.returncode == 0 or missing_result.get("status") != "erro"
                or "OCR indisponível" not in missing_result.get("erro", "")):
            raise RuntimeError("Ausência de OCR não foi reportada claramente.")
        ocr_result["ausencia_ocr_reportada"] = True
        ocr_result["windows"] = platform.platform()
        # O caminho temporário não permanece válido na distribuição.
        ocr_result["ocr"]["comando"] = "_internal/ocr/tesseract.exe"
        (folder / "VERIFICACAO_OCR.json").write_text(
            json.dumps(ocr_result, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    validate_reference(ROOT)
    (folder / "LEIA-ME.txt").write_text(
        "Importador Domínio — CANDIDATA NÃO HOMOLOGADA\n\n"
        "Execute ImportadorDominio.exe. Mantenha toda a pasta _internal junto dele.\n"
        "Python não é necessário para usar esta distribuição.\n"
        "Tesseract OCR e Português (por) estão em _internal/ocr; não exigem instalação.\n"
        "Licenças, avisos e procedência: _internal/ocr/OCR_MANIFEST.json.\n"
        "TESSERACT_CMD e TESSDATA_PREFIX explícitos são preservados, mesmo inválidos.\n"
        "OCR português sintético: VERIFICACAO_OCR.json. Não homologa extratos.\n"
        "A v1.12 permanece intacta em _internal/reference/.\n"
        "A validação de empacotamento não certifica precisão dos extratos.\n"
        "Ainda existem pendências documentais e de segurança no salvamento.\n"
        "A distribuição não possui assinatura digital. Não desative o antivírus.\n",
        encoding="utf-8",
    )
    (folder / "VERIFICACAO_EMPACOTAMENTO.json").write_bytes(report.read_bytes())
    make_distribution_zip(folder, archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(
        digest + "  " + archive.name + "\n", encoding="utf-8",
    )
    print(f"\nExecutável: {executable}\nPacote completo: {archive}\nSHA-256: {digest}")
    print("Conserve o EXE e a pasta _internal juntos. Não é versão homologada.")


if __name__ == "__main__":
    main()
