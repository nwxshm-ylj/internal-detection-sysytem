"""Encapsulate database access for inspection records.

集中管理 `InspectionRecord` CRUD，避免视图层直接处理 session。
"""

from __future__ import annotations

import json

from app.extensions import db
from app.models.inspection import InspectionRecord


def save_record(vin: str, client_event_id: str, image_path: str, standard: dict, detected: dict, compare_info: dict) -> int:
    rec = InspectionRecord(
        vin=vin,
        client_event_id=client_event_id,
        image_path=image_path,
        standard_json=json.dumps(standard, ensure_ascii=False, default=str),
        detected_json=json.dumps(detected, ensure_ascii=False, default=str),
        compare_json=json.dumps(compare_info, ensure_ascii=False, default=str),
        overall=compare_info.get("overall"),
    )
    try:
        db.session.add(rec)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return rec.id



def find_by_vin_event(*, vin: str, client_event_id: str):
    """根据 VIN + client_event_id 唯一键查询记录。"""
    return (
        db.session.query(InspectionRecord)
        .filter(
            InspectionRecord.vin == vin,
            InspectionRecord.client_event_id == client_event_id,
        )
        .one_or_none()
    )
