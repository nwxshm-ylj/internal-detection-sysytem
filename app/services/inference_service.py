from __future__ import annotations

import os
from typing import Any, Dict, Tuple, Optional

import cv2
import numpy as np
from flask import current_app
from ultralytics import YOLO

from app.repositories.color_prototype_repo import get_prototypes


# 冷启动默认原型（DB 没校准时使用）
DEFAULT_COLOR_PROTOTYPES = {
    "door_trim_color": {
        "panel_black":  (20.0, 128.0, 128.0),
        "panel_grey":   (55.0, 128.0, 128.0),
        "panel_yellow": (70.0, 110.0, 170.0),
    }
}

_MODEL: Optional[YOLO] = None


def _get_model() -> YOLO:
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    model_path = current_app.config.get("YOLO_MODEL_PATH")
    if not model_path:
        raise RuntimeError("YOLO_MODEL_PATH not configured")

    if not os.path.isabs(model_path):
        model_path = os.path.abspath(model_path)

    if not os.path.exists(model_path):
        raise FileNotFoundError(f"YOLO model not found: {model_path}")

    _MODEL = YOLO(model_path)
    return _MODEL


def _center_crop(img_bgr, ratio: float = 0.7):
    h, w = img_bgr.shape[:2]
    ch, cw = int(h * ratio), int(w * ratio)
    y1 = max((h - ch) // 2, 0)
    x1 = max((w - cw) // 2, 0)
    return img_bgr[y1:y1 + ch, x1:x1 + cw]


def _lab_median(img_bgr) -> Tuple[float, float, float]:
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    flat = lab.reshape(-1, 3)

    # 过滤反光/阴影像素
    L = flat[:, 0]
    mask = (L > 20) & (L < 235)
    if mask.sum() > 50:
        flat = flat[mask]

    m = np.median(flat, axis=0).astype(float)
    return float(m[0]), float(m[1]), float(m[2])


def _dist(lab1: Tuple[float, float, float], lab2: Tuple[float, float, float]) -> float:
    return float(np.linalg.norm(np.array(lab1) - np.array(lab2)))


def _get_color_prototypes(feature: str) -> Dict[str, Tuple[float, float, float]]:
    # 优先 DB 在线原型
    db_protos = get_prototypes(feature)
    if db_protos:
        return db_protos
    return DEFAULT_COLOR_PROTOTYPES.get(feature, {})


def _classify_color(feature: str, roi_bgr) -> Tuple[Optional[str], Dict[str, Any]]:
    protos = _get_color_prototypes(feature)
    if not protos:
        return None, {"reason": "no_prototypes"}

    roi2 = _center_crop(roi_bgr, ratio=0.7)
    lab = _lab_median(roi2)

    dists = {label: _dist(lab, proto) for label, proto in protos.items()}
    best_label = min(dists, key=dists.get)
    best_dist = float(dists[best_label])

    threshold = float(current_app.config.get("COLOR_DIST_THRESHOLD", 25.0))
    if best_dist > threshold:
        # 不确定：返回 None，避免误判
        return None, {
            "lab_median": lab,
            "distances": dists,
            "selected": best_label,
            "selected_dist": best_dist,
            "threshold": threshold,
            "reason": "dist_too_large",
        }

    return best_label, {
        "lab_median": lab,
        "distances": dists,
        "selected": best_label,
        "selected_dist": best_dist,
        "threshold": threshold,
        "reason": None,
    }


def infer_detected_config(image_path: str) -> Dict[str, Any]:
    """
    只做 door_trim_color 三分类：
      panel_black / panel_grey / panel_yellow / None

    YOLO 类名：panel_color（你已确认）
    """
    mode = (current_app.config.get("INFERENCE_MODE") or "mock").lower()

    if mode == "mock":
        return {"door_trim_color": None, "_meta": {"mode": "mock"}}

    if mode in ("local", "yolov8"):
        pass
    else:
        raise RuntimeError(f"Unknown INFERENCE_MODE={mode} (supported: yolov8/local, mock)")

    img = cv2.imread(image_path)
    if img is None:
        return {"door_trim_color": None, "_meta": {"error": "imread_failed"}}

    model = _get_model()
    imgsz = int(current_app.config.get("YOLO_IMG_SIZE", 640))
    conf = float(current_app.config.get("YOLO_CONF", 0.25))

    results = model.predict(source=image_path, imgsz=imgsz, conf=conf, verbose=False)
    if not results:
        return {"door_trim_color": None, "_meta": {"error": "no_results"}}

    r0 = results[0]
    names = r0.names
    panel_names = set(current_app.config.get("YOLO_PANEL_CLASSNAMES", ["panel_color"]))

    best = None  # (score, xyxy, cls_name)
    if r0.boxes is not None and len(r0.boxes) > 0:
        for b in r0.boxes:
            cls_id = int(b.cls[0])
            cls_name = str(names.get(cls_id, cls_id))
            if cls_name not in panel_names:
                continue

            score = float(b.conf[0])
            xyxy = [float(x) for x in b.xyxy[0].tolist()]
            if best is None or score > best[0]:
                best = (score, xyxy, cls_name)

    if best is None:
        return {"door_trim_color": None, "_meta": {"yolo": {"hit": False, "panel_names": list(panel_names)}}}

    score, xyxy, cls_name = best
    x1, y1, x2, y2 = map(int, xyxy)
    h, w = img.shape[:2]
    x1, y1 = max(x1, 0), max(y1, 0)
    x2, y2 = min(x2, w), min(y2, h)

    roi = img[y1:y2, x1:x2]
    if roi is None or roi.size == 0:
        return {
            "door_trim_color": None,
            "_meta": {"yolo": {"hit": True, "bbox": [x1, y1, x2, y2], "conf": score}, "error": "roi_empty"},
        }

    label, meta = _classify_color("door_trim_color", roi)

    return {
        "door_trim_color": label,
        "_meta": {
            "mode": "yolov8+lab",
            "door_trim_color": {
                "yolo_class": cls_name,
                "conf": score,
                "bbox": [x1, y1, x2, y2],
                **meta,
            },
        },
    }
