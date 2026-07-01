"""
实现标准配置与推理结果的逐项比对逻辑。
"""

from __future__ import annotations

from app.domain.feature_registry import FEATURE_REGISTRY, FeatureSpec


def compare_configs(standard_cfg: dict, detected_cfg: dict) -> dict:
    """返回逐项比对结果及 overall 结论。"""
    standard_features = standard_cfg.get("features", {}) or {}
    detected_features = detected_cfg or {}

    compare_result = {}
    overall = "OK"

    for feature, std_val in standard_features.items():
        spec: FeatureSpec = FEATURE_REGISTRY.get(
            feature,
            FeatureSpec(name=feature, allowed=None, mandatory=False),
        )

        det_val = detected_features.get(feature)

        item = {
            "standard": std_val,
            "detected": det_val,
            "result": None,
            "reason": None,
            "mandatory": spec.mandatory,
        }

        # 1. 标准缺失
        if std_val is None:
            item["result"] = "UNKNOWN"
            item["reason"] = "standard_missing"
            compare_result[feature] = item
            continue

        # 2. 推理缺失
        if det_val is None:
            if spec.mandatory:
                item["result"] = "NG"
                item["reason"] = "detected_missing"
                overall = "NG"
            else:
                item["result"] = "UNKNOWN"
                item["reason"] = "detected_missing"
            compare_result[feature] = item
            continue

        # 3. 枚举合法性校验（防止推理引擎输出非法值）
        if spec.allowed and det_val not in spec.allowed:
            item["result"] = "NG"
            item["reason"] = f"detected_not_allowed:{det_val}"
            if spec.mandatory:
                overall = "NG"
            compare_result[feature] = item
            continue

        # 4. 正常比对
        if std_val == det_val:
            item["result"] = "OK"
        else:
            item["result"] = "NG"
            item["reason"] = "value_mismatch"
            if spec.mandatory:
                overall = "NG"

        compare_result[feature] = item

    if not compare_result:
        overall = "UNKNOWN"

    return {
        "compare_result": compare_result,
        "overall": overall,
    }
