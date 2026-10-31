from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QLockFile, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__
from .config import ConfigStore, application_directory, atomic_json, default_data_directory
from .journal import Journal
from .models import UserError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="海康 ASMP 跨平台批量登记工具")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--data-dir", type=Path, help="指定数据目录，默认使用系统用户数据目录")
    parser.add_argument("--legacy-dir", type=Path, help="旧版配置与 CSV 所在目录")
    parser.add_argument("--login", action="store_true", help="启动后打开官方登录窗口")
    parser.add_argument("--diagnostics", action="store_true", help="仅将认证成功状态写入 diagnostics.json，不写入令牌")
    parser.add_argument("--smoke-test", action="store_true", help="在独立临时目录检查界面启动，不发送业务请求")
    parser.add_argument("--browser-smoke", action="store_true", help="检查官网能否在 QtWebEngine 载入，不登录、不提交")
    parser.add_argument("--screenshot", type=Path, help="配合 --smoke-test 保存应用界面截图")
    args = parser.parse_args(argv)
    smoke = args.smoke_test or args.browser_smoke
    if args.screenshot and not args.smoke_test:
        parser.error("--screenshot 仅用于 --smoke-test")
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    QCoreApplication.setOrganizationName("HikvisionASMP")
    QCoreApplication.setApplicationName("HikvisionASMP")
    QCoreApplication.setApplicationVersion(__version__)
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setStyle("Fusion")
    # Import WebEngine before constructing any view, on the GUI's main thread.
    from .ui.window import MainWindow
    data_dir = args.data_dir or (Path(tempfile.mkdtemp(prefix="asmp-smoke-")) if smoke else default_data_directory())
    legacy_dir = args.legacy_dir or (None if smoke else application_directory())
    lock = None
    try:
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = QLockFile(str(data_dir / "app.lock"))
        if not lock.tryLock(0):
            raise UserError("此数据目录的程序已在运行，请使用已打开的窗口")
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
        if smoke:
            print(message, file=sys.stderr)
        else:
            QMessageBox.critical(None, "ASMP 启动失败", message + "\n数据目录：" + str(data_dir))
        if lock:
            lock.unlock()
        return 1
    window.show()
    result = {"exit": 0}
    if args.smoke_test:
        smoke_objects = []
        def check_window():
            try:
                config.save(window.settings())
                if "token" in json.loads(config.path.read_text(encoding="utf-8")):
                    raise RuntimeError("令牌意外写入配置")
                if args.screenshot:
                    args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                    if not window.grab().save(str(args.screenshot)):
                        raise RuntimeError("截图保存失败")
                from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
                from PySide6.QtWebEngineWidgets import QWebEngineView
                profile = QWebEngineProfile(app)
                view = QWebEngineView()
                page = QWebEnginePage(profile, view)
                view.setPage(page)
                smoke_objects.extend([profile, view, page])
                def loaded(ok):
                    if not ok:
                        result["exit"] = 1
                    else:
                        atomic_json(data_dir / "smoke-result.json", {"ui": True, "webengine": True, "version": __version__})
                        print("UI_AND_WEBENGINE_SMOKE_OK", flush=True)
                    page.deleteLater()
                    view.deleteLater()
                    profile.deleteLater()
                    window.close()
                view.loadFinished.connect(loaded)
                view.setHtml("<!doctype html><title>ASMP offline smoke</title><p>Offline renderer check</p>")
                return
            except Exception as error:
                result["exit"] = 1
                print(str(error), file=sys.stderr, flush=True)
            window.close()
        QTimer.singleShot(300, check_window)
        def timed_out():
            result["exit"] = 1
            print("SMOKE_FAILED: renderer timeout", file=sys.stderr, flush=True)
            window.close()
        QTimer.singleShot(45000, timed_out)
    elif args.browser_smoke:
        timer = QTimer(app)
        clock = QElapsedTimer()
        clock.start()
        window.show_login()
        dialog = window._login_dialog
        def check_browser():
            if not dialog._disposed and dialog.page.title() and dialog.view.url().toString().startswith("https://asmp.hikvision.com/sr/"):
                print("BROWSER_SMOKE_OK: official page loaded in off-the-record QtWebEngine", flush=True)
                atomic_json(data_dir / "smoke-result.json", {"official_page": True, "version": __version__})
            elif clock.elapsed() < 45000:
                return
            else:
                result["exit"] = 1
                print("BROWSER_SMOKE_FAILED: official page did not load within 45 seconds", file=sys.stderr, flush=True)
            timer.stop()
            if not dialog._disposed:
                dialog.reject()
            window.close()
        timer.timeout.connect(check_browser)
        timer.start(500)
    elif args.login:
        QTimer.singleShot(100, window.show_login)
    try:
        code = app.exec()
        return result["exit"] or code
    finally:
        lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
