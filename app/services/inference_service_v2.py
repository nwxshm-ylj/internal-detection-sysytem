"""V2 Inference Service: 单帧 → 多零件多颜色识别。

与 v1 的区别：
- v1 只检测 door_trim_color 一个特征
- v2 支持多个零件类别（由 YOLO_FEATURE_CLASS_MAP 配置驱动）
- 返回 {feature: {label, conf, bbox, lab_meta}} 结构

YOLO 模型类别 → 业务 feature 的映射关系由配置 YOLO_FEATURE_CLASS_MAP 决定。
当 YOLO 模型仅训练了 panel_color 时，自然只返回 door_trim_color 一项。
等模型重训加了新类别后，只需更新配置即可支持更多零件。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from flask import current_app
from ultralytics import YOLO

from app.repositories.color_prototype_repo import get_prototypes


# 冷启动默认原型（DB 没校准时使用）
DEFAULT_COLOR_PROTOTYPES: Dict[str, Dict[str, Tuple[float, float, float]]] = {
    "door_trim_color": {
        "panel_black": (20.0, 128.0, 128.0),
        "panel_grey": (55.0, 128.0, 128.0),
        "panel_yellow": (70.0, 110.0, 170.0),
    },
    # 后续新增零件在这里添加默认原型
    # "seat_color": { ... },
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
    """优先从 DB 取在线校准原型，fallback 到默认硬编码。"""
    db_protos = get_prototypes(feature)
    if db_protos:
        return db_protos
    return DEFAULT_COLOR_PROTOTYPES.get(feature, {})


def _classify_color(feature: str, roi_bgr) -> Tuple[Optional[str], Dict[str, Any]]:
    """对 ROI 做 Lab 颜色分类，返回 (label, meta)。"""
    protos = _get_color_prototypes(feature)
    if not protos:
        return None, {"reason": "no_prototypes"}

    roi2 = _center_crop(roi_bgr, ratio=0.7)
    lab = _lab_median(roi2)

    dists = {label: _dist(lab, proto) for label, proto in protos.items()}
    best_label = min(dists, key=dists.get)  # type: ignore[arg-type]
    best_dist = float(dists[best_label])

    threshold = float(current_app.config.get("COLOR_DIST_THRESHOLD", 25.0))
    if best_dist > threshold:
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


def _get_feature_class_map() -> Dict[str, List[str]]:
    """
    获取 feature → YOLO 类名列表的映射。
    配置格式:
        YOLO_FEATURE_CLASS_MAP = {
            "door_trim_color": ["panel_color"],
            "seat_color": ["seat"],
            ...
        }
    """
    return current_app.config.get("YOLO_FEATURE_CLASS_MAP", {
        "door_trim_color": ["panel_color"],
    })


def _invert_class_map(feature_class_map: Dict[str, List[str]]) -> Dict[str, str]:
    """反转映射：YOLO 类名 → feature。"""
    inv: Dict[str, str] = {}
    for feature, class_names in feature_class_map.items():
        for cls in class_names:
            inv[cls] = feature
    return inv


def infer_frame(image_path: str) -> Dict[str, Any]:
    """
    V2 核心推理入口：单帧 → 多零件检测。

    返回格式：
    {
        "features": {
            "door_trim_color": {
                "label": "panel_black" | None,
                "conf": 0.87,
                "bbox": [x1, y1, x2, y2],
                "lab_meta": {...}
            },
            "seat_color": { ... },
            ...
        },
        "_meta": {
            "mode": "yolov8+lab",
            "yolo_detections": 3,   # YOLO 检测到的总框数
            "matched_features": 1,  # 匹配到业务 feature 的框数
        }
    }
    """
    mode = (current_app.config.get("INFERENCE_MODE") or "mock").lower()

    feature_class_map = _get_feature_class_map()

    if mode == "mock":
        # Mock 模式：所有 feature 返回 None
        features = {f: {"label": None, "conf": 0.0, "bbox": None, "lab_meta": {}} for f in feature_class_map}
        return {"features": features, "_meta": {"mode": "mock"}}

    if mode not in ("local", "yolov8"):
        raise RuntimeError(f"Unknown INFERENCE_MODE={mode} (supported: yolov8/local, mock)")

    img = cv2.imread(image_path)
    if img is None:
        features = {f: {"label": None, "conf": 0.0, "bbox": None, "lab_meta": {"error": "imread_failed"}} for f in feature_class_map}
        return {"features": features, "_meta": {"error": "imread_failed"}}

    model = _get_model()
    imgsz = int(current_app.config.get("YOLO_IMG_SIZE", 640))
    conf = float(current_app.config.get("YOLO_CONF", 0.25))

    results = model.predict(source=image_path, imgsz=imgsz, conf=conf, verbose=False)
    if not results:
        features = {f: {"label": None, "conf": 0.0, "bbox": None, "lab_meta": {"error": "no_results"}} for f in feature_class_map}
        return {"features": features, "_meta": {"error": "no_results"}}

    r0 = results[0]
    names = r0.names
    cls_to_feature = _invert_class_map(feature_class_map)

    # 每个 feature 取置信度最高的检测框
    best_per_feature: Dict[str, Tuple[float, List[float], str]] = {}  # feature -> (conf, xyxy, cls_name)

    total_detections = 0
    if r0.boxes is not None and len(r0.boxes) > 0:
        total_detections = len(r0.boxes)
        for b in r0.boxes:
            cls_id = int(b.cls[0])
            cls_name = str(names.get(cls_id, cls_id))

            feature = cls_to_feature.get(cls_name)
            if feature is None:
                continue

            score = float(b.conf[0])
            xyxy = [float(x) for x in b.xyxy[0].tolist()]

            if feature not in best_per_feature or score > best_per_feature[feature][0]:
                best_per_feature[feature] = (score, xyxy, cls_name)

    # 对每个 feature 做颜色分类
    h, w = img.shape[:2]
    features: Dict[str, Dict[str, Any]] = {}

    for feature in feature_class_map:
        if feature not in best_per_feature:
            features[feature] = {
                "label": None,
                "conf": 0.0,
                "bbox": None,
                "lab_meta": {"reason": "not_detected"},
            }
            continue

        score, xyxy, cls_name = best_per_feature[feature]
        x1, y1, x2, y2 = map(int, xyxy)
        x1, y1 = max(x1, 0), max(y1, 0)
        x2, y2 = min(x2, w), min(y2, h)

        roi = img[y1:y2, x1:x2]
        if roi is None or roi.size == 0:
            features[feature] = {
                "label": None,
                "conf": score,
                "bbox": [x1, y1, x2, y2],
                "lab_meta": {"error": "roi_empty"},
            }
            continue

        label, lab_meta = _classify_color(feature, roi)
        features[feature] = {
            "label": label,
            "conf": score,
            "bbox": [x1, y1, x2, y2],
            "yolo_class": cls_name,
            "lab_meta": lab_meta,
        }

    return {
        "features": features,
        "_meta": {
            "mode": "yolov8+lab",
            "yolo_detections": total_detections,
            "matched_features": len(best_per_feature),
        },
    }