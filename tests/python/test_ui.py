import json
import time

import httpx
import pytest
from PySide6.QtTest import QTest

from asmp_tool.api import ApiClient
from asmp_tool.config import ConfigStore
from asmp_tool.journal import Journal
from asmp_tool.ui.window import MainWindow


def wait_done(window, qapp, timeout=8):
    deadline = time.monotonic() + timeout
    while window._thread is not None and time.monotonic() < deadline:
        qapp.processEvents()
        QTest.qWait(10)
    assert window._thread is None, "Worker did not shut down"
    qapp.processEvents()


@pytest.fixture
def window(qapp, tmp_path, settings, account):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("getLoginInfo"):
            body = account
        elif request.url.path.endswith("getConfigList"):
            body = [{"configContent": "其他"}, {"configContent": "无图像"}]
        elif request.url.path.endswith("getRmaDetailBySerial"):
            body = {"productModel": "DS-TEST", "repairEndtime": "2028-01-01", "clientName": "产品客户"}
        else:
            body = {"rmaId": "TEST-RMA"}
        return httpx.Response(200, json={"code": "000", "data": body}, request=request)
    factory = lambda token: ApiClient(token, transport=httpx.MockTransport(handler))
    view = MainWindow(ConfigStore(tmp_path), Journal(tmp_path / "db"), settings, "UI-SECRET-TOKEN", client_factory=factory, diagnostics=True)
    view.show()
    qapp.processEvents()
    yield view, calls
    if view._thread is not None:
        view.request_stop()
        wait_done(view, qapp)
    view.close()
    view.deleteLater()
    qapp.processEvents()


def test_auth_worker_updates_ui_and_only_boolean_diagnostics(window, qapp):
    view, calls = window
    view.check_button.click()
    wait_done(view, qapp)
    assert view.auth_status.text() == "登录有效"
    assert view.fault_combo.count() == 2
    assert view.submit_button.isEnabled() and not view.stop_button.isEnabled()
    diag = json.loads((view.config_store.directory / "diagnostics.json").read_text())
    assert diag == {"authenticated": True}
    assert len(calls) == 2


def test_query_and_submit_table_and_history(window, qapp):
    view, calls = window
    view.serial_edit.setPlainText("A\na\nB")
    view.query_button.click()
    wait_done(view, qapp)
    assert view.last_summary.queried == 2 and view.result_table.rowCount() == 2
    assert view.result_table.item(0, 1).text() == "DS-TEST"
    assert not view.journal.records()
    view.submit_button.click()
    wait_done(view, qapp)
    assert view.last_summary.succeeded == 2 and view.history_table.rowCount() == 2
    assert view.result_table.item(0, 6).text() == "TEST-RMA"
    assert sum(path.endswith("setNewRma") for path in calls) == 2
    assert view.submit_button.isEnabled() and not view._busy
    assert "token" not in json.loads(view.config_store.path.read_text(encoding="utf-8"))


def test_validation_failure_restores_no_worker(window):
    view, calls = window
    view.serial_edit.setPlainText("A B")
    view.submit_button.click()
    assert view.last_error and not calls and not view._busy and view.submit_button.isEnabled()


def test_worker_failure_reenables_controls(window, qapp):
    view, _ = window
    def fail(_worker):
        raise RuntimeError("internal error containing UI-SECRET-TOKEN")
    view._start_job(fail, lambda _value: None)
    wait_done(view, qapp)
    assert view.last_error and "UI-SECRET-TOKEN" not in view.last_error
    assert view.submit_button.isEnabled() and view.serial_edit.isEnabled()


def test_stop_and_close_keep_running_thread_alive_until_done(window, qapp):
    view, _ = window
    def wait_for_stop(worker):
        assert worker.stop_event.wait(3)
        return "stopped"
    view._start_job(wait_for_stop, lambda _value: view.status_label.setText("done"))
    qapp.processEvents()
    view.close()
    wait_done(view, qapp)
    assert view.isVisible()  # close was refused while a request was active
    assert view.status_label.text() == "done" and not view._busy


def test_log_redacts_all_seen_tokens(window):
    view, _ = window
    view.log("debug UI-SECRET-TOKEN")
    assert "UI-SECRET-TOKEN" not in view.log_edit.toPlainText()
    assert "UI-SECRET-TOKEN" not in view.log_path.read_text(encoding="utf-8")
