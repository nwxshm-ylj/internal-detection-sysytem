from __future__ import annotations

import os
from datetime import datetime
from uuid import uuid4

import cv2
import numpy as np
from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.repositories.inspection_repo import find_by_vin_event, save_record
from app.services.compare_service import compare_configs
from app.services.inference_service import infer_detected_config
from app.services.standard_service import get_standard_config
from app.services.color_calibration_service import update_prototype_from_roi
from app.utils.response_utils import fail, ok

api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")


@api_v1_bp.get("/health")
def health():
    return jsonify(ok({"status": "up"}))


@api_v1_bp.post("/inspection")
def inspection():
    vin = (request.form.get("vin") or "").strip()
    client_event_id = (request.form.get("client_event_id") or "").strip()
    image = request.files.get("image")

    if not vin:
        return jsonify(fail("vin missing", 400)), 400
    if not image:
        return jsonify(fail("image missing", 400)), 400

    # Basic upload validation
    max_bytes = int(current_app.config.get("MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
    allowed_mimes = set(current_app.config.get("ALLOWED_IMAGE_MIME", {"image/jpeg", "image/png"}))
    allowed_ext = set(current_app.config.get("ALLOWED_IMAGE_EXT", {".jpg", ".jpeg", ".png"}))

    if request.content_length and request.content_length > max_bytes:
        return jsonify(fail("image too large", 413)), 413

    filename = (image.filename or "").strip()
    ext = os.path.splitext(filename)[1].lower()
    if ext and ext not in allowed_ext:
        return jsonify(fail("image type not allowed", 400)), 400

    mimetype = (image.mimetype or "").lower()
    if mimetype and mimetype not in allowed_mimes:
        return jsonify(fail("image mimetype not allowed", 400)), 400

    data = image.read()
    if not data:
        return jsonify(fail("empty image", 400)), 400
    if len(data) > max_bytes:
        return jsonify(fail("image too large", 413)), 413

    img_preview = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img_preview is None:
        return jsonify(fail("image decode failed", 400)), 400
    h, w = img_preview.shape[:2]
    max_pixels = int(current_app.config.get("MAX_IMAGE_PIXELS", 20_000_000))
    max_w = int(current_app.config.get("MAX_IMAGE_WIDTH", 8000))
    max_h = int(current_app.config.get("MAX_IMAGE_HEIGHT", 8000))
    if w <= 0 or h <= 0:
        return jsonify(fail("invalid image size", 400)), 400
    if w > max_w or h > max_h or (w * h) > max_pixels:
        return jsonify(fail("image resolution too large", 413)), 413

    # 前端未接入时兜底；上线建议强制前端提供
    if not client_event_id:
        client_event_id = str(uuid4())

    # 幂等命中：VIN + event 已存在则直接返回
    existed = find_by_vin_event(vin=vin, client_event_id=client_event_id)
    if existed:
        payload = existed.to_payload()
        payload["idempotent_hit"] = True
        return jsonify(ok(payload))

    # 1) 保存图片
    base_dir = current_app.config["UPLOAD_DIR"]
    day_dir = datetime.now().strftime("%Y%m%d")
    save_dir = os.path.join(base_dir, day_dir)
    os.makedirs(save_dir, exist_ok=True)

    ts = datetime.now().strftime("%H%M%S%f")
    filename = f"{vin}_{client_event_id}_{ts}.jpg"
    abs_path = os.path.join(save_dir, filename)
    with open(abs_path, "wb") as f:
        f.write(data)
    rel_path = os.path.relpath(abs_path, base_dir)

    # 2) 标准配置（LES or mock）
    standard_cfg = get_standard_config(vin)

    # 3) 推理（只做 door_trim_color）
    detected_cfg = infer_detected_config(abs_path)

    # 4) 比对
    compare_info = compare_configs(standard_cfg, detected_cfg)

    # 5) 落库（并发/重试用唯一约束兜底）
    try:
        record_id = save_record(
            vin=vin,
            client_event_id=client_event_id,
            image_path=rel_path,
            standard=standard_cfg,
            detected=detected_cfg,
            compare_info=compare_info,
        )
    except IntegrityError:
        db.session.rollback()
        existed = find_by_vin_event(vin=vin, client_event_id=client_event_id)
        if existed:
            # 并发冲突下清理孤儿文件
            try:
                os.remove(abs_path)
            except OSError:
                pass

            payload = existed.to_payload()
            payload["idempotent_hit"] = True
            return jsonify(ok(payload))
        raise

    # ===== 在线校准：用标准配置（真值）更新 prototype（越用越准）=====
    try:
        if current_app.config.get("COLOR_CALIBRATION_ENABLED", True):
            std_label = (standard_cfg.get("features") or {}).get("door_trim_color")
            meta = (detected_cfg.get("_meta") or {}).get("door_trim_color") or {}
            bbox = meta.get("bbox")

            if std_label in ("panel_black", "panel_grey", "panel_yellow") and bbox:
                img_bgr = cv2.imread(abs_path)
                if img_bgr is not None:
                    x1, y1, x2, y2 = map(int, bbox)
                    roi = img_bgr[y1:y2, x1:x2]
                    if roi is not None and roi.size > 0:
                        update_prototype_from_roi("door_trim_color", std_label, roi)
    except Exception:
        # 校准失败不影响主流程
        pass

    payload = {
        "record_id": record_id,
        "vin": vin,
        "client_event_id": client_event_id,
        "image_path": rel_path,
        "standard": standard_cfg,
        "detected": detected_cfg,
        "compare_result": compare_info.get("compare_result") or compare_info.get("compare_detail"),
        "overall": compare_info.get("overall"),
        "idempotent_hit": False,
    }
    return jsonify(ok(payload))
