from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

from .models import Settings, UserError, validate_token


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    source_root = Path(__file__).resolve().parents[2]
    # An installed wheel has no adjacent legacy installation; never scan Python's Lib.
    return source_root if (source_root / "run.py").exists() else Path(sys.argv[0]).resolve().parent


def default_data_directory() -> Path:
    directory = application_directory()
    if getattr(sys, "frozen", False) or (directory / "run.py").is_file():
        location = directory / "data-directory.txt"
        if location.is_file():
            try:
                selected = location.read_text(encoding="utf-8-sig").strip()
                if not selected or "\n" in selected or "\r" in selected:
                    raise ValueError
                return (directory / selected).resolve()
            except (OSError, ValueError) as error:
                raise UserError("无法读取 data-directory.txt，请填写一行有效的数据目录路径") from error
        if (directory / "portable-mode.txt").is_file():
            return directory / "data"
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "HikvisionASMP"


def atomic_json(path: Path, data: dict) -> None:
    name = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".config-", suffix=".tmp", delete=False) as stream:
            name = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    except OSError as error:
        raise UserError("无法保存配置，请检查数据目录的写入权限") from error
    finally:
        if name is not None:
            with suppress(OSError):
                name.unlink(missing_ok=True)


class ConfigStore:
    def __init__(self, data_directory: Path, legacy_directory: Path | None = None):
        self.directory = Path(data_directory)
        self.path = self.directory / "submit_config.json"
        self.legacy_directory = legacy_directory
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def load(self) -> tuple[Settings, str]:
        source = self.path
        if not source.exists() and self.legacy_directory:
            source = self.legacy_directory / "submit_config.json"
        if not source.exists():
            return Settings(), ""
        try:
            raw = json.loads(source.read_text(encoding="utf-8-sig"))
            settings = Settings.from_dict(raw)
        except (OSError, UnicodeError, ValueError) as error:
            raise UserError("配置文件无法读取或 JSON 格式损坏，请先修复配置") from error
        token = ""
        if raw.get("token"):
            try:
                token = validate_token(str(raw["token"]))
            except UserError:
                pass
        if source != self.path or "token" in raw:
            self.save(settings)
            # Preserve the old business fields but remove the retired plaintext credential.
            if source != self.path and "token" in raw:
                raw.pop("token")
                atomic_json(source, raw)
        return settings, token

    def save(self, settings: Settings) -> None:
        settings.validate(required=False)
        atomic_json(self.path, settings.to_dict())
