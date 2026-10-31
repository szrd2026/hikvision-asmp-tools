import csv
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from asmp_tool.config import ConfigStore
from asmp_tool.journal import Journal, JournalError, RecordBlocked
from asmp_tool.models import UserError


def legacy_csv(path, rows, mode="w"):
    with path.open(mode, encoding="utf-8-sig" if mode == "w" else "utf-8", newline="") as stream:
        writer = csv.writer(stream)
        if mode == "w":
            writer.writerow(["时间", "序列号", "型号", "结果"])
        writer.writerows(rows)


def test_config_migrates_without_secret(tmp_path, settings):
    old = tmp_path / "old"
    old.mkdir()
    source = old / "submit_config.json"
    source.write_text(json.dumps(settings.to_dict() | {"token": "LEGACY-SECRET"}), encoding="utf-8-sig")
    store = ConfigStore(tmp_path / "new", old)
    loaded, token = store.load()
    assert loaded == settings and token == "LEGACY-SECRET"
    assert "token" not in json.loads(source.read_text(encoding="utf-8"))
    assert "token" not in json.loads(store.path.read_text(encoding="utf-8"))
    assert store.load() == (settings, "")


def test_config_replaces_existing_file(tmp_path, settings):
    store = ConfigStore(tmp_path)
    store.save(settings)
    store.save(settings)
    assert store.load()[0] == settings
    assert not list(tmp_path.glob(".config-*.tmp"))


def test_corrupt_config_not_overwritten(tmp_path):
    path = tmp_path / "submit_config.json"
    path.write_text("BROKEN", encoding="utf-8")
    with pytest.raises(UserError):
        ConfigStore(tmp_path).load()
    assert path.read_text() == "BROKEN"


def test_intent_survives_reopen_and_always_blocks(tmp_path):
    path = tmp_path / "records.sqlite3"
    journal = Journal(path)
    attempt = journal.reserve("ABC", "DS", "BATCH", skip_success=True)
    other = Journal(path)
    assert other.status("abc") == "pending"
    with pytest.raises(RecordBlocked):
        other.reserve("ABC", "DS", "NEXT", skip_success=False)
    other.finish(attempt, "unknown", "timeout")
    with pytest.raises(RecordBlocked):
        journal.reserve("ABC", "DS", "NEXT", skip_success=False)


def test_history_success_and_new_pending(tmp_path):
    journal = Journal(tmp_path / "db")
    attempt = journal.reserve("A", "DS", "B", skip_success=True)
    journal.finish(attempt, "succeeded", "ok", "RMA1")
    journal.record_failure("A", "DS", "B2", "failed query")
    assert journal.status("a") == "succeeded"
    with pytest.raises(RecordBlocked):
        journal.reserve("A", "DS", "B3", skip_success=True)
    next_attempt = journal.reserve("a", "DS", "B3", skip_success=False)
    assert journal.status("A") == "pending"
    journal.finish(next_attempt, "rejected", "server refused")
    assert journal.status("A") == "succeeded"


def test_reservation_atomic_across_threads(tmp_path):
    journal = Journal(tmp_path / "db")
    def reserve(_index):
        try:
            return journal.reserve("SAME", "DS", "B", skip_success=False)
        except RecordBlocked:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        attempts = list(pool.map(reserve, range(4)))
    assert sum(value is not None for value in attempts) == 1
    assert len(journal.records()) == 1


def test_reconciliation_audited_and_terminal_immutable(tmp_path):
    journal = Journal(tmp_path / "db")
    attempt = journal.reserve("A", "DS", "B", skip_success=True)
    with pytest.raises(UserError):
        journal.reconcile(attempt, registered=False, note="")
    journal.reconcile(attempt, registered=False, note="官网确认未登记")
    assert journal.status("A") is None
    with pytest.raises(JournalError):
        journal.reconcile(attempt, registered=True, note="cannot rewrite terminal result")
    with journal.connection() as db:
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 2


