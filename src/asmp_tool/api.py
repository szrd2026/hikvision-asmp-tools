from __future__ import annotations

import re
from typing import Any

import httpx

from .models import API_BASE, ORIGIN, TOKEN_COOKIE, UserError, validate_token


class AuthenticationExpired(UserError):
    pass


class RequestUncertain(UserError):
    """Transport/protocol failure, never evidence that a submission was rejected."""


class BusinessRejected(UserError):
    pass


class ApiClient:
    ENDPOINTS = {
        ("POST", "/base/getLoginInfo"), ("GET", "/base/getConfigList"),
        ("GET", "/base/getProvinceCityArea"),
        ("POST", "/rmaManage/getRmaDetailBySerial"), ("POST", "/rmaManage/setNewRma"),
    }

    def __init__(self, token: str, *, transport: httpx.BaseTransport | None = None):
        self.token = validate_token(token)
        self.client = httpx.Client(
            timeout=httpx.Timeout(90.0, connect=20.0), follow_redirects=False,
            transport=transport,
            headers={"accessToken": self.token, "Origin": ORIGIN, "Referer": ORIGIN + "/sr/"},
        )
        self.client.cookies.set(TOKEN_COOKIE, self.token, domain="asmp.hikvision.com", path="/")

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *_args) -> None:
        self.client.close()

    def safe(self, text: Any) -> str:
        text = str(text).replace(self.token, "[令牌已隐藏]")
        text = re.sub(r"(?i)(access_?token|asmp_sr_token)(\s*[=:]\s*)[^\s&\"<>]+", r"\1\2[已隐藏]", text)
        return text[:1000]

    def request(self, method: str, endpoint: str, *, data: dict | None = None, params: dict | None = None) -> dict:
        if (method, endpoint) not in self.ENDPOINTS:
            raise UserError("请求不在 ASMP 官方接口允许列表中")
        try:
            response = self.client.request(method, API_BASE + endpoint, json=data, params=params)
        except httpx.HTTPError as error:
            raise RequestUncertain("网络连接失败或请求超时") from error
        try:
            body = response.json()
        except (ValueError, UnicodeError):
            body = None
        code = body.get("code") if isinstance(body, dict) else None
        msg = self.safe(body.get("msg") or "") if isinstance(body, dict) else ""
        if response.status_code in (401, 403) or code in ("003", "013") or re.search(r"notLogin|未登录|登录失效|登录过期|重新登录", msg, re.I):
            raise AuthenticationExpired("登录已失效，请重新通过官方网页登录")
        if not 200 <= response.status_code < 300:
            raise RequestUncertain(f"HTTP {response.status_code}，无法确认请求结果")
        if not isinstance(body, dict) or not isinstance(code, str) or not code:
            raise RequestUncertain("服务器响应格式异常，无法确认请求结果")
        if code != "000":
            raise BusinessRejected(msg or f"服务端拒绝请求（{self.safe(code)}）")
        return body

    def login_info(self) -> dict:
        data = self.request("POST", "/base/getLoginInfo", data={}).get("data")
        if not isinstance(data, dict) or not isinstance(data.get("currentUser"), dict) or not data["currentUser"]:
            raise AuthenticationExpired("未取得有效的登录信息，请重新登录")
        return data

    def fault_options(self) -> list[str]:
        data = self.request("GET", "/base/getConfigList", params={"type": 1}).get("data")
        if not isinstance(data, list):
            return []
        return list(dict.fromkeys(str(item["configContent"]) for item in data if isinstance(item, dict) and item.get("configContent")))

    def query(self, serial: str) -> dict:
        data = self.request("POST", "/rmaManage/getRmaDetailBySerial", data={"serialId": serial}).get("data")
        if not isinstance(data, dict) or not data.get("productModel"):
            raise BusinessRejected("未查到有效产品资料，请核对序列号")
        return data

    def regions(self, level: str, parent_code: str = "") -> list[dict[str, str]]:
        if level not in {"province", "city", "district"} or level != "province" and not parent_code:
            raise UserError("请先选择上级行政区域")
        data = self.request("GET", "/base/getProvinceCityArea", params={
            "locationType": level, "parentCode": parent_code, "keyword": "",
        }).get("data")
        if not isinstance(data, list):
            raise UserError("省市区资料格式异常，请重新加载")
        options = []
        for item in data:
            if (not isinstance(item, dict) or not isinstance(item.get("locationName"), str)
                    or not item["locationName"].strip() or not item.get("locationCode")):
                raise UserError("省市区资料不完整，请重新加载")
            options.append({"name": item["locationName"], "code": str(item["locationCode"])})
        return options

    def submit(self, payload: dict) -> str:
        data = self.request("POST", "/rmaManage/setNewRma", data=payload).get("data")
        return str(data.get("rmaId") or "") if isinstance(data, dict) else ""
