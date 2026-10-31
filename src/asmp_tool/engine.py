from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Callable
from uuid import uuid4

from .api import ApiClient, AuthenticationExpired, BusinessRejected, RequestUncertain
from .journal import Journal, RecordBlocked
from .models import Settings, UserError, build_payload, parse_serials, validate_account


@dataclass
class ItemResult:
    serial: str
    state: str
    model: str = ""
    message: str = ""
    data: dict | None = None
    rma_id: str = ""


@dataclass
class Summary:
    total: int
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    queried: int = 0
    processed: int = 0
    stopped: bool = False
    reason: str = ""


class BatchEngine:
    def __init__(self, journal: Journal, client_factory: Callable[[str], ApiClient] = ApiClient):
        self.journal = journal
        self.client_factory = client_factory

    def run(self, text: str, token: str, settings: Settings, stop: Event, *, query_only: bool = False,
            on_item: Callable[[ItemResult], None] = lambda _r: None,
            on_progress: Callable[[int, int], None] = lambda _i, _n: None) -> Summary:
        serials = parse_serials(text)
        if not serials:
            raise UserError("请先粘贴序列号")
        settings.validate(required=not query_only)
        summary = Summary(len(serials))
        if stop.is_set():
            summary.stopped = True
            return summary
        batch_id = str(uuid4())
        with self.client_factory(token) as api:
            info = api.login_info()
            if not query_only:
                validate_account(info, settings)
            for serial in serials:
                if stop.is_set():
                    summary.stopped = True
                    break
                if not query_only:
                    status = self.journal.status(serial)
                    if status == "pending" or status == "succeeded" and settings.skip_success:
                        summary.skipped += 1
                        summary.processed += 1
                        message = "待核对记录始终跳过，请先核对官网历史数据" if status == "pending" else "以前已成功登记，已跳过"
                        on_item(ItemResult(serial, "skipped", message=message))
                        on_progress(summary.processed, summary.total)
                        continue
                on_item(ItemResult(serial, "querying", message="正在查询产品资料"))
                try:
                    data = api.query(serial)
                except (AuthenticationExpired, BusinessRejected, RequestUncertain) as error:
                    message = api.safe(str(error))
                    auth = isinstance(error, AuthenticationExpired)
                    if not query_only:
                        self.journal.record_failure(serial, "", batch_id, message, auth=auth)
                    summary.failed += 1
                    summary.processed += 1
                    on_item(ItemResult(serial, "auth" if auth else "failed", message=message))
                    on_progress(summary.processed, summary.total)
                    if not isinstance(error, BusinessRejected):
                        summary.stopped = True
                        summary.reason = message
                        break
                    if stop.wait(settings.delay_ms / 1000):
                        summary.stopped = True
                        break
                    continue
                model = str(data.get("productModel") or "")
                if stop.is_set():
                    on_item(ItemResult(serial, "cancelled", model, "已停止，未提交此条", data))
                    summary.stopped = True
                    break
                if query_only:
                    summary.queried += 1
                    on_item(ItemResult(serial, "queried", model, "查询成功，未提交", data))
                else:
                    try:
                        payload = build_payload(serial, data, settings)
                    except UserError as error:
                        summary.failed += 1
                        self.journal.record_failure(serial, model, batch_id, str(error))
                        on_item(ItemResult(serial, "failed", model, str(error), data))
                    else:
                        # This transaction re-checks duplicates atomically before persisting intent.
                        try:
                            attempt_id = self.journal.reserve(serial, model, batch_id, skip_success=settings.skip_success)
                        except RecordBlocked as error:
                            summary.skipped += 1
                            on_item(ItemResult(serial, "skipped", model, str(error), data))
                        else:
                            if stop.is_set():
                                self.journal.finish(attempt_id, "rejected", "用户停止，未发出提交请求")
                                summary.stopped = True
                                on_item(ItemResult(serial, "cancelled", model, "已停止，未提交此条", data))
                                break
                            on_item(ItemResult(serial, "submitting", model, "正在提交；停止后等待此请求结果", data))
                            try:
                                rma_id = api.submit(payload)
                            except AuthenticationExpired as error:
                                message = str(error)
                                self.journal.finish(attempt_id, "auth", message)
                                summary.failed += 1
                                summary.stopped = True
                                summary.reason = message
                                on_item(ItemResult(serial, "auth", model, message, data))
                            except BusinessRejected as error:
                                message = api.safe(str(error))
                                self.journal.finish(attempt_id, "rejected", message)
                                summary.failed += 1
                                on_item(ItemResult(serial, "rejected", model, message, data))
                            except Exception:
                                # A sent POST is never replayed, even after an unexpected failure.
                                message = "提交结果待核对，请先查看官网历史数据，禁止直接重试"
                                self.journal.finish(attempt_id, "unknown", message)
                                summary.failed += 1
                                summary.stopped = True
                                summary.reason = message
                                on_item(ItemResult(serial, "unknown", model, message, data))
                            else:
                                self.journal.finish(attempt_id, "succeeded", "成功", rma_id)
                                summary.succeeded += 1
                                on_item(ItemResult(serial, "succeeded", model, "成功", data, rma_id))
                summary.processed += 1
                on_progress(summary.processed, summary.total)
                if summary.stopped:
                    break
                if stop.wait(settings.delay_ms / 1000):
                    summary.stopped = True
                    break
        return summary
