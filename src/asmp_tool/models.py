from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

ORIGIN = "https://asmp.hikvision.com"
API_BASE = ORIGIN + "/api/sendRepairWeb"
LOGIN_URL = ORIGIN + "/sr/#/receiving/registration"
TOKEN_COOKIE = "asmp_sr_token"
CHINA_TIME = timezone(timedelta(hours=8))
FAULT_OPTIONS = ["无图像", "不断重启", "搜索不到", "硬盘/SD卡故障", "不上电", "不能录像", "外观异常", "密码错误", "其他"]
DEAL_OPTIONS = {"0": "维修", "1": "一年包换", "2": "本地服务"}
REPAIR_OPTIONS = {"0": "送修", "1": "上门取件", "2": "寄修"}


class UserError(Exception):
    """An actionable error whose text is safe to display to the operator."""


def display_time(value: str) -> str:
    try:
        moment = datetime.fromisoformat(value)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=CHINA_TIME)
        return moment.astimezone(CHINA_TIME).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


@dataclass(frozen=True)
class Settings:
    repair_client: str = ""
    linkman: str = ""
    linknumber: str = ""
    reback_fault: str = "其他"
    fault_text: str = ""
    deal_type: str = "2"
    repair_mode: str = "2"
    delay_ms: int = 500
    skip_success: bool = True

    def validate(self, *, required: bool = True) -> None:
        for name, value in [("送修客户", self.repair_client), ("联系人", self.linkman),
                            ("电话", self.linknumber), ("故障类型", self.reback_fault),
                            ("故障描述", self.fault_text)]:
            if not isinstance(value, str):
                raise UserError(f"{name}必须为文本")
            if required and not value.strip():
                raise UserError(f"请填写{name}")
            if len(value) > 4000 or any(ord(c) < 32 and c not in "\r\n\t" for c in value):
                raise UserError(f"{name}内容过长或含非法控制字符")
        if self.deal_type not in DEAL_OPTIONS or self.repair_mode not in REPAIR_OPTIONS:
            raise UserError("处理方式或接修方式无效")
        if type(self.delay_ms) is not int or not 0 <= self.delay_ms <= 600000:
            raise UserError("间隔必须是 0 至 600000 毫秒的整数")
        if type(self.skip_success) is not bool:
            raise UserError("跳过历史成功记录的设置无效")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        if not isinstance(data, dict):
            raise UserError("配置必须是 JSON 对象")
        try:
            raw_delay = data.get("delay", 500)
            if isinstance(raw_delay, bool) or not re.fullmatch(r"\d+", str(raw_delay)):
                raise ValueError
            settings = cls(
                repair_client=data.get("repairClient", ""), linkman=data.get("linkman", ""),
                linknumber=data.get("linknumber", ""), reback_fault=data.get("rebackFault", "其他"),
                fault_text=data.get("rebackFaulttext", ""), deal_type=str(data.get("dealType", "2")),
                repair_mode=str(data.get("repairMode", "2")), delay_ms=int(raw_delay),
                skip_success=data.get("skip", True),
            )
            settings.validate(required=False)
            return settings
        except (ValueError, TypeError) as error:
            raise UserError("配置中的间隔格式无效") from error

    def to_dict(self) -> dict[str, Any]:
        return {
            "repairClient": self.repair_client, "linkman": self.linkman, "linknumber": self.linknumber,
            "rebackFault": self.reback_fault, "rebackFaulttext": self.fault_text,
            "dealType": self.deal_type, "repairMode": self.repair_mode,
            "delay": self.delay_ms, "skip": self.skip_success,
        }


@dataclass(frozen=True)
class Session:
    token: str = field(repr=False)


def validate_token(token: str) -> str:
    token = token.strip()
    if not token:
        raise UserError("请先登录或粘贴登录令牌")
    if len(token) > 16384 or any(ord(c) < 33 or ord(c) > 126 or c in ';,"\\' for c in token):
        raise UserError("令牌格式无效，请重新通过官方网页登录获取")
    return token


def parse_serials(text: str) -> list[str]:
    seen: set[str] = set()
    serials = []
    for value in re.split(r"[\r\n\t,，;；]+", text):
        value = value.strip()
        if not value:
            continue
        if len(value) > 128 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 or c in '\\"' for c in value):
            raise UserError("序列号含空白、非法字符或超过 128 字符，请只复制序列号列")
        if value.casefold() not in seen:
            serials.append(value)
            seen.add(value.casefold())
    return serials


def validate_account(info: dict[str, Any], settings: Settings) -> None:
    user = info.get("currentUser") or {}
    permissions = user.get("permissionList") or []
    if not any(p.get("code") == "SR02" and type(p.get("value")) is int and p["value"] == 0
               for p in permissions if isinstance(p, dict)):
        raise UserError("当前账号没有收货登记权限（SR02）")
    point = info.get("currentCollectingPoint") or {}
    local = point.get("localRepair") == 1 or point.get("hikExchange") == 1
    if local and settings.deal_type != "2":
        raise UserError("当前网点在网页中固定为本地服务，请选择处理方式“本地服务”")
    if not local and settings.deal_type == "2":
        raise UserError("当前网点没有本地服务权限，请按官网支持的方式设置")


def build_payload(serial: str, data: dict[str, Any], settings: Settings) -> dict[str, Any]:
    settings.validate()
    if not isinstance(data, dict) or not data.get("productModel"):
        raise UserError("查询未返回产品型号，已阻止提交")
    if settings.deal_type == "1":
        if data.get("hxwl") != "Y" or not data.get("clientName"):
            raise UserError("此产品不符合网页的一年包换条件，请在官网核对")
        if str(data.get("changeType")) not in {"0", "1"}:
            raise UserError("一年包换需要选择更换方式，请在网页完成这类登记")
    detail: dict[str, Any] = {
        "uuid": str(uuid4()), "isSend": 1, "serialId": serial,
        "rebackFault": settings.reback_fault, "rebackFaulttext": settings.fault_text,
        "dealType": settings.deal_type,
        "changeType": str(data["changeType"]) if settings.deal_type == "1" else "",
        "stateStr": "new", "isEdit": True, "addType": "hand", "isSerial": True,
        "isExchangeAmountMaterial": data.get("isExchangeAmountMaterial") or 0,
    }
    for key in ("productModel", "repairEndtime", "repairSituation", "clientName", "randomAttach",
                "saleTime", "hxwl", "xltyp", "qaCheckResult", "qaCheckContent", "qaCheckUser", "qaCheckTime",
                "materialCategoryCode", "materialGroup", "materialNumber", "materialDesc",
                "salesOrderNum", "salesOrderLineNum", "customerId"):
        detail[key] = data.get(key) if data.get(key) is not None else ""
    if data.get("zprPrice") is not None:
        detail["zprPrice"] = data["zprPrice"]
    return {
        "createTime": datetime.now(CHINA_TIME).strftime("%Y-%m-%d %H:%M:%S"),
        "city": "", "area": "", "province": None, "address": None, "fax": None, "remark": None,
        "repairClient": settings.repair_client, "linkman": settings.linkman, "linknumber": settings.linknumber,
        "repairMode": int(settings.repair_mode), "isSend": 1, "state": 1, "isMessage": "0",
        "rmaDetailList": [detail],
    }
