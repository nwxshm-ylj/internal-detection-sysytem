from __future__ import annotations

import json
from typing import Any, Dict, Optional, Union

import requests
from flask import current_app
from requests import Session

from zeep import Client
from zeep.exceptions import Fault
from zeep.transports import Transport


# =========================
# Errors
# =========================
class LesClientError(RuntimeError):
    """标准配置（LES）调用失败异常。"""


class PRServiceError(RuntimeError):
    """PR SOAP 调用失败异常。"""


# =========================
# SOAP PR (你现有能力保留)
# =========================
def _build_zeep_client(wsdl_url: str) -> Client:
    timeout = float(current_app.config.get("PR_SOAP_TIMEOUT", 5.0))
    verify_ssl = bool(current_app.config.get("PR_SOAP_VERIFY_SSL", False))

    session = Session()
    session.verify = verify_ssl
    transport = Transport(session=session, timeout=timeout)
    return Client(wsdl=wsdl_url, transport=transport)


def fetch_pr_group(vin_or_vins: Union[str, list[str]]) -> Dict[str, Any]:
    wsdl_url = current_app.config.get(
        "PR_SOAP_WSDL_URL",
        "http://172.29.76.49:47220/backend/services/IPrService?wsdl",
    )

    try:
        client = _build_zeep_client(wsdl_url)
        resp = client.service.prGroup(vin_or_vins)

        if isinstance(resp, str):
            data = json.loads(resp)
        else:
            data = resp if isinstance(resp, dict) else json.loads(json.dumps(resp, default=str))

        if not isinstance(data, dict):
            raise PRServiceError(f"PR SOAP unexpected response type: {type(data)}")

        if not data.get("success"):
            raise PRServiceError(f"PR SOAP call failed: {data!r}")

        result = data.get("result")
        if not isinstance(result, list) or len(result) == 0:
            raise PRServiceError("PR SOAP result empty")

        return data

    except Fault as e:
        raise PRServiceError(f"PR SOAP Fault: {e}") from e
    except json.JSONDecodeError as e:
        raise PRServiceError(f"PR SOAP JSON decode error: {e}") from e
    except Exception as e:
        raise PRServiceError(f"PR SOAP exception: {e}") from e


def extract_pr_group_from_response(data: Dict[str, Any], vin: str) -> Optional[str]:
    result = data.get("result", [])
    if not isinstance(result, list):
        return None

    vin_u = (vin or "").strip().upper()
    for row in result:
        if not isinstance(row, dict):
            continue
        row_vin = str(row.get("vin") or row.get("VIN") or "").strip().upper()
        if row_vin and row_vin != vin_u:
            continue

        pr = row.get("prGroup") or row.get("pr_group") or row.get("prgroup") or row.get("PRGROUP")
        return str(pr).strip() if pr is not None else None

    row0 = result[0]
    if isinstance(row0, dict):
        pr = row0.get("prGroup") or row0.get("pr_group") or row0.get("prgroup") or row0.get("PRGROUP")
        return str(pr).strip() if pr else None

    return None


# =========================
# HTTP LES Standard Config (未来可用)
# =========================
def _fetch_les_http(vin: str) -> Dict[str, Any]:
    """
    未来你们内网 LES HTTP 接口可用时使用。
    约定：GET LES_API_URL?vin=xxxx，返回 json。
    """
    url = current_app.config.get("LES_API_URL")
    timeout = float(current_app.config.get("LES_API_TIMEOUT", 3.0))

    if not url:
        raise LesClientError("LES_API_URL not configured")

    try:
        r = requests.get(url, params={"vin": vin}, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        raise LesClientError(f"LES HTTP request failed: {e}") from e
    except ValueError as e:
        raise LesClientError(f"LES HTTP response not JSON: {e}") from e


# =========================
# Unified Entry: fetch_les_by_vin (你缺的就是它)
# =========================
def fetch_les_by_vin(vin: str) -> Dict[str, Any]:
    """
    标准配置统一入口：
    - 优先走 HTTP LES（如果你们有这个接口并可访问）
    - 如只需要 prGroup 或 HTTP 不可用，可配置走 SOAP PR 再拼装
    返回 dict：至少包含 prGroup 字段（供 standard_service 解析）
    """
    vin = (vin or "").strip()
    if not vin:
        raise LesClientError("vin is empty")

    mode = (current_app.config.get("LES_MODE") or "http").lower()
    # LES_MODE:
    #  - "http": 走 LES HTTP 标准接口（默认）
    #  - "soap_pr_only": 仅走 SOAP 拉 prGroup（临时过渡）
    #  - "auto": 先 http 失败则走 soap_pr_only（推荐）

    if mode not in ("http", "soap_pr_only", "auto"):
        mode = "http"

    if mode in ("http", "auto"):
        try:
            raw = _fetch_les_http(vin)
            # 保证至少有 vin
            if isinstance(raw, dict):
                raw.setdefault("vin", vin)
            return raw
        except Exception:
            if mode == "http":
                raise
            # auto: 继续 fallback 到 soap_pr_only

    # soap_pr_only：只拿 prGroup，然后拼一个最小 raw 返回
    try:
        data = fetch_pr_group(vin)
        pr_group = extract_pr_group_from_response(data, vin) or ""
        return {
            "vin": vin,
            "prGroup": pr_group,
            "source": "soap_pr_only",
        }
    except PRServiceError as e:
        raise LesClientError(f"LES fallback SOAP PR failed: {e}") from e


        
