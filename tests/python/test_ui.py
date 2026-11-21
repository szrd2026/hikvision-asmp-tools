import json
import time

import httpx
import pytest
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt

from asmp_tool.api import ApiClient, AuthenticationExpired
from asmp_tool.config import ConfigStore
from asmp_tool.journal import Journal
from asmp_tool.models import UserError
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
    payloads = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("getLoginInfo"):
            body = account
        elif request.url.path.endswith("getConfigList"):
            body = [{"configContent": "其他"}, {"configContent": "无图像"}]
        elif request.url.path.endswith("getRmaDetailBySerial"):
            body = {"productModel": "DS-TEST", "repairEndtime": "2028-01-01", "clientName": "产品客户"}
        elif request.url.path.endswith("getProvinceCityArea"):
            body = {
                ("province", ""): [{"locationName": "测试省", "locationCode": "P1"}, {"locationName": "另一省", "locationCode": "P2"}],
                ("city", "P1"): [{"locationName": "测试市", "locationCode": "C1"}],
                ("city", "P2"): [{"locationName": "另一市", "locationCode": "C2"}],
                ("district", "C1"): [{"locationName": "测试区", "locationCode": "D1"}],
                ("district", "C2"): [{"locationName": "另一区", "locationCode": "D2"}],
            }[(request.url.params["locationType"], request.url.params["parentCode"])]
        else:
            payloads.append(json.loads(request.content))
            body = {"rmaId": "TEST-RMA"}
        return httpx.Response(200, json={"code": "000", "data": body}, request=request)
    factory = lambda token: ApiClient(token, transport=httpx.MockTransport(handler))
    view = MainWindow(ConfigStore(tmp_path), Journal(tmp_path / "db"), settings, "UI-SECRET-TOKEN", client_factory=factory, diagnostics=True)
    view.show()
    view.test_payloads = payloads
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
    view.token_edit.clear()
    view.token_edit.setFocus()
    clipboard = qapp.clipboard()
    previous = clipboard.text()
    try:
        clipboard.setText("UI-SECRET-TOKEN")
        view.token_edit.paste()
    finally:
        clipboard.setText(previous)
    assert view.token_edit.text() == "UI-SECRET-TOKEN"
    QTest.keyClick(view.token_edit, Qt.Key.Key_Return)
    wait_done(view, qapp)
    assert view.auth_status.text() == "登录有效"
    assert view.fault_combo.count() == 2
    assert view.submit_button.isEnabled() and not view.stop_button.isEnabled()
    diag = json.loads((view.config_store.directory / "diagnostics.json").read_text())
    assert diag == {"authenticated": True}
    assert len(calls) == 2
    view.serial_edit.setPlainText("TEST001")
    view.query_button.click()
    wait_done(view, qapp)
    assert view.last_summary.queried == 1 and not view.journal.records()
    assert "UI-SECRET-TOKEN" not in view.config_store.path.read_text(encoding="utf-8")
    assert "UI-SECRET-TOKEN" not in view.log_path.read_text(encoding="utf-8")


def test_logout_during_fault_option_load_invalidates_login(window, qapp, monkeypatch):
    view, _ = window

    def expired(_api):
        raise AuthenticationExpired("登录已失效")

    monkeypatch.setattr(ApiClient, "fault_options", expired)
    view.check_button.click()
    wait_done(view, qapp)
    assert view.auth_status.text() == "登录已失效" and not view.token_edit.text()


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


def test_form_autosaves_without_query_or_submit_and_restores(window, qapp):
    view, calls = window
    view.client_edit.setText("新测试客户")
    view.contact_edit.setText("新测试联系人")
    view.phone_edit.setText("010-11111111")
    view.fault_combo.setCurrentText("无图像")
    view.description_combo.setEditText("持续无图像")
    view.deal_combo.setCurrentIndex(view.deal_combo.findData("0"))
    view.repair_combo.setCurrentIndex(view.repair_combo.findData("1"))
    view.return_combo.setCurrentIndex(view.return_combo.findData("0"))
    for combo, name in [(view.province_combo, "测试省"), (view.city_combo, "测试市"), (view.area_combo, "测试区")]:
        combo.addItem(name)
        combo.setCurrentIndex(0)
    view.address_edit.setText("测试街道1号")
    view.delay_spin.setValue(321)
    view.skip_checkbox.setChecked(False)
    QTest.qWait(900)
    loaded, token = view.config_store.load()
    assert loaded == view.settings() and token == "" and not calls
    assert (loaded.province, loaded.city, loaded.area) == ("测试省", "测试市", "测试区")
    assert "已自动保存" in view.settings_status.text()
    reopened = MainWindow(view.config_store, view.journal, loaded, client_factory=view.api_factory)
    try:
        assert reopened.settings() == loaded
        assert reopened.return_combo.currentText() == "寄回客户"
        assert reopened.description_combo.currentText() == "持续无图像"
    finally:
        reopened.close()
        reopened.deleteLater()


def test_close_flushes_pending_autosave_even_with_incomplete_form(window):
    view, calls = window
    view.client_edit.setText("尚未填完")
    view.contact_edit.clear()
    assert view._save_timer.isActive()
    view.close()
    loaded, _ = view.config_store.load()
    assert loaded.repair_client == "尚未填完" and loaded.linkman == "" and not calls
    assert not view._save_timer.isActive()


def test_autosave_failure_is_visible_and_can_retry(window, monkeypatch):
    view, _ = window
    view.save_settings()
    before = view.config_store.path.read_bytes()
    view.client_edit.setText("需要保留的修改")
    def fail(_settings):
        raise UserError("测试：磁盘不可写")
    with monkeypatch.context() as patch:
        patch.setattr(view.config_store, "save", fail)
        view._autosave_settings()
        assert "保存失败" in view.settings_status.text()
        assert view.config_store.path.read_bytes() == before
    view.save_button.click()
    assert view.config_store.load()[0].repair_client == "需要保留的修改"
    assert "已自动保存" in view.settings_status.text()


def test_repair_client_dropdown_remembers_finished_edits_and_deletes_history(window, qapp):
    view, calls = window
    view.client_edit.setFocus()
    view.client_edit.setText("客户")
    QTest.qWait(900)
    assert view.config_store.load()[0].repair_client == "客户"
    assert view.client_combo.count() == 0  # Pausing mid-entry only saves the draft text.
    view.client_edit.setText("客户甲")
    QTest.keyClick(view.client_edit, Qt.Key.Key_Return)
    view.client_edit.setText("客户乙")
    QTest.keyClick(view.client_edit, Qt.Key.Key_Return)
    assert view.config_store.load()[0].repair_client_history == ("客户乙", "客户甲")

    # Select an older value through the actual popup and verify it moves to the top.
    view.client_combo.showPopup()
    qapp.processEvents()
    view.client_combo.view().setCurrentIndex(view.client_combo.model().index(1, 0))
    QTest.keyClick(view.client_combo.view(), Qt.Key.Key_Return)
    assert view.client_edit.text() == "客户甲"
    assert view.config_store.load()[0].repair_client_history == ("客户甲", "客户乙")
    assert view.contact_edit.text() and view.phone_edit.text()

    view.delete_client_button.click()
    assert view.client_edit.text() == "客户甲"
    assert view.client_combo.findText("客户甲") == -1
    view.close()
    restored, token = view.config_store.load()
    assert restored.repair_client == "客户甲"
    assert restored.repair_client_history == ("客户乙",) and token == "" and not calls
    reopened = MainWindow(view.config_store, view.journal, restored)
    try:
        assert reopened.client_combo.itemText(0) == "客户乙"
        assert reopened.client_combo.currentText() == "客户甲"
        assert not reopened.delete_client_button.isEnabled()
    finally:
        reopened.close()
        reopened.deleteLater()


def test_description_dropdown_sort_delete_and_submit_plain_text(window, qapp):
    view, _ = window
    for serial, text in enumerate(["无图像", "无图像", "频繁重启"]):
        attempt = view.journal.reserve(f"H{serial}", "DS", "B", skip_success=True, fault_text=text)
        view.journal.finish(attempt, "succeeded", "ok")
    view.refresh_descriptions()
    assert [view.description_combo.itemText(i) for i in range(view.description_combo.count())] == ["无图像", "频繁重启"]
    view.description_combo.setCurrentIndex(0)
    assert view.delete_description_button.isEnabled()
    view.serial_edit.setPlainText("NEW")
    view.submit_button.click()
    wait_done(view, qapp)
    assert view.test_payloads[0]["rmaDetailList"][0]["rebackFaulttext"] == "无图像"
    assert view.journal.fault_descriptions()[0]["use_count"] == 3
    view.delete_description_button.click()
    assert view.description_combo.findText("无图像") == -1
    assert view.description_combo.currentText() == "无图像"  # deleting history preserves the active form
    assert not view.delete_description_button.isEnabled()
    view.refresh_descriptions()
    assert view.description_combo.findText("无图像") == -1
    assert len(view.journal.records()) == 4
    view.description_combo.setEditText("全新描述")
    QTest.keyClick(view.description_edit, Qt.Key.Key_Return)
    assert view.description_combo.findText("全新描述") == -1


