"""Portão de redistribuição: só copiar um runtime com inventário revisado.

Não transforma metadados em parecer jurídico. Quem prepara o runtime precisa
conferir as licenças de TODOS os componentes, incluindo as DLLs transitivas.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil


def validate_bundle(folder):
    folder = Path(folder)
    manifest_path = folder / "OCR_MANIFEST.json"
    if not manifest_path.is_file():
        raise RuntimeError(
            "OCR ausente ou sem procedência revisada: falta OCR_MANIFEST.json. "
            "Veja windows/OCR_REDISTRIBUICAO.md; nenhum ZIP será aprovado."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or manifest.get("redistribution_reviewed") is not True:
        raise RuntimeError("OCR: revisão de redistribuição não confirmada.")
    if not manifest.get("review_notes", "").strip():
        raise RuntimeError("OCR: registre a revisão das obrigações e avisos.")
    files = manifest.get("files", {})
    if not {"tesseract.exe", "tessdata/por.traineddata"}.issubset(files):
        raise RuntimeError("OCR: faltam Tesseract ou idioma português (por).")
    for name, expected in files.items():
        relative = PurePosixPath(name)
        if (relative.is_absolute() or ".." in relative.parts or "\\" in name
                or ":" in name or str(relative) != name or name == "OCR_MANIFEST.json"):
            raise RuntimeError(f"OCR: caminho inseguro no inventário: {name}")
        path = folder / name
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            raise RuntimeError(f"OCR: link não permitido: {name}")
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"OCR: arquivo ausente ou SHA-256 divergente: {name}")
    covered = set()
    for component in manifest.get("components", []):
        if (not component.get("name") or not component.get("version")
                or not component.get("source", "").startswith("https://")
                or not component.get("license") or not component.get("files")):
            raise RuntimeError("OCR: componente sem versão, origem HTTPS ou licença.")
        licenses = component.get("license_files", [])
        # [] significa que a revisão não encontrou NOTICE aplicável; chave obrigatória.
        if not licenses or "notice_files" not in component:
            raise RuntimeError("OCR: faltam cópias das licenças ou revisão de NOTICE.")
        names = component["files"] + licenses + component["notice_files"]
        if not set(names).issubset(files):
            raise RuntimeError("OCR: componente cita arquivo fora do inventário.")
        covered.update(names)
    if covered != set(files):
        raise RuntimeError("OCR: há arquivos sem origem/licença revisada.")
    if (folder / "tesseract.exe").read_bytes()[:2] != b"MZ":
        raise RuntimeError("OCR: Tesseract não é um executável Windows.")
    return manifest


def stage_bundle(source, target):
    manifest = validate_bundle(source)
    source = Path(source).resolve()
    target = Path(target)
    resolved_target = target.resolve()
    if (source == resolved_target or source in resolved_target.parents
            or resolved_target in source.parents):
        raise RuntimeError("OCR: origem e destino não podem se sobrepor.")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name in [*manifest["files"], "OCR_MANIFEST.json"]:
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(source) / name, destination)
    validate_bundle(target)
    return target
