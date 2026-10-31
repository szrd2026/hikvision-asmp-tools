from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4, uuid5, NAMESPACE_URL

from .models import UserError, display_time

STATE_LABELS = {
    "pending": "提交中（待核对）", "unknown": "待核对", "succeeded": "成功",
    "rejected": "明确拒绝", "failed": "查询/校验失败", "auth": "登录失效",
}


class JournalError(UserError):
    pass


class RecordBlocked(UserError):
    def __init__(self, status: str):
        self.status = status
        super().__init__("存在待核对记录，请先在官网历史数据确认" if status == "pending" else "以前已成功登记")


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def digest_rows(rows: list[dict]) -> str:
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def legacy_state(result: str) -> str:
    if result == "成功":
        return "succeeded"
    if "待核对" in result:
        return "pending" if result.startswith("提交中") else "unknown"
    if result.startswith(("失败:", "失败：")):
        message = re.split(r"[:：]", result, maxsplit=1)[1].strip()
        if re.search(r"notLogin|登录已失效|accesstoken.*过期|令牌.*失效", message, re.I):
            return "auth"
        if message.startswith("服务端拒绝") or "人工核对未登记" in message:
            return "rejected"
        if message.startswith(("查询", "一年包换需要")):
            return "failed"
        # v1 discarded the HTTP status/code and called even submit timeouts "failed".
        return "unknown"
    raise JournalError("旧 CSV 中存在未知结果，已停止迁移")


