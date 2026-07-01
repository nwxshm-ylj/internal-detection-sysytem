from __future__ import annotations

from typing import Tuple

import cv2
import numpy as np

from app.repositories.color_prototype_repo import upsert_running_mean


def lab_median(roi_bgr) -> Tuple[float, float, float]:
    """
    ROI Lab 中位数，过滤极端亮暗像素，抗反光。
    """
    lab = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2LAB)
    flat = lab.reshape(-1, 3)

    L = flat[:, 0]
    mask = (L > 20) & (L < 235)
    if mask.sum() > 50:
        flat = flat[mask]

    m = np.median(flat, axis=0).astype(float)
    return float(m[0]), float(m[1]), float(m[2])


def update_prototype_from_roi(feature: str, label: str, roi_bgr) -> Tuple[float, float, float]:
    """
    用标准配置 label 作为真值，对 feature 的 prototype 做在线校准。
    返回该 ROI 的 lab median 便于调试。
    """
    lab = lab_median(roi_bgr)
    upsert_running_mean(feature, label, lab)
    return lab
