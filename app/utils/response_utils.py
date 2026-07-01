"""Utility helpers for building consistent API responses.

统一 API 返回结构，加入 trace_id 便于链路追踪。
"""

from __future__ import annotations

import uuid

from flask import request


def _trace_id() -> str:
    """返回请求头中的 trace id；若缺失则自动生成。"""
    return request.headers.get("X-Trace-Id") or uuid.uuid4().hex


def ok(data=None, msg="ok", code=200):
    """标准成功返回体。"""
    return {"code": code, "msg": msg, "data": data, "trace_id": _trace_id()}


def fail(msg="error", code=400, data=None):
    """标准失败返回体。"""
    return {"code": code, "msg": msg, "data": data, "trace_id": _trace_id()}
