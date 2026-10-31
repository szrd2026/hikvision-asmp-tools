import importlib.util
import os
import zipfile
from pathlib import Path


def build_module():
    path = Path(__file__).resolve().parents[2] / "tools/build.py"
    spec = importlib.util.spec_from_file_location("asmp_native_build", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_archive_allowlist_and_unix_launch_permissions(tmp_path):
    module = build_module()
    archive = module.source_archive(tmp_path)
    with zipfile.ZipFile(archive) as stream:
        names = stream.namelist()
        assert any(name.endswith("src/asmp_tool/app.py") for name in names)
        for document in module.PUBLIC_DOCUMENTS:
            assert "hikvision-asmp-tools/" + document in names
        assert not any("legacy/" in name or ".venv/" in name or "egg-info" in name or "__pycache__" in name for name in names)
        assert not any(name.endswith("submit_config.json") or ".sqlite3" in name or "/logs/" in name for name in names)
        assert (stream.getinfo("hikvision-asmp-tools/Start-Submit.command").external_attr >> 16) & 0o111


def test_windows_build_isolated_from_host_tool_dll_paths(tmp_path, monkeypatch):
    module = build_module()
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setenv("PATH", "UNRELATED-POPLER-DLLS")
    monkeypatch.setenv("QT_PLUGIN_PATH", "UNRELATED-QT")
    environment = module.build_environment(tmp_path)
    assert "UNRELATED" not in environment["PATH"]
    assert "QT_PLUGIN_PATH" not in environment
    assert environment["PYINSTALLER_CONFIG_DIR"] == str(tmp_path / "pyinstaller-cache")
    assert os.environ["PATH"] == "UNRELATED-POPLER-DLLS"
