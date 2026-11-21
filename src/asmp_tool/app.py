from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox

from . import __version__
from .config import ConfigStore, application_directory, atomic_json, default_data_directory
from .journal import Journal
from .models import UserError

def acquire_instance_lock(data_dir: Path) -> QLockFile:
    lock = QLockFile(str(data_dir / "app.lock"))
    if lock.tryLock(0):
        return lock
    if lock.error() == QLockFile.LockError.LockFailedError:
        raise UserError("此数据目录的程序已在运行，请使用已打开的窗口")
    if lock.error() == QLockFile.LockError.PermissionError:
        raise UserError("无法在数据目录创建锁文件，请检查写入权限，或使用 --data-dir 指定可写的数据目录")
    raise UserError("无法创建数据目录的锁文件，请检查磁盘空间和文件系统状态")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="海康 ASMP 跨平台批量登记工具")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--data-dir", type=Path, help="指定数据目录，默认使用系统用户数据目录")
    parser.add_argument("--legacy-dir", type=Path, help="旧版配置与 CSV 所在目录")
    parser.add_argument("--diagnostics", action="store_true", help="仅将认证成功状态写入 diagnostics.json，不写入令牌")
    parser.add_argument("--smoke-test", action="store_true", help="在独立临时目录检查界面启动，不发送业务请求")
    parser.add_argument("--screenshot", type=Path, help="配合 --smoke-test 保存应用界面截图")
    args = parser.parse_args(argv)
    if args.screenshot and not args.smoke_test:
        parser.error("--screenshot 仅用于 --smoke-test")
    QCoreApplication.setOrganizationName("HikvisionASMP")
    QCoreApplication.setApplicationName("HikvisionASMP")
    QCoreApplication.setApplicationVersion(__version__)
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setStyle("Fusion")
    from .ui.window import MainWindow
    data_dir = args.data_dir
    legacy_dir = args.legacy_dir or (None if args.smoke_test else application_directory())
    lock = None
    try:
        if data_dir is None:
            data_dir = Path(tempfile.mkdtemp(prefix="asmp-smoke-")) if args.smoke_test else default_data_directory()
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = acquire_instance_lock(data_dir)
        config = ConfigStore(data_dir, legacy_dir)
        settings, token = config.load()
        journal = Journal(data_dir / "submit_records.sqlite3")
        imported = journal.import_legacy_csv(legacy_dir / "submit_records.csv") if legacy_dir else 0
        window = MainWindow(config, journal, settings, token, diagnostics=args.diagnostics)
        if args.diagnostics:
            window._write_diagnostics({"authenticated": False, "state": "awaiting_login"})
        if imported:
            window.log(f"已迁移旧 CSV 的 {imported} 行记录，旧文件保持原样。")
    except (UserError, OSError) as error:
        message = str(error) if isinstance(error, UserError) else "无法初始化数据目录，请检查权限或磁盘空间"
        if args.smoke_test:
            print(message, file=sys.stderr)
        else:
            if data_dir is not None:
                message += "\n数据目录：" + str(data_dir)
            QMessageBox.critical(None, "ASMP 启动失败", message)
        if lock:
            lock.unlock()
        return 1
    window.show()
    result = {"exit": 0}
    if args.smoke_test:
        def check_window():
            try:
                if window.token_edit.echoMode() != QLineEdit.EchoMode.Password:
                    raise RuntimeError("令牌输入框未隐藏")
                window.token_edit.setText("OFFLINE-SMOKE-TOKEN")
                config.save(window.settings())
                saved = config.path.read_text(encoding="utf-8")
                if "token" in json.loads(saved) or window.token_edit.text() in saved:
                    raise RuntimeError("令牌意外写入配置")
                window.token_edit.clear()
                if args.screenshot:
                    args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                    if not window.grab().save(str(args.screenshot)):
                        raise RuntimeError("截图保存失败")
                atomic_json(data_dir / "smoke-result.json",
                            {"ui": True, "manual_token": True, "version": __version__})
                print("UI_AND_MANUAL_TOKEN_SMOKE_OK", flush=True)
            except Exception as error:
                result["exit"] = 1
                print(str(error), file=sys.stderr, flush=True)
            finally:
                window.close()
        QTimer.singleShot(300, check_window)
    try:
        code = app.exec()
        return result["exit"] or code
    finally:
        lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
