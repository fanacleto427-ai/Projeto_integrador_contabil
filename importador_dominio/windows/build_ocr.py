"""Compilar OCR mínimo dos fontes revisados; executar nativamente no Windows x64."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import urllib.request

from ocr_bundle import validate_bundle


# Arquivos obtidos das releases upstream e revisados antes de fixar os hashes.
# Mudança de versão exige nova revisão de licenças, avisos e dependências.
SOURCES = {
    "zlib": {
        "version": "1.3.1", "repository": "madler/zlib", "tag": "v1.3.1",
        "sha256": "17e88863f3600672ab49182f217281b6fc4d3c762bde361935e436a95214d05c",
        "license": "Zlib", "legal": ["LICENSE"],
    },
    "libpng": {
        "version": "1.6.44", "repository": "pnggroup/libpng", "tag": "v1.6.44",
        "sha256": "0ef5b633d0c65f780c4fced27ff832998e71478c13b45dfb6e94f23a82f64f7c",
        "license": "libpng-2.0", "legal": ["LICENSE", "AUTHORS"],
    },
    "leptonica": {
        "version": "1.85.0", "repository": "DanBloomberg/leptonica", "tag": "1.85.0",
        "sha256": "c01376bce0379d4ea4bc2ec5d5cbddaa49e2f06f88242619ab8c059e21adf233",
        "license": "BSD-2-Clause", "legal": ["leptonica-license.txt"],
    },
    "tesseract": {
        "version": "5.5.0", "repository": "tesseract-ocr/tesseract", "tag": "5.5.0",
        "sha256": "f2fb34ca035b6d087a42875a35a7a5c4155fa9979c6132365b1e5a28ebc3fc11",
        "license": "Apache-2.0", "legal": ["LICENSE", "AUTHORS"],
    },
}
MODEL_ROOT = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/"
MODEL_FILES = {
    "por.traineddata": "c4932b937207a9514b7514d518b931a99938c02a28a5a5a553f8599ed58b7deb",
    "LICENSE": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
}
SYSTEM_DLLS = {
    "kernel32.dll", "user32.dll", "gdi32.dll", "advapi32.dll", "shell32.dll",
    "ole32.dll", "oleaut32.dll", "ws2_32.dll", "bcrypt.dll", "ntdll.dll",
}


def source_url(component):
    return (f"https://codeload.github.com/{component['repository']}/tar.gz/refs/tags/"
            f"{component['tag']}")


def download_checked(url, path, expected):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        temporary = path.with_suffix(path.suffix + ".part")
        try:
            with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as out:
                shutil.copyfileobj(response, out)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise RuntimeError(f"OCR: SHA-256 divergente em {path.name}; geração bloqueada.")
    return path


def unpack_source(archive, destination):
    """Não aceitar caminhos de escape, links ou dispositivos, mesmo com hash fixo."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive, "r:gz") as tar:
        for item in tar.getmembers():
            parts = Path(item.name).parts
            if (Path(item.name).is_absolute() or ".." in parts or "\\" in item.name
                    or ":" in item.name or not (item.isfile() or item.isdir())):
                raise RuntimeError("OCR: arquivo de fontes contém entrada insegura.")
        tar.extractall(destination, filter="data")
    roots = list(destination.iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        raise RuntimeError("OCR: estrutura inesperada do arquivo de fontes.")
    return roots[0]


def check_system_dependencies(text):
    dependencies = re.findall(r"^\s+([\w.-]+\.dll)\s*$", text, flags=re.I | re.M)
    if not dependencies:
        raise RuntimeError("OCR: não foi possível verificar as dependências PE.")
    unexpected = set(name.lower() for name in dependencies) - SYSTEM_DLLS
    if unexpected:
        raise RuntimeError(f"OCR não estático ou dependência não revisada: {sorted(unexpected)}")
    return sorted(set(dependencies))


def make_manifest(runtime, sources, dependencies):
    """Incluir textos integrais e atribuições de tudo que foi ligado no EXE."""
    runtime = Path(runtime)
    components = []
    for name, component in SOURCES.items():
        legal = []
        for filename in component["legal"]:
            relative = f"licenses/{name}/{filename}"
            target = runtime / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(sources[name] / filename, target)
            legal.append(relative)
        # Os arquivos-fonte fixados não contêm NOTICE na raiz.
        if (sources[name] / "NOTICE").exists():
            raise RuntimeError("OCR: NOTICE inesperado; revisar obrigações antes de distribuir.")
        components.append({
            "name": name, "version": component["version"], "source": source_url(component),
            "source_sha256": component["sha256"], "license": component["license"],
            "files": ["tesseract.exe"], "license_files": legal, "notice_files": ["NOTICE.txt"],
        })
    components.append({
        "name": "tessdata_fast/por", "version": "4.1.0", "source": MODEL_ROOT + "por.traineddata",
        "source_sha256": MODEL_FILES["por.traineddata"], "license": "Apache-2.0",
        "files": ["tessdata/por.traineddata"],
        "license_files": ["licenses/tessdata_fast/LICENSE"], "notice_files": ["NOTICE.txt"],
    })
    (runtime / "NOTICE.txt").write_text(
        "OCR do Importador Domínio: Tesseract + Leptonica + libpng + zlib.\n"
        "Modelo português: tesseract-ocr/tessdata_fast 4.1.0.\n"
        "Os projetos upstream e seus autores são os titulares dos componentes.\n"
        "Textos integrais das licenças e atribuições em licenses/.\n"
        "Fontes sem alterações; compilação estática MSVC Release x64, CRT estático.\n"
        "Recursos opcionais desativados: SW, OpenMP, curl, libarchive, TIFF,\n"
        "JPEG, GIF, WebP, OpenJPEG, ferramentas de treino e de imagem.\n"
        "O aplicativo fornece imagens PNG renderizadas; nenhum leitor foi reescrito.\n"
        "Dependências de sistema verificadas: " + ", ".join(dependencies) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema": 1, "redistribution_reviewed": True,
        "review_notes": (
            "Revisão dos arquivos e receitas fixados em build_ocr.py: Apache-2.0 exige "
            "licença/atribuições e NOTICE aplicável; BSD-2-Clause exige reproduzir aviso "
            "e disclaimer; libpng/Zlib exigem preservar origem e avisos. Textos integrais "
            "incluídos, fontes não modificados. Contrib, testes e ferramentas não ligados. "
            "Não usa DLLs de instaladores terceiros; somente quatro bibliotecas revisadas "
            "e modelo oficial, mais bibliotecas de sistema Windows."
        ),
        "files": {
            path.relative_to(runtime).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(runtime.rglob("*")) if path.is_file()
            and path.name != "OCR_MANIFEST.json"
        },
        "components": components,
    }
    (runtime / "OCR_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    validate_bundle(runtime)


def build(work):
    work = Path(work).resolve()
    # Somente diretório novo: não remover trabalho ou runtime já existente.
    work.mkdir(parents=True, exist_ok=False)
    prefix = work / "prefix"
    sources = {}
    for name, component in SOURCES.items():
        archive = download_checked(source_url(component), work / f"{name}.tar.gz",
                                   component["sha256"])
        sources[name] = unpack_source(archive, work / f"src-{name}")
    flags = [
        "-G", "Visual Studio 17 2022", "-A", "x64",
        "-DCMAKE_POLICY_DEFAULT_CMP0091=NEW", "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
        "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded", "-DBUILD_SHARED_LIBS=OFF",
        f"-DCMAKE_INSTALL_PREFIX={prefix}", f"-DCMAKE_PREFIX_PATH={prefix}",
        "-DCMAKE_DISABLE_FIND_PACKAGE_PkgConfig=TRUE",
    ]
    zlib = prefix / "lib/zlibstatic.lib"
    png = prefix / "lib/libpng16_static.lib"
    options = {
        "zlib": ["-DZLIB_BUILD_EXAMPLES=OFF"],
        "libpng": ["-DPNG_SHARED=OFF", "-DPNG_STATIC=ON", "-DPNG_TESTS=OFF",
                   "-DPNG_TOOLS=OFF", "-DPNG_EXECUTABLES=OFF"],
        "leptonica": ["-DSW_BUILD=OFF", "-DBUILD_PROG=OFF", "-DSTRICT_CONF=ON",
                      "-DENABLE_GIF=OFF", "-DENABLE_JPEG=OFF", "-DENABLE_TIFF=OFF",
                      "-DENABLE_WEBP=OFF", "-DENABLE_OPENJPEG=OFF",
                      "-DENABLE_PNG=ON", "-DENABLE_ZLIB=ON", f"-DPNG_LIBRARY={png}"],
        "tesseract": ["-DSW_BUILD=OFF", "-DWIN32_MT_BUILD=ON", "-DOPENMP_BUILD=OFF",
                      "-DBUILD_TRAINING_TOOLS=OFF", "-DBUILD_TESTS=OFF",
                      "-DDISABLE_CURL=ON", "-DDISABLE_ARCHIVE=ON", "-DDISABLE_TIFF=ON",
                      "-DGRAPHICS_DISABLED=ON", "-DENABLE_NATIVE=OFF"],
    }
    for name in SOURCES:
        directory = work / f"build-{name}"
        extra = [] if name == "zlib" else [
            f"-DZLIB_LIBRARY={zlib}", f"-DZLIB_INCLUDE_DIR={prefix / 'include'}",
        ]
        subprocess.run(["cmake", "-S", str(sources[name]), "-B", str(directory),
                        *flags, *extra, *options[name]], check=True)
        subprocess.run(["cmake", "--build", str(directory), "--config", "Release",
                        "--parallel", "2"], check=True)
        subprocess.run(["cmake", "--install", str(directory), "--config", "Release"], check=True)
    executable = prefix / "bin/tesseract.exe"
    if not executable.is_file():
        raise RuntimeError("Compilação não entregou tesseract.exe.")
    vswhere = (Path(os.environ["ProgramFiles(x86)"]) /
               "Microsoft Visual Studio/Installer/vswhere.exe")
    installation = subprocess.check_output([
        str(vswhere), "-latest", "-products", "*",
        "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
        "-property", "installationPath",
    ], text=True).strip()
    dumpbins = sorted(Path(installation).glob("VC/Tools/MSVC/*/bin/Hostx64/x64/dumpbin.exe"))
    if not dumpbins:
        raise RuntimeError("dumpbin MSVC ausente; dependências OCR não verificadas.")
    dependency_text = subprocess.check_output(
        [str(dumpbins[-1]), "/DEPENDENTS", str(executable)], text=True, errors="replace",
    )
    dependencies = check_system_dependencies(dependency_text)
    runtime = work / "runtime"
    (runtime / "tessdata").mkdir(parents=True)
    shutil.copyfile(executable, runtime / "tesseract.exe")
    download_checked(MODEL_ROOT + "por.traineddata", runtime / "tessdata/por.traineddata",
                     MODEL_FILES["por.traineddata"])
    download_checked(MODEL_ROOT + "LICENSE", runtime / "licenses/tessdata_fast/LICENSE",
                     MODEL_FILES["LICENSE"])
    make_manifest(runtime, sources, dependencies)
    return runtime


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True,
                        help="Diretório novo para fontes, build e runtime")
    args = parser.parse_args(argv)
    if os.name != "nt":
        raise SystemExit("Compilação OCR exige Windows x64 com Visual Studio 2022 C++ e CMake.")
    print(f"Runtime revisado: {build(args.work_dir)}")


if __name__ == "__main__":
    main()