def test_csv_import_pairs_intent_and_result_and_is_incremental(tmp_path):
    path = tmp_path / "old.csv"
    legacy_csv(path, [["t", "A", "DS", "提交中（待核对）"], ["t", "A", "DS", "成功"],
                      ["t", "A", "DS", "失败: 服务端拒绝：后一次失败"], ["t", "B", "DS", "待核对: timeout"]])
    journal = Journal(tmp_path / "db")
    assert journal.import_legacy_csv(path) == 4
    assert journal.status("A") == "succeeded" and journal.status("B") == "pending"
    assert len(journal.records()) == 3
    assert journal.import_legacy_csv(path) == 0
    legacy_csv(path, [["t", "B", "DS", "成功"]], mode="a")
    assert journal.import_legacy_csv(path) == 1
    assert journal.status("B") == "succeeded" and len(journal.records()) == 3


def test_csv_import_transaction_rolls_back_invalid_row(tmp_path):
    path = tmp_path / "old.csv"
    legacy_csv(path, [["t", "A", "DS", "成功"], ["t", "B", "DS", "未知结果"]])
    journal = Journal(tmp_path / "db")
    with pytest.raises(JournalError):
        journal.import_legacy_csv(path)
    assert journal.records() == []


def test_csv_prior_content_cannot_silently_change(tmp_path):
    path = tmp_path / "old.csv"
    legacy_csv(path, [["t", "A", "DS", "成功"]])
    journal = Journal(tmp_path / "db")
    journal.import_legacy_csv(path)
    legacy_csv(path, [["t", "A", "DS", "失败: changed"]])
    with pytest.raises(JournalError):
        journal.import_legacy_csv(path)
    assert journal.status("A") == "succeeded"


@pytest.mark.parametrize("content", ["", "bad,header\n", '时间,序列号,型号,结果\nt,A,DS,"truncated', "时间,序列号,型号,结果\nt,A,DS\n"])
def test_broken_csv_fails_closed(tmp_path, content):
    path = tmp_path / "old.csv"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(JournalError):
        Journal(tmp_path / "db").import_legacy_csv(path)


def test_corrupt_database_is_never_reset(tmp_path):
    path = tmp_path / "db"
    path.write_bytes(b"not a SQLite database")
    with pytest.raises(JournalError):
        Journal(path)
    assert path.read_bytes() == b"not a SQLite database"


def test_unknown_schema_version_rejected(tmp_path):
    path = tmp_path / "db"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(JournalError):
        Journal(path)


def test_export_has_bom_and_excel_formula_protection(tmp_path):
    journal = Journal(tmp_path / "db")
    journal.record_failure("=A1", '+MODEL,"quoted"', "B", "message")
    out = tmp_path / "records.csv"
    assert journal.export_csv(out) == 1
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")
    with out.open(encoding="utf-8-sig", newline="") as stream:
        row = list(csv.DictReader(stream))[0]
    assert row["序列号"] == "'=A1" and row["型号"] == '\'+MODEL,"quoted"'


@pytest.mark.parametrize("model", ["DS", ""])
def test_early_legacy_network_failure_remains_uncertain(tmp_path, model):
    source = tmp_path / "old.csv"
    legacy_csv(source, [["t", "A", model, "失败: 提交网络错误: timeout"]])
    journal = Journal(tmp_path / "db")
    journal.import_legacy_csv(source)
    assert journal.status("A") == "pending"


@pytest.mark.parametrize("message,state", [
    ("失败: 查询明细网络错误: timeout", "failed"),
    ("失败: notLogin：accesstoken 已过期", "auth"),
    ("失败: 已人工核对未登记", "rejected"),
])
def test_provable_legacy_non_submissions_are_terminal(tmp_path, message, state):
    source = tmp_path / "old.csv"
    legacy_csv(source, [["t", "A", "DS", message]])
    journal = Journal(tmp_path / "db")
    journal.import_legacy_csv(source)
    assert journal.records()[0]["state"] == state and journal.status("A") is None


def test_earlier_importer_data_is_repaired_without_source_csv(tmp_path):
    journal = Journal(tmp_path / "db")
    attempt = journal.reserve("A", "DS", "legacy", skip_success=True)
    journal.finish(attempt, "rejected", "失败: 提交网络错误: timeout")
    with journal.connection() as db:
        db.execute("UPDATE attempts SET legacy_source='old.csv' WHERE id=?", (attempt,))
    reopened = Journal(tmp_path / "db")
    assert reopened.status("A") == "pending"
