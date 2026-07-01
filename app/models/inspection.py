from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.extensions import db


def safe_json_loads(s: str | None, default: Any):
    """
    安全解析 JSON 字符串：
    - s 为空 / None：返回 default
    - s 不是合法 JSON：返回 default
    """
    if not s:
        return default
    try:
        return json.loads(s)
    except Exception:
        return default


class InspectionRecord(db.Model):
    __tablename__ = "inspection_record"

    id = db.Column(db.Integer, primary_key=True)
    vin = db.Column(db.String(32), index=True, nullable=False)
    client_event_id = db.Column(db.String(64), nullable=False)

    image_path = db.Column(db.String(255), nullable=True)

    standard_json = db.Column(db.Text, nullable=True)
    detected_json = db.Column(db.Text, nullable=True)
    compare_json = db.Column(db.Text, nullable=True)
    overall = db.Column(db.String(8), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("vin", "client_event_id", name="uq_vin_client_event"),
    )

    def to_payload(self) -> dict:
        compare_info = safe_json_loads(self.compare_json, {})
        return {
            "record_id": self.id,
            "vin": self.vin,
            "client_event_id": self.client_event_id,
            "image_path": self.image_path,
            "standard": safe_json_loads(self.standard_json, {}),
            "detected": safe_json_loads(self.detected_json, {}),
            "compare_result": compare_info.get("compare_result", {}),
            "overall": self.overall,
        }
