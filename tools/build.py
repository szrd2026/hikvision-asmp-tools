"""Build native packages on each target OS, and verify the frozen Qt renderer."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import plistlib
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from asmp_tool import __version__

PUBLIC_DOCUMENTS = [
    "README.md", "README.en.md", "LICENSE", "CHANGELOG.md", "RELEASE_NOTES.md",
    "THIRD_PARTY_NOTICES.md", "CONTRIBUTING.md", "submit_config.example.json",
    "docs/installation.md", "docs/migration.md", "docs/development.md",
    "docs/python-refactor.md", "docs/screenshot-python.png",
]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_archive(dist):
    target = dist / f"Hikvision-ASMP-v{__version__}-source.zip"
    files = ["pyproject.toml", "requirements.txt", "requirements-dev.txt", "run.py", "setup_env.py",
             "Start-Submit.bat", "Start-Submit.sh", "Start-Submit.command"] + PUBLIC_DOCUMENTS
    for directory in ["src/asmp_tool", "tests/python", "tools", "packaging", ".github/workflows"]:
        files.extend(str(path.relative_to(ROOT)) for path in (ROOT / directory).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(files):
            path = ROOT / relative
            entry = zipfile.ZipInfo.from_file(path, "hikvision-asmp-tools/" + Path(relative).as_posix())
            entry.compress_type = zipfile.ZIP_DEFLATED
            if path.suffix in {".sh", ".command"}:
                entry.create_system = 3
                entry.external_attr = (stat.S_IFREG | 0o755) << 16
            archive.writestr(entry, path.read_bytes())
    return target


def collect_licenses(target):
    target.mkdir(parents=True, exist_ok=True)
    names = ["PySide6", "PySide6_Essentials", "PySide6_Addons", "PySide6_WebEngine", "PySide6_Pdf",
             "shiboken6", "httpx", "httpcore", "anyio", "certifi", "idna", "h11", "typing_extensions", "pyinstaller"]
    versions = {}
    for name in names:
        distribution = importlib.metadata.distribution(name)
        versions[name] = distribution.version
        for entry in distribution.files or []:
            relative = str(entry).replace("\\", "/")
            if ".dist-info/licenses/" in relative or ".dist-info/" in relative and Path(relative).name.lower().startswith(("license", "copying")):
                source = Path(distribution.locate_file(entry))
                if source.is_file():
                    destination = target / name / source.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
    for source in (ROOT / "packaging/licenses").glob("*"):
        shutil.copy2(source, target / source.name)
    (target / "versions.json").write_text(json.dumps(versions, indent=2) + "\n", encoding="utf-8")


def mac_entitlements(build):
    import PySide6
    entitlements = {"com.apple.security.cs.allow-jit": True}
    # Qt specifies that its helper's required entitlements must be retained.
    for path in Path(PySide6.__file__).parent.rglob("QtWebEngineProcess.entitlements"):
        with path.open("rb") as stream:
            entitlements.update(plistlib.load(stream))
    path = build / "macos.entitlements.plist"
    with path.open("wb") as stream:
        plistlib.dump(entitlements, stream)
    return path


def build_environment(build):
    environment = os.environ.copy()
    environment["PYINSTALLER_CONFIG_DIR"] = str(build / "pyinstaller-cache")
    if sys.platform == "win32":
        # A developer's PATH may contain unrelated ICU/Qt DLLs (e.g. Poppler).
        # PyInstaller's resolver must see only the selected Python, Qt and OS runtimes.
        site = Path(importlib.metadata.distribution("PySide6").locate_file("PySide6"))
        windows = Path(environment.get("SystemRoot", r"C:\Windows"))
        paths = [Path(sys.executable).parent, Path(sys.base_prefix), Path(sys.base_prefix) / "DLLs",
                 site, site.parent / "shiboken6", windows / "System32", windows]
        environment["PATH"] = os.pathsep.join(str(path) for path in paths)
        for variable in ("QT_PLUGIN_PATH", "QML_IMPORT_PATH", "QML2_IMPORT_PATH",
                         "QTWEBENGINEPROCESS_PATH", "QTWEBENGINE_RESOURCES_PATH", "QTWEBENGINE_LOCALES_PATH"):
            environment.pop(variable, None)
    return environment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-tests", action="store_true", help="Use only after tests have already passed")
    parser.add_argument("--source-only", action="store_true")
    parser.add_argument("--codesign-identity", help="Optional macOS Developer ID identity already installed on this Mac")
    args = parser.parse_args()
    dist, build = ROOT / "dist", ROOT / "build"
    # All replacement/staging targets are confined to this repository.
    for path in (dist, build, ROOT / ".tmp"):
        if not path.resolve().is_relative_to(ROOT):
            raise RuntimeError("Build paths must stay inside the project")
        path.mkdir(exist_ok=True)
    if not args.skip_tests:
        subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, check=True)
    archives = [source_archive(dist)]
    if not args.source_only:
        licenses = build / "third-party-licenses"
        collect_licenses(licenses)
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
                   "--name", "HikvisionASMP", "--paths", str(ROOT / "src"),
                   "--distpath", str(build / "frozen"), "--workpath", str(build / "pyinstaller"),
                   "--specpath", str(build), "--add-data", f"{licenses}{os.pathsep}third-party-licenses",
                   "--add-data", f"{ROOT / 'THIRD_PARTY_NOTICES.md'}{os.pathsep}.",
                   "--runtime-hook", str(ROOT / "packaging/smoke_runtime.py")]
        if sys.platform == "darwin":
            for relative in PUBLIC_DOCUMENTS:
                destination = str(Path(relative).parent)
                command += ["--add-data", f"{ROOT / relative}{os.pathsep}{destination}"]
        if sys.platform == "darwin":
            command += ["--osx-bundle-identifier", "com.hikvisionasmp.desktop",
                        "--osx-entitlements-file", str(mac_entitlements(build))]
            if args.codesign_identity:
                command += ["--codesign-identity", args.codesign_identity]
        command.append(str(ROOT / "run.py"))
        subprocess.run(command, cwd=ROOT, env=build_environment(build), check=True)
        folder = build / "frozen/HikvisionASMP"
        if sys.platform == "darwin":
            folder = folder.with_suffix(".app")
            executable = folder / "Contents/MacOS/HikvisionASMP"
        else:
            executable = folder / ("HikvisionASMP.exe" if sys.platform == "win32" else "HikvisionASMP")
            for relative in PUBLIC_DOCUMENTS:
                destination = folder / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, destination)
        smoke_dir = ROOT / ".tmp" / ("frozen-smoke-" + uuid4().hex)
        subprocess.run([str(executable), "--smoke-test", "--data-dir", str(smoke_dir)], check=True, timeout=100, cwd=ROOT)
        marker = json.loads((smoke_dir / "smoke-result.json").read_text(encoding="utf-8"))
        if not marker.get("ui") or not marker.get("webengine"):
            raise RuntimeError("Frozen browser renderer did not pass the smoke test")
        system = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
        arch = {"AMD64": "x86_64", "aarch64": "arm64"}.get(platform.machine(), platform.machine())
        base = dist / f"Hikvision-ASMP-v{__version__}-{system}-{arch}"
        if sys.platform == "darwin":
            archive = Path(str(base) + ".zip")
            # ditto preserves framework symlinks and macOS bundle metadata.
            subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(folder), str(archive)], check=True)
        elif sys.platform == "win32":
            archive = Path(shutil.make_archive(str(base), "zip", root_dir=folder.parent, base_dir=folder.name))
        else:
            archive = Path(str(base) + ".tar.gz")
            with tarfile.open(archive, "w:gz") as stream:
                stream.add(folder, arcname=folder.name)
        archives.append(archive)
    checksum_lines = []
    for archive in archives:
        checksum = digest(archive)
        line = f"{checksum}  {archive.name}"
        checksum_lines.append(line)
        archive.with_name(archive.name + ".sha256").write_text(line + "\n", encoding="utf-8")
        print(f"{archive.name}: {archive.stat().st_size / 1024 / 1024:.1f} MiB\nSHA256 {checksum}", flush=True)
    (dist / f"checksums-v{__version__}.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