class Journal:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise JournalError("记录数据库来自较新版本，请使用对应版本打开")
            db.execute("PRAGMA journal_mode=WAL")
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise JournalError("提交记录数据库损坏，已停止以防重复登记")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS attempts (
                    id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, serial TEXT NOT NULL,
                    serial_key TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL CHECK(state IN ('pending','unknown','succeeded','rejected','failed','auth')),
                    message TEXT NOT NULL DEFAULT '', rma_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, legacy_source TEXT
                );
                CREATE INDEX IF NOT EXISTS ix_serial ON attempts(serial_key,state);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, attempt_id TEXT NOT NULL REFERENCES attempts(id),
                    state TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                PRAGMA user_version=1;
            """)
            # Repair data created by an earlier prototype of the v2 importer as well.
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute("SELECT id,message FROM attempts WHERE legacy_source IS NOT NULL AND state='rejected'").fetchall():
                if row["message"].startswith(("失败:", "失败：")) and legacy_state(row["message"]) == "unknown":
                    db.execute("UPDATE attempts SET state='unknown',updated_at=? WHERE id=?", (stamp(), row["id"]))
                    self._event(db, row["id"], "unknown", "修正早期迁移：原失败记录缺少明确拒绝依据")
            db.commit()

    @contextmanager
    def connection(self):
        db = None
        try:
            db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            yield db
        except sqlite3.Error as error:
            raise JournalError("提交记录数据库无法读写，请检查权限、磁盘空间或文件完整性；勿直接重试登记") from error
        finally:
            if db is not None:
                if db.in_transaction:
                    db.rollback()
                db.close()

    @staticmethod
    def _status(db, serial: str) -> str | None:
        states = {row[0] for row in db.execute("SELECT state FROM attempts WHERE serial_key=?", (serial.casefold(),))}
        if states & {"pending", "unknown"}:
            return "pending"
        if "succeeded" in states:
            return "succeeded"
        return None

    def status(self, serial: str) -> str | None:
        with self.connection() as db:
            return self._status(db, serial)

    @staticmethod
    def _event(db, attempt_id: str, state: str, note: str) -> None:
        db.execute("INSERT INTO events(attempt_id,state,note,created_at) VALUES(?,?,?,?)", (attempt_id, state, note, stamp()))

    def reserve(self, serial: str, model: str, batch_id: str, *, skip_success: bool) -> str:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            status = self._status(db, serial)
            if status == "pending" or status == "succeeded" and skip_success:
                raise RecordBlocked(status)
            attempt_id, now = str(uuid4()), stamp()
            db.execute("""INSERT INTO attempts(id,batch_id,serial,serial_key,model,state,created_at,updated_at)
                          VALUES(?,?,?,?,?,'pending',?,?)""",
                       (attempt_id, batch_id, serial, serial.casefold(), model, now, now))
            self._event(db, attempt_id, "pending", "请求发出前持久保存提交意图")
            db.commit()  # FULL synchronous: the intent must reach disk before the POST.
            return attempt_id

    def finish(self, attempt_id: str, state: str, message: str, rma_id: str = "") -> None:
        if state not in {"unknown", "succeeded", "rejected", "auth"}:
            raise JournalError("无效的提交结果状态")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("""UPDATE attempts SET state=?,message=?,rma_id=?,updated_at=?
                                    WHERE id=? AND state IN ('pending','unknown')""",
                                 (state, message, rma_id, stamp(), attempt_id)).rowcount
            if not changed:
                raise JournalError("记录状态已经改变，已停止更新")
            self._event(db, attempt_id, state, message)
            db.commit()

    def record_failure(self, serial: str, model: str, batch_id: str, message: str, *, auth: bool = False) -> None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            attempt_id, now = str(uuid4()), stamp()
            state = "auth" if auth else "failed"
            db.execute("""INSERT INTO attempts(id,batch_id,serial,serial_key,model,state,message,created_at,updated_at)
                          VALUES(?,?,?,?,?,?,?,?,?)""",
                       (attempt_id, batch_id, serial, serial.casefold(), model, state, message, now, now))
            self._event(db, attempt_id, state, message)
            db.commit()

    def records(self, search: str = "", *, limit: int = 2000) -> list[dict]:
        with self.connection() as db:
            # instr treats '%' and '_' literally, unlike a user-supplied LIKE pattern.
            return [dict(row) for row in db.execute(
                "SELECT * FROM attempts WHERE instr(serial_key,?)>0 ORDER BY rowid DESC LIMIT ?",
                (search.casefold(), limit),
            )]

    def reconcile(self, attempt_id: str, *, registered: bool, note: str) -> None:
        if not note.strip():
            raise UserError("请填写网页核对结果")
        self.finish(attempt_id, "succeeded" if registered else "rejected", "人工核对：" + note.strip())

    def export_csv(self, path: Path, search: str = "") -> int:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM attempts WHERE instr(serial_key,?)>0 ORDER BY rowid", (search.casefold(),)).fetchall()
        def cell(value):
            text = str(value)
            return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text
        try:
            with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["时间", "序列号", "型号", "结果", "RMA单号", "说明"])
                for row in rows:
                    writer.writerow([cell(display_time(row["created_at"])), cell(row["serial"]), cell(row["model"]),
                                     STATE_LABELS[row["state"]], cell(row["rma_id"]), cell(row["message"])])
            return len(rows)
        except OSError as error:
            raise UserError("无法导出 CSV，请检查文件是否被占用以及目标目录权限") from error

    def import_legacy_csv(self, path: Path) -> int:
        path = Path(path).resolve()
        if not path.exists():
            return 0
        try:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream, strict=True)
                if reader.fieldnames != ["时间", "序列号", "型号", "结果"]:
                    raise JournalError("旧版 CSV 表头异常，请先核对旧记录；未导入任何记录")
                rows = list(reader)
        except (OSError, UnicodeError, csv.Error) as error:
            raise JournalError("旧版 CSV 无法读取或内容损坏，请先核对记录") from error
        if any(set(row) != {"时间", "序列号", "型号", "结果"} or any(v is None for v in row.values())
               or not row["序列号"].strip() or not row["结果"].strip() for row in rows):
            raise JournalError("旧版 CSV 存在不完整记录，已停止迁移")
        source = str(path)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT value FROM metadata WHERE key=?", ("legacy:" + source,)).fetchone()
            previous = json.loads(old[0]) if old else {"count": 0, "digest": digest_rows([])}
            count = previous["count"]
            if len(rows) < count or digest_rows(rows[:count]) != previous["digest"]:
                raise JournalError("已经迁移的旧 CSV 被改写，请先核对记录，避免重复登记")
            for index, row in enumerate(rows[count:], start=count):
                serial, result = row["序列号"].strip(), row["结果"].strip()
                state = legacy_state(result)
                active = db.execute("""SELECT id FROM attempts WHERE legacy_source=? AND serial_key=?
                                       AND state IN ('pending','unknown') ORDER BY rowid DESC LIMIT 1""",
                                    (source, serial.casefold())).fetchone()
                now = stamp()
                if active:
                    attempt_id = active[0]
                    db.execute("UPDATE attempts SET state=?,message=?,updated_at=? WHERE id=?", (state, result, now, attempt_id))
                else:
                    attempt_id = str(uuid5(NAMESPACE_URL, source + ":" + str(index)))
                    db.execute("""INSERT INTO attempts(id,batch_id,serial,serial_key,model,state,message,created_at,updated_at,legacy_source)
                                  VALUES(?,?,?,?,?,?,?,?,?,?)""",
                               (attempt_id, "legacy", serial, serial.casefold(), row["型号"], state, result, row["时间"], now, source))
                self._event(db, attempt_id, state, "旧 CSV 迁移：" + result)
            db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)", ("legacy:" + source, json.dumps({"count": len(rows), "digest": digest_rows(rows)})))
            db.commit()
            return len(rows) - count
