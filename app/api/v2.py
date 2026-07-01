"""REST API v2: 会话化检测流程。

端点：
- POST /api/v2/session/start        开启会话（拉标准配置，返回 session_id）
- POST /api/v2/session/<id>/frame   上传单帧图片（实时识别，返回该帧识别结果）
- POST /api/v2/session/<id>/finish  结束会话（聚合所有帧 → 比对 → 写库 → 返回最终判定）
- GET  /api/v2/session/<id>          查询会话详情（含全部帧，仅供调试/管理端）
- GET  /api/v2/health                健康检查（兼容 v1）

旧 v1 (/api/v1/*) 保持不变，新流程统一走 v2。
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime

import cv2
import numpy as np
from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.repositories import session_repo
from app.repositories.color_prototype_repo import get_prototypes
from app.repositories.session_repo import (
    commit_or_rollback,
    create_frame,
    create_session,
    find_frame,
    find_session_by_id,
    find_session_by_vin_client,
    increment_frame_count,
    list_frames,
    finalize_session,
)
from app.services.aggregation_service import aggregate_frames
from app.services.color_calibration_service import update_prototype_from_roi
from app.services.compare_service import compare_configs
from app.services.inference_service_v2 import infer_frame
from app.services.standard_service import get_standard_config
from app.utils.response_utils import fail, ok

api_v2_bp = Blueprint("api_v2", __name__, url_prefix="/api/v2")


# =========================
# 通用工具
# =========================
def _save_image(image_storage, vin: str, client_session_id: str, frame_index: int = 0) -> tuple[str, str]:
    """
    保存上传图片到 UPLOAD_DIR/YYYYMMDD/{vin}_{cid}_{idx}.jpg
    返回 (abs_path, rel_path)
    """
    data = image_storage.read()
    if not data:
        raise ValueError("empty image")

    base_dir = current_app.config["UPLOAD_DIR"]
    day_dir = datetime.now().strftime("%Y%m%d")
    save_dir = os.path.join(base_dir, day_dir)
    os.makedirs(save_dir, exist_ok=True)

    ts = datetime.now().strftime("%H%M%S%f")
    if frame_index:
        filename = f"{vin}_{client_session_id}_{frame_index}_{ts}.jpg"
    else:
        filename = f"{vin}_{client_session_id}_{ts}.jpg"
    abs_path = os.path.join(save_dir, filename)
    with open(abs_path, "wb") as f:
        f.write(data)

    rel_path = os.path.relpath(abs_path, base_dir)
    return abs_path, rel_path


def _validate_image(image_storage) -> tuple[bytes | None, str | None]:
    """校验上传图片（大小、mime、解码）。返回 (data_bytes, error_msg)。"""
    if image_storage is None:
        return None, "image missing"

    max_bytes = int(current_app.config.get("MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
    allowed_ext = set(current_app.config.get("ALLOWED_IMAGE_EXT", {".jpg", ".jpeg", ".png"}))
    allowed_mimes = set(current_app.config.get("ALLOWED_IMAGE_MIME", {"image/jpeg", "image/png"}))

    filename = (image_storage.filename or "").strip()
    ext = os.path.splitext(filename)[1].lower()
    if ext and ext not in allowed_ext:
        return None, "image type not allowed"

    mimetype = (image_storage.mimetype or "").lower()
    if mimetype and mimetype not in allowed_mimes:
        return None, "image mimetype not allowed"

    data = image_storage.read()
    if not data:
        return None, "empty image"
    if len(data) > max_bytes:
        return None, "image too large"

    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None, "image decode failed"

    max_pixels = int(current_app.config.get("MAX_IMAGE_PIXELS", 20_000_000))
    max_w = int(current_app.config.get("MAX_IMAGE_WIDTH", 8000))
    max_h = int(current_app.config.get("MAX_IMAGE_HEIGHT", 8000))
    h, w = img.shape[:2]
    if w <= 0 or h <= 0:
        return None, "invalid image size"
    if w > max_w or h > max_h or (w * h) > max_pixels:
        return None, "image resolution too large"

    return data, None


def _run_color_calibration(detected_cfg: dict, standard_cfg: dict, abs_path: str) -> None:
    """对已识别成功的 feature 做在线颜色校准（标准 label 作为真值）。"""
    if not current_app.config.get("COLOR_CALIBRATION_ENABLED", True):
        return
    try:
        std_features = (standard_cfg.get("features") or {})
        detected_features = (detected_cfg.get("features") or {})
        img_bgr = cv2.imread(abs_path)
        if img_bgr is None:
            return

        for feature, std_label in std_features.items():
            if std_label not in ("panel_black", "panel_grey", "panel_yellow"):
                # 暂只对门板类颜色做校准；后续其他 feature 的 label 可按需扩展
                continue
            det = detected_features.get(feature) or {}
            bbox = det.get("bbox")
            label = det.get("label")
            # 仅当推理命中且 label 与标准一致时，更新原型
            if label != std_label or not bbox:
                continue
            x1, y1, x2, y2 = map(int, bbox)
            roi = img_bgr[y1:y2, x1:x2]
            if roi is None or roi.size == 0:
                continue
            update_prototype_from_roi(feature, std_label, roi)
    except Exception:
        # 校准失败不影响主流程
        pass


# =========================
# 端点
# =========================
@api_v2_bp.get("/health")
def health():
    return jsonify(ok({"status": "up", "version": "v2"}))


@api_v2_bp.post("/session/start")
def session_start():
    """开启检测会话。

    Body: { "vin": "...", "client_session_id": "..." }
    """
    payload = request.get_json(silent=True) or {}
    vin = (payload.get("vin") or request.form.get("vin") or "").strip()
    client_session_id = (payload.get("client_session_id") or request.form.get("client_session_id") or "").strip()

    if not vin:
        return jsonify(fail("vin missing", 400)), 400
    if not client_session_id:
        client_session_id = uuid.uuid4().hex

    # 幂等：已存在则直接返回
    existed = find_session_by_vin_client(vin=vin, client_session_id=client_session_id)
    if existed:
        body = existed.to_payload()
        body["idempotent_hit"] = True
        return jsonify(ok(body))

    # 取标准配置
    standard_cfg = get_standard_config(vin)

    create_session(
        vin=vin,
        client_session_id=client_session_id,
        standard=standard_cfg,
    )

    if not commit_or_rollback():
        # 并发冲突 → 重新查询返回
        existed = find_session_by_vin_client(vin=vin, client_session_id=client_session_id)
        if existed:
            body = existed.to_payload()
            body["idempotent_hit"] = True
            return jsonify(ok(body))
        return jsonify(fail("session create failed", 500)), 500

    # 重新查一次拿到 id
    sess = find_session_by_vin_client(vin=vin, client_session_id=client_session_id)
    body = sess.to_payload()
    body["idempotent_hit"] = False
    return jsonify(ok(body))


@api_v2_bp.post("/session/<int:session_id>/frame")
def session_frame(session_id: int):
    """上传单帧图片并实时识别。

    multipart:
        image         图片文件（必填）
        frame_index   帧序号（可选；缺省时使用当前最大索引+1）
    """
    sess = find_session_by_id(session_id)
    if sess is None:
        return jsonify(fail("session not found", 404)), 404
    if sess.status != "RUNNING":
        return jsonify(fail(f"session status is {sess.status}, cannot upload", 409)), 409

    image = request.files.get("image")
    data, err = _validate_image(image)
    if err:
        return jsonify(fail(err, 400)), 400

    # 帧序号
    try:
        frame_index = int(request.form.get("frame_index", -1))
    except ValueError:
        frame_index = -1
    if frame_index < 0:
        existing = list_frames(session_id)
        frame_index = (max((f.frame_index for f in existing), default=-1)) + 1

    # 帧幂等：同 session_id+frame_index 已存在 → 直接返回
    if find_frame(session_id, frame_index) is not None:
        existed_frame = find_frame(session_id, frame_index)
        return jsonify(ok({
            "session_id": session_id,
            "frame_index": frame_index,
            "frame_id": existed_frame.id,
            "idempotent_hit": True,
            "detected": existed_frame.to_payload()["detected"],
        }))

    # 保存图片（写盘 + 推理均可能耗时，先写盘再推理）
    # 重新写入（_validate_image 已 read 过指针；这里直接保存原文件）
    image.stream.seek(0)
    abs_path, rel_path = _save_image(image, vin=sess.vin, client_session_id=sess.client_session_id, frame_index=frame_index)

    # 单帧推理
    detected_cfg = infer_frame(abs_path)

    # 写帧记录
    create_frame(
        session_id=session_id,
        frame_index=frame_index,
        image_path=rel_path,
        detected=detected_cfg,
    )
    increment_frame_count(session_id)

    if not commit_or_rollback():
        # 并发冲突（同 index 重复提交）
        existed_frame = find_frame(session_id, frame_index)
        if existed_frame:
            try:
                os.remove(abs_path)
            except OSError:
                pass
            return jsonify(ok({
                "session_id": session_id,
                "frame_index": frame_index,
                "frame_id": existed_frame.id,
                "idempotent_hit": True,
                "detected": existed_frame.to_payload()["detected"],
            }))
        raise

    # 在线校准（用标准 label 作为真值）
    standard_cfg_json = _safe_load_json(sess.standard_json, {})
    _run_color_calibration(detected_cfg, standard_cfg_json, abs_path)

    return jsonify(ok({
        "session_id": session_id,
        "frame_index": frame_index,
        "image_path": rel_path,
        "detected": detected_cfg,
        "idempotent_hit": False,
    }))


@api_v2_bp.post("/session/<int:session_id>/finish")
def session_finish(session_id: int):
    """结束会话：聚合 → 比对 → 落库。"""
    sess = find_session_by_id(session_id)
    if sess is None:
        return jsonify(fail("session not found", 404)), 404
    if sess.status == "FINISHED":
        # 已结束 → 直接返回历史结果（幂等）
        return jsonify(ok(sess.to_payload(include_frames=False) | {"idempotent_hit": True}))

    frames = list_frames(session_id)
    detected_per_frame = []
    for f in frames:
        det = _safe_load_json(f.detected_json, {})
        detected_per_frame.append(det)

    # 聚合
    standard_cfg = _safe_load_json(sess.standard_json, {})
    feature_order = list((standard_cfg.get("features") or {}).keys())
    aggregated = aggregate_frames(detected_per_frame, feature_order=feature_order)

    # 把聚合后的 features 拍平为 {feature: label} 给 compare_service
    flat_detected = {
        fname: finfo.get("label") for fname, finfo in (aggregated.get("features") or {}).items()
    }
    compare_info = compare_configs(standard_cfg, flat_detected)
    overall = compare_info.get("overall", "UNKNOWN")

    finalize_session(
        session_id,
        aggregated=aggregated,
        compare_info=compare_info,
        overall=overall,
        status="FINISHED",
    )

    if not commit_or_rollback():
        return jsonify(fail("session finalize failed", 500)), 500

    return jsonify(ok({
        "session_id": session_id,
        "overall": overall,
        "aggregated": aggregated,
        "compare_result": compare_info.get("compare_result", {}),
        "frame_count": sess.frame_count,
    }))


@api_v2_bp.get("/session/<int:session_id>")
def session_get(session_id: int):
    """查询会话详情（含所有帧），用于调试/历史查询。"""
    sess = find_session_by_id(session_id)
    if sess is None:
        return jsonify(fail("session not found", 404)), 404
    return jsonify(ok(sess.to_payload(include_frames=True)))


def _safe_load_json(s: str | None, default):
    import json
    if not s:
        return default
    try:
        return json.loads(s)
    except Exception:
        return default