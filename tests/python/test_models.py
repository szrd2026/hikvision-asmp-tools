from dataclasses import replace

import pytest

from asmp_tool.models import Settings, Session, UserError, build_payload, display_time, parse_serials, validate_account, validate_token
from asmp_tool.ui.login import cookie_token, official_url


@pytest.mark.parametrize("text,expected", [
    ("A\nB\r\nA", ["A", "B"]), ("A\ta，B;C；c", ["A", "B", "C"]),
    ("", []), (" A-001 \nB_002", ["A-001", "B_002"]), ("A,A,a", ["A"]),
])
def test_serial_normalization(text, expected):
    assert parse_serials(text) == expected


@pytest.mark.parametrize("text", ['A"B', "A B", "A\\B", "A\x00B", "A" * 129, "A\u3000B"])
def test_bad_serials(text):
    with pytest.raises(UserError):
        parse_serials(text)


@pytest.mark.parametrize("value", [-1, 600001, True, 1.5, "500"])
def test_delay_validation(settings, value):
    with pytest.raises(UserError):
        replace(settings, delay_ms=value).validate()


def test_empty_defaults_can_be_saved_but_not_submitted():
    Settings().validate(required=False)
    with pytest.raises(UserError):
        Settings().validate()


def test_legacy_settings_round_trip(settings):
    old = settings.to_dict() | {"delay": "500", "token": "not-for-persistence"}
    result = Settings.from_dict(old)
    assert result.delay_ms == 500
    assert "token" not in result.to_dict()
    assert result.repair_client == settings.repair_client


@pytest.mark.parametrize("value", [True, -1, "abc", "2147483648"])
def test_invalid_config_delay(value):
    with pytest.raises(UserError):
        Settings.from_dict({"delay": value})


def test_account_constraints(settings, account):
    validate_account(account, settings)
    with pytest.raises(UserError):
        validate_account(account, replace(settings, deal_type="0"))
    account["currentCollectingPoint"]["localRepair"] = 0
    with pytest.raises(UserError):
        validate_account(account, settings)
    validate_account(account, replace(settings, deal_type="0"))
    account["currentUser"]["permissionList"][0]["value"] = False
    with pytest.raises(UserError):
        validate_account(account, replace(settings, deal_type="0"))


def test_payload_preserves_web_contract(settings):
    data = {"productModel": "DS-TEST", "qaCheckResult": "Q", "randomAttach": "电源", "xltyp": "TYPE", "zprPrice": 12.5,
            "customerId": "123", "salesOrderLineNum": "001"}
    payload = build_payload("SERIAL001", data, settings)
    detail = payload["rmaDetailList"][0]
    assert payload["isSend"] == 1 and payload["isMessage"] == "0" and payload["state"] == 1
    assert payload["repairMode"] == 2
    assert detail["isExchangeAmountMaterial"] == 0
    assert detail["qaCheckResult"] == "Q" and detail["randomAttach"] == "电源" and detail["xltyp"] == "TYPE"
    assert detail["salesOrderLineNum"] == "001" and detail["zprPrice"] == 12.5
    assert detail["changeType"] == "" and len(payload["rmaDetailList"]) == 1
    assert build_payload("A", {"productModel": "DS"}, settings)["rmaDetailList"][0].get("zprPrice") is None


@pytest.mark.parametrize("data", [{}, {"productModel": "DS", "changeType": 0},
                                    {"productModel": "DS", "hxwl": "Y", "clientName": "CLIENT"}])
def test_incomplete_exchange_rejected(settings, data):
    with pytest.raises(UserError):
        build_payload("A", data, replace(settings, deal_type="1"))


def test_complete_exchange(settings):
    data = {"productModel": "DS", "hxwl": "Y", "clientName": "CLIENT", "changeType": 0}
    assert build_payload("A", data, replace(settings, deal_type="1"))["rmaDetailList"][0]["changeType"] == "0"


@pytest.mark.parametrize("mode", ["0", "1"])
def test_return_mode_matches_header_and_every_detail(settings, mode):
    configured = replace(settings, return_mode=mode, province="测试省", city="测试市", area="测试区", address="测试路1号")
    payload = build_payload("A", {"productModel": "DS"}, configured)
    assert type(payload["isSend"]) is int and payload["isSend"] == int(mode)
    assert all(detail["isSend"] == payload["isSend"] for detail in payload["rmaDetailList"])
    if mode == "0":
        assert [payload[key] for key in ("province", "city", "area", "address")] == ["测试省", "测试市", "测试区", "测试路1号"]
    else:
        assert not any(payload[key] for key in ("province", "city", "area", "address"))
    assert Settings.from_dict(configured.to_dict()) == configured


@pytest.mark.parametrize("field", ["province", "city", "area", "address"])
def test_return_to_customer_requires_complete_address_only_on_submit(settings, field):
    configured = replace(settings, return_mode="0", province="测试省", city="测试市", area="测试区", address="测试路1号")
    incomplete = replace(configured, **{field: "  "})
    incomplete.validate(required=False)
    with pytest.raises(UserError, match="寄回客户"):
        build_payload("A", {"productModel": "DS"}, incomplete)


@pytest.mark.parametrize("mode", ["", "2", "寄回客户", None, True])
def test_invalid_return_mode_cannot_be_submitted(settings, mode):
    with pytest.raises(UserError, match="返回方式"):
        replace(settings, return_mode=mode).validate()


def test_v2_config_without_return_mode_keeps_original_delivery_behavior(settings):
    old = settings.to_dict()
    for key in ("isSend", "province", "city", "area", "address"):
        old.pop(key)
    assert Settings.from_dict(old).return_mode == "1"
    assert Settings.from_dict(old | {"isSend": 0}).return_mode == "0"


@pytest.mark.parametrize("value", ["", "abc\r\nheader", "a;b", 'a"b', "a b", "a" * 16385])
def test_token_validation(value):
    with pytest.raises(UserError):
        validate_token(value)


def test_session_never_reprs_secret():
    assert "SECRET" not in repr(Session("SECRET"))


def test_record_times_use_service_timezone():
    assert display_time("2026-10-31T01:00:00+00:00") == "2026-10-31 09:00:00"
    assert display_time("2026-10-31 09:00:00") == "2026-10-31 09:00:00"


@pytest.mark.parametrize("url", ["https://asmp.hikvision.com/sr/#/login", "https://asmp.hikvision.com:443/sr/"])
def test_official_navigation(url):
    assert official_url(url)


@pytest.mark.parametrize("url", ["http://asmp.hikvision.com/", "https://evil.com/", "https://asmp.hikvision.com.evil.com/",
                                  "https://evil@asmp.hikvision.com/", "file:///tmp/test", "https://asmp.hikvision.com:444/"])
def test_official_navigation_restricts_origin(url):
    assert not official_url(url)


@pytest.mark.parametrize("name,domain,path,expected", [
    ("asmp_sr_token", "asmp.hikvision.com", "/", "TOKEN"),
    ("asmp_sr_token", ".hikvision.com", "/api", "TOKEN"),
    ("other", "asmp.hikvision.com", "/", ""),
    ("asmp_sr_token", "evil.com", "/", ""),
    ("asmp_sr_token", "asmp.hikvision.com", "/sr/", ""),
    ("asmp_sr_token", "asmp.hikvision.com", "/api/send", ""),
])
def test_cookie_scope(name, domain, path, expected):
    assert cookie_token(name, "TOKEN", domain, path) == expected
