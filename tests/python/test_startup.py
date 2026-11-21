import pytest
from PySide6.QtCore import QLockFile

from asmp_tool import app, config
from asmp_tool.models import UserError


def test_instance_lock_blocks_second_window_and_releases(tmp_path):
    first = app.acquire_instance_lock(tmp_path)
    try:
        with pytest.raises(UserError, match="已在运行"):
            app.acquire_instance_lock(tmp_path)
    finally:
        first.unlock()
    second = app.acquire_instance_lock(tmp_path)
    second.unlock()
    assert not (tmp_path / "app.lock").exists()


@pytest.mark.parametrize("error, message", [
    (QLockFile.LockError.PermissionError, "写入权限"),
    (QLockFile.LockError.UnknownError, "磁盘空间"),
])
def test_lock_io_errors_do_not_claim_another_instance(tmp_path, monkeypatch, error, message):
    class FailedLock:
        LockError = QLockFile.LockError

        def __init__(self, path):
            pass

        def tryLock(self, timeout):
            return False

        def error(self):
            return error

    monkeypatch.setattr(app, "QLockFile", FailedLock)
    with pytest.raises(UserError, match=message) as caught:
        app.acquire_instance_lock(tmp_path)
    assert "已在运行" not in str(caught.value)


@pytest.mark.parametrize("frozen, marker, portable", [
    (True, True, True),
    (True, False, False),
    (False, True, False),
])
def test_portable_data_is_explicit_and_relative_to_executable(tmp_path, monkeypatch, frozen, marker, portable):
    installation = tmp_path / "installation"
    installation.mkdir()
    unrelated = tmp_path / "working-directory"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    monkeypatch.setattr(config.sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(config.sys, "platform", "win32")
    monkeypatch.setattr(config, "application_directory", lambda: installation)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-data"))
    if marker:
        (installation / "portable-mode.txt").touch()
    expected = installation / "data" if portable else tmp_path / "user-data" / "HikvisionASMP"
    assert config.default_data_directory() == expected
