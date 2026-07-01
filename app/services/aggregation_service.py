"""Aggregation Service: 多帧检测结果 → 每零件最终判定。

策略：置信度加权投票 + 一致性检查。

逻辑：
1. 遍历所有帧的识别结果
2. 对每个 feature，收集所有帧对该 feature 的 (label, conf) 命中
3. 计算每个 label 的"总权重"（累加 conf），取权重最高的 label 作为最终结果
4. 若某 feature 在所有帧中都没命中 → 记为 None（UNKNOWN）

示例：
  feature = door_trim_color
  frames = [
    {"label": "panel_black", "conf": 0.9},
    {"label": "panel_black", "conf": 0.8},
    {"label": "panel_grey", "conf": 0.6},  # 离群
  ]
  → 加权：black = 1.7, grey = 0.6 → 选 panel_black
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _aggregate_feature(feature: str, hits: List[Tuple[Optional[str], float]]) -> Dict[str, Any]:
    """
    对单个 feature 的所有帧命中做加权投票。

    Args:
        feature: feature 名
        hits: [(label, conf), ...] 每帧的识别结果

    Returns:
        {
          "label": "panel_black" | None,
          "confidence": 0.85,
          "frame_count": 3,
          "label_votes": {"panel_black": 1.7, "panel_grey": 0.6},
          "unanimous": False,    # 投票是否一致
          "inlier_ratio": 0.67,  # 与最终结果一致的帧占比
        }
    """
    if not hits:
        return {
            "label": None,
            "confidence": 0.0,
            "frame_count": 0,
            "label_votes": {},
            "unanimous": False,
            "inlier_ratio": 0.0,
        }

    label_votes: Dict[str, float] = {}
    for label, conf in hits:
        if label is None:
            # 漏识别帧不计票（但计入 frame_count）
            continue
        label_votes[label] = label_votes.get(label, 0.0) + float(conf)

    if not label_votes:
        return {
            "label": None,
            "confidence": 0.0,
            "frame_count": len(hits),
            "label_votes": {},
            "unanimous": False,
            "inlier_ratio": 0.0,
        }

    # 选票最高的 label
    best_label = max(label_votes, key=lambda k: label_votes[k])  # type: ignore[arg-type]
    total_votes = sum(label_votes.values())
    best_conf = label_votes[best_label] / max(len([h for h in hits if h[0] is not None]), 1)

    # 计算 inlier_ratio：命中 = best_label 的帧数 / 总命中帧数
    matched_frames = [h for h in hits if h[0] is not None]
    inlier_count = sum(1 for h in matched_frames if h[0] == best_label)
    inlier_ratio = inlier_count / len(matched_frames) if matched_frames else 0.0

    return {
        "label": best_label,
        "confidence": round(best_conf, 4),
        "frame_count": len(hits),
        "label_votes": {k: round(v, 4) for k, v in label_votes.items()},
        "unanimous": len(label_votes) == 1,
        "inlier_ratio": round(inlier_ratio, 4),
    }


def aggregate_frames(frames: List[Dict[str, Any]], feature_order: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    多帧检测结果 → 每 feature 的最终判定。

    Args:
        frames: list of frame detected dict，每项格式:
            {
                "features": {
                    "door_trim_color": {"label": ..., "conf": ..., ...},
                    ...
                },
                "_meta": {...}
            }
        feature_order: 可选，按指定顺序返回 feature；默认自动从 frames 抽取

    Returns:
        {
            "features": {
                "door_trim_color": {
                    "label": "panel_black",
                    "confidence": 0.85,
                    "frame_count": 5,
                    "label_votes": {"panel_black": 2.5, "panel_grey": 0.6},
                    "unanimous": False,
                    "inlier_ratio": 0.83,
                },
                ...
            },
            "_meta": {
                "frame_count": 5,
                "strategy": "confidence_weighted_voting",
            }
        }
    """
    if not frames:
        return {
            "features": {},
            "_meta": {
                "frame_count": 0,
                "strategy": "confidence_weighted_voting",
            },
        }

    # 抽取所有 feature 名（保持传入顺序）
    if feature_order is None:
        seen: List[str] = []
        for f in frames:
            for fname in (f.get("features") or {}).keys():
                if fname not in seen:
                    seen.append(fname)
        feature_order = seen

    # 收集每个 feature 的命中
    feature_hits: Dict[str, List[Tuple[Optional[str], float]]] = {f: [] for f in feature_order}
    for frame in frames:
        feats = frame.get("features") or {}
        for f_name in feature_order:
            f_info = feats.get(f_name)
            if f_info is None:
                feature_hits[f_name].append((None, 0.0))
            else:
                label = f_info.get("label")
                conf = float(f_info.get("conf") or 0.0)
                feature_hits[f_name].append((label, conf))

    aggregated = {f: _aggregate_feature(f, hits) for f, hits in feature_hits.items()}

    return {
        "features": aggregated,
        "_meta": {
            "frame_count": len(frames),
            "strategy": "confidence_weighted_voting",
        },
    }