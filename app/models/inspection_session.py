"""Session-level inspection models.

新版（v2）检测以"会话"为单位：一辆车一次检测 = 一个 Session + N 帧（Frame）。

- InspectionSession：会话主表，存储 VIN、标准配置、聚合后的判定结果。
- InspectionFrame：单帧子表，存储每次拍照的原始识别结果。

兼容性说明：
- 旧的单图模型 app/models/inspection.py 仍保留，供 v1 API 使用。
- v2 流程统一走 Session/Frame。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.extensions import db


def _safe_json_loads(s: str | None, default: Any):
    if not s:
        return default
    try:
        return json.loads(s)
    except Exception:
        return default


class InspectionSession(db.Model):
    """一次车辆检测会话（一辆车 = 一个会话）。"""

    __tablename__ = "inspection_session"

    id = db.Column(db.Integer, primary_key=True)
    vin = db.Column(db.String(32), index=True, nullable=False)

    # 客户端生成的会话幂等键（同 vin + 同 session_id 不会重复创建）
    client_session_id = db.Column(db.String(64), nullable=False)

    # 会话状态：RUNNING（拍摄中）/ FINISHED（已聚合判定）/ ABORTED（被中止）
    status = db.Column(db.String(16), nullable=False, default="RUNNING")

    # 标准配置快照（开始会话时从 PR / LES 拉取并冻结，避免聚合阶段配置变更）
    standard_json = db.Column(db.Text, nullable=True)

    # 聚合后的检测结果：{feature: {label, confidence, frame_count, ...}}
    aggregated_json = db.Column(db.Text, nullable=True)

    # 比对结果：{compare_result: {...}, overall: "OK"/"NG"/"UNKNOWN"}
    compare_json = db.Column(db.Text, nullable=True)
    overall = db.Column(db.String(8), nullable=True)

    # 帧总数（便于快速展示）
    frame_count = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    finished_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("vin", "client_session_id", name="uq_session_vin_client"),
    )

    # 关联帧（一对多）
    frames = db.relationship(
        "InspectionFrame",
        backref="session",
        cascade="all, delete-orphan",
        order_by="InspectionFrame.frame_index",
    )

    def to_payload(self, include_frames: bool = False) -> dict:
        compare_info = _safe_json_loads(self.compare_json, {})
        payload = {
            "session_id": self.id,
            "vin": self.vin,
            "client_session_id": self.client_session_id,
            "status": self.status,
            "standard": _safe_json_loads(self.standard_json, {}),
            "aggregated": _safe_json_loads(self.aggregated_json, {}),
            "compare_result": compare_info.get("compare_result", {}),
            "overall": self.overall,
            "frame_count": self.frame_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
        if include_frames:
            payload["frames"] = [f.to_payload() for f in self.frames]
        return payload


class InspectionFrame(db.Model):
    """会话中的单帧记录（一张图一条）。"""

    __tablename__ = "inspection_frame"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer,
        db.ForeignKey("inspection_session.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 帧序号（APP 端连续拍摄时的顺序，0 开始）
    frame_index = db.Column(db.Integer, nullable=False, default=0)

    image_path = db.Column(db.String(255), nullable=True)

    # 该帧检测出的所有零件信息：
    # {feature_name: {label, conf, bbox, lab_meta, ...}}
    detected_json = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("session_id", "frame_index", name="uq_frame_session_index"),
    )

    def to_payload(self) -> dict:
        return {
            "frame_id": self.id,
            "session_id": self.session_id,
            "frame_index": self.frame_index,
            "image_path": self.image_path,
            "detected": _safe_json_loads(self.detected_json, {}),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }