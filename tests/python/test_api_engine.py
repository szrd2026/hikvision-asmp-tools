import json
from dataclasses import replace
from threading import Event

import httpx
import pytest

from asmp_tool.api import ApiClient, AuthenticationExpired, BusinessRejected, RequestUncertain
from asmp_tool.engine import BatchEngine
from asmp_tool.journal import Journal, JournalError
from asmp_tool.models import UserError

TOKEN = "OFFLINE-TEST-TOKEN"


def response(request, status=200, body=None, text=None):
    return httpx.Response(status, json=body, text=text, request=request)


@pytest.mark.parametrize("status,body,text,error", [
    (200, {"code": "003", "data": {"r": "https://evil.invalid"}}, None, AuthenticationExpired),
    (200, {"code": "013"}, None, AuthenticationExpired),
    (401, None, "login", AuthenticationExpired), (403, None, "forbidden", AuthenticationExpired),
    (500, {"code": "000"}, None, RequestUncertain), (302, None, "redirect", RequestUncertain),
    (200, None, "<html>login</html>", RequestUncertain), (200, None, "", RequestUncertain),
    (200, {"code": 0}, None, RequestUncertain), (200, ["bad"], None, RequestUncertain),
    (200, {"code": "999", "msg": "业务拒绝"}, None, BusinessRejected),
])
def test_reply_classification(status, body, text, error):
    with ApiClient(TOKEN, transport=httpx.MockTransport(lambda req: response(req, status, body, text))) as api:
        with pytest.raises(error):
            api.request("POST", "/base/getLoginInfo", data={})


def test_headers_cookie_and_json_encoding():
    def handler(request):
        assert request.url.host == "asmp.hikvision.com"
        assert request.headers["accessToken"] == TOKEN
        assert f"asmp_sr_token={TOKEN}" in request.headers["cookie"]
        assert json.loads(request.content)["serialId"] == 'A"B'
        return response(request, body={"code": "000", "data": {"productModel": "DS"}})
    with ApiClient(TOKEN, transport=httpx.MockTransport(handler)) as api:
        assert api.query('A"B')["productModel"] == "DS"


def test_no_credential_redirect_or_automatic_retry():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(307, headers={"location": "https://evil.invalid"}, request=request)
    with ApiClient(TOKEN, transport=httpx.MockTransport(handler)) as api:
        with pytest.raises(RequestUncertain):
            api.login_info()
        with pytest.raises(UserError):
            api.request("POST", "https://evil.invalid")
    assert len(calls) == 1


def test_server_error_redacts_token():
    with ApiClient(TOKEN, transport=httpx.MockTransport(lambda req: response(req, body={"code": "999", "msg": TOKEN}))) as api:
        with pytest.raises(BusinessRejected) as caught:
            api.login_info()
    assert TOKEN not in str(caught.value)


def factory_for(journal, account, calls, *, submit=None, query=None):
    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("getLoginInfo"):
            return response(request, body={"code": "000", "data": account})
        if request.url.path.endswith("getRmaDetailBySerial"):
            if query:
                return query(request)
            return response(request, body={"code": "000", "data": {"productModel": "DS", "qaCheckResult": "Q"}})
        if request.url.path.endswith("setNewRma"):
            serial = json.loads(request.content)["rmaDetailList"][0]["serialId"]
            assert journal.status(serial) == "pending", "POST attempted before durable intent"
            if submit:
                return submit(request)
            return response(request, body={"code": "000", "data": {"rmaId": "RMA-TEST"}})
        raise AssertionError("unexpected request")
    return lambda token: ApiClient(token, transport=httpx.MockTransport(handler))


def test_complete_batch_deduplicates_and_skips_success(tmp_path, settings, account):
    journal = Journal(tmp_path / "db")
    calls, items = [], []
    engine = BatchEngine(journal, factory_for(journal, account, calls))
    result = engine.run("A\na\nB", TOKEN, settings, Event(), on_item=items.append)
    assert result.succeeded == 2 and result.total == 2
    assert sum(path.endswith("setNewRma") for path in calls) == 2
    assert journal.records()[0]["rma_id"] == "RMA-TEST"
    calls.clear()
    result = engine.run("A\nB", TOKEN, settings, Event())
    assert result.skipped == 2 and len(calls) == 1


@pytest.mark.parametrize("kind", ["timeout", "http500", "html", "empty"])
def test_uncertain_submission_blocks_even_if_skip_unchecked(tmp_path, settings, account, kind):
    journal = Journal(tmp_path / "db")
    calls = []
    def submit(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("arbitrary sensitive text " + TOKEN, request=request)
        if kind == "http500":
            return response(request, 500, {"code": "000"})
        return response(request, text="<html/>" if kind == "html" else "")
    engine = BatchEngine(journal, factory_for(journal, account, calls, submit=submit))
    result = engine.run("A\nB", TOKEN, settings, Event())
    assert result.failed == 1 and result.stopped and journal.status("A") == "pending"
    assert sum(path.endswith("setNewRma") for path in calls) == 1
    calls.clear()
    result = engine.run("A", TOKEN, replace(settings, skip_success=False), Event())
    assert result.skipped == 1 and len(calls) == 1
    assert TOKEN not in json.dumps(journal.records())


def test_expired_submit_stops_batch(tmp_path, settings, account):
    journal = Journal(tmp_path / "db")
    calls = []
    engine = BatchEngine(journal, factory_for(journal, account, calls, submit=lambda req: response(req, body={"code": "013"})))
    result = engine.run("A\nB", TOKEN, settings, Event())
    assert result.stopped and result.failed == 1 and journal.status("A") is None
    assert journal.records()[0]["state"] == "auth"


def test_query_only_never_submits_or_creates_journal(tmp_path, settings, account):
    journal = Journal(tmp_path / "db")
    calls = []
    result = BatchEngine(journal, factory_for(journal, account, calls)).run("A\nB", TOKEN, settings, Event(), query_only=True)
    assert result.queried == 2 and not journal.records()
    assert not any(path.endswith("setNewRma") for path in calls)


def test_stop_during_query_prevents_submit(tmp_path, settings, account):
    journal = Journal(tmp_path / "db")
    calls, stop = [], Event()
    def query(request):
        stop.set()
        return response(request, body={"code": "000", "data": {"productModel": "DS"}})
    result = BatchEngine(journal, factory_for(journal, account, calls, query=query)).run("A", TOKEN, settings, stop)
    assert result.stopped and not journal.records() and len(calls) == 2


def test_stop_after_sent_post_records_result_before_stopping(tmp_path, settings, account):
    journal = Journal(tmp_path / "db")
    calls, stop = [], Event()
    def submit(request):
        stop.set()
        return response(request, body={"code": "000"})
    result = BatchEngine(journal, factory_for(journal, account, calls, submit=submit)).run("A\nB", TOKEN, settings, stop)
    assert result.succeeded == 1 and result.stopped and journal.status("A") == "succeeded"
    assert len(calls) == 3


def test_journal_write_failure_prevents_post(tmp_path, settings, account, monkeypatch):
    journal = Journal(tmp_path / "db")
    calls = []
    def fail(*_a, **_kw):
        raise JournalError("disk full")
    monkeypatch.setattr(journal, "reserve", fail)
    with pytest.raises(JournalError):
        BatchEngine(journal, factory_for(journal, account, calls)).run("A", TOKEN, settings, Event())
    assert len(calls) == 2


def test_journal_result_write_failure_leaves_intent(tmp_path, settings, account, monkeypatch):
    journal = Journal(tmp_path / "db")
    calls = []
    def fail(*_a, **_kw):
        raise JournalError("disk full")
    monkeypatch.setattr(journal, "finish", fail)
    with pytest.raises(JournalError):
        BatchEngine(journal, factory_for(journal, account, calls)).run("A", TOKEN, settings, Event())
    assert journal.status("A") == "pending" and len(calls) == 3


def test_stop_during_durable_reservation_prevents_post(tmp_path, settings, account, monkeypatch):
    journal = Journal(tmp_path / "db")
    calls, stop = [], Event()
    original = journal.reserve
    def reserve(*args, **kwargs):
        attempt = original(*args, **kwargs)
        stop.set()
        return attempt
    monkeypatch.setattr(journal, "reserve", reserve)
    result = BatchEngine(journal, factory_for(journal, account, calls)).run("A", TOKEN, settings, stop)
    assert result.stopped and len(calls) == 2
    assert journal.status("A") is None