def select_region(combo, index, view, qapp):
    combo.setCurrentIndex(index)
    combo.activated.emit(index)
    wait_done(view, qapp)


def test_customer_return_cascades_address_and_submits_selected_value(window, qapp):
    view, _ = window
    select_region(view.return_combo, view.return_combo.findData("0"), view, qapp)
    assert view.return_address_panel.isVisible()
    assert view.province_combo.count() == 2 and not view.province_combo.currentText()
    select_region(view.province_combo, 0, view, qapp)
    select_region(view.city_combo, 0, view, qapp)
    view.area_combo.setCurrentIndex(0)
    view.address_edit.setText("测试街道1号")
    select_region(view.province_combo, 0, view, qapp)
    select_region(view.city_combo, 0, view, qapp)
    assert view.city_combo.currentText() == "测试市" and view.area_combo.currentText() == "测试区"
    view.serial_edit.setPlainText("CUSTOMER")
    view.submit_button.click()
    wait_done(view, qapp)
    payload = view.test_payloads[-1]
    assert payload["isSend"] == payload["rmaDetailList"][0]["isSend"] == 0
    assert [payload[key] for key in ("province", "city", "area", "address")] == ["测试省", "测试市", "测试区", "测试街道1号"]
    select_region(view.province_combo, 1, view, qapp)
    assert not view.city_combo.currentText() and not view.area_combo.currentText()
    assert view.city_combo.itemText(0) == "另一市" and view.area_combo.count() == 0
    # Going back to the collecting point retains the address locally but does not send it.
    view.return_combo.setCurrentIndex(view.return_combo.findData("1"))
    assert not view.return_address_panel.isVisible()
    view.serial_edit.setPlainText("POINT")
    view.submit_button.click()
    wait_done(view, qapp)
    assert view.test_payloads[-1]["isSend"] == 1 and not view.test_payloads[-1]["address"]


def test_saved_region_names_are_restored_on_reload(window, qapp):
    view, _ = window
    view.return_combo.setCurrentIndex(view.return_combo.findData("0"))
    for combo, name in [(view.province_combo, "测试省"), (view.city_combo, "测试市"), (view.area_combo, "测试区")]:
        combo.addItem(name)
        combo.setCurrentIndex(0)
    view.load_regions()
    wait_done(view, qapp)
    assert [combo.currentText() for combo in (view.province_combo, view.city_combo, view.area_combo)] == ["测试省", "测试市", "测试区"]
    assert [combo.currentData() for combo in (view.province_combo, view.city_combo, view.area_combo)] == ["P1", "C1", "D1"]


def test_customer_return_incomplete_address_never_starts_submission(window):
    view, calls = window
    view.return_combo.setCurrentIndex(view.return_combo.findData("0"))
    view.serial_edit.setPlainText("A")
    view.submit_button.click()
    assert "寄回客户" in view.last_error and not calls and not view._busy


def test_region_failure_cannot_retain_children_of_old_province(window, qapp, monkeypatch):
    view, _ = window
    view.province_combo.addItem("原省", "P1")
    view.province_combo.addItem("另一省", "P2")
    view.province_combo.setCurrentIndex(0)
    view.city_combo.addItem("旧城市", "OLD-C")
    view.city_combo.setCurrentIndex(0)
    view.area_combo.addItem("旧区域", "OLD-D")
    view.area_combo.setCurrentIndex(0)
    def fail(_self, *_args):
        raise UserError("地址加载失败，请重试")
    monkeypatch.setattr(ApiClient, "regions", fail)
    select_region(view.province_combo, 1, view, qapp)
    assert "加载失败" in view.last_error
    assert not view.city_combo.currentText() and not view.area_combo.currentText()


def test_return_address_controls_fit_at_minimum_window_size(window, qapp):
    view, _ = window
    view.resize(1020, 760)
    view.return_combo.setCurrentIndex(view.return_combo.findData("0"))
    qapp.processEvents()
    panel = view.return_address_panel
    for field in (view.province_combo, view.city_combo, view.area_combo, view.address_edit, view.region_button):
        assert panel.rect().contains(field.geometry())
    assert view.province_combo.geometry().bottom() < view.address_edit.geometry().top()
    assert panel.geometry().bottom() < view.delay_spin.geometry().top()
    assert view.settings_group.rect().contains(panel.geometry())
