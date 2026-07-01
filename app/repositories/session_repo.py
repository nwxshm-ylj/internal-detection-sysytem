"""Session / Frame repository.

封装对 InspectionSession 与 InspectionFrame 的数据库访问。
所有写操作均显式 commit，便于 API 层捕获唯一约束冲突做幂等返回。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.inspection_session import InspectionFrame, InspectionSession


# =========================
# Session
# =========================
def find_session_by_id(session_id: int) -> Optional[InspectionSession]:
    return db.session.get(InspectionSession, session_id)


def find_session_by_vin_client(vin: str, client_session_id: str) -> Optional[InspectionSession]:
    return (
        db.session.query(InspectionSession)
        .filter(
            InspectionSession.vin == vin,
            InspectionSession.client_session_id == client_session_id,
        )
        .one_or_none()
    )


def create_session(
    *,
    vin: str,
    client_session_id: str,
    standard: dict,
) -> InspectionSession:
    """创建会话；返回新对象（commit 由调用方负责）。"""
    sess = InspectionSession(
        vin=vin,
        client_session_id=client_session_id,
        status="RUNNING",
        standard_json=json.dumps(standard, ensure_ascii=False, default=str),
        frame_count=0,
    )
    db.session.add(sess)
    return sess


def finalize_session(
    session_id: int,
    *,
    aggregated: dict,
    compare_info: dict,
    overall: str,
    status: str = "FINISHED",
) -> Optional[InspectionSession]:
    """结束会话：写入聚合结果 + 比对结果 + 状态。"""
    sess = find_session_by_id(session_id)
    if sess is None:
        return None

    sess.aggregated_json = json.dumps(aggregated, ensure_ascii=False, default=str)
    sess.compare_json = json.dumps(compare_info, ensure_ascii=False, default=str)
    sess.overall = overall
    sess.status = status
    sess.finished_at = datetime.utcnow()
    return sess


def increment_frame_count(session_id: int) -> None:
    """帧数 +1（原子累加由 session 自身维护）。"""
    sess = find_session_by_id(session_id)
    if sess is None:
        return
    sess.frame_count = (sess.frame_count or 0) + 1


# =========================
# Frame
# =========================
def find_frame(session_id: int, frame_index: int) -> Optional[InspectionFrame]:
    return (
        db.session.query(InspectionFrame)
        .filter(
            InspectionFrame.session_id == session_id,
            InspectionFrame.frame_index == frame_index,
        )
        .one_or_none()
    )


def list_frames(session_id: int) -> List[InspectionFrame]:
    return (
        db.session.query(InspectionFrame)
        .filter(InspectionFrame.session_id == session_id)
        .order_by(InspectionFrame.frame_index.asc())
        .all()
    )


def create_frame(
    *,
    session_id: int,
    frame_index: int,
    image_path: str,
    detected: dict,
) -> InspectionFrame:
    """创建帧记录（调用方负责 commit）。"""
    frame = InspectionFrame(
        session_id=session_id,
        frame_index=frame_index,
        image_path=image_path,
        detected_json=json.dumps(detected, ensure_ascii=False, default=str),
    )
    db.session.add(frame)
    return frame


def commit_or_rollback() -> bool:
    """统一 commit 入口；冲突时 rollback 并返回 False。"""
    try:
        db.session.commit()
        return True
    except IntegrityError:
        db.session.rollback()
        return False