"""Parse PR codes and map them to human readable features.

负责解析 PR 码集合，并映射成业务可读的特征值。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

import yaml
from flask import current_app

# ===== 全局缓存（由 load_pr_rules 在应用启动时填充）=====
PR_FEATURE_RULES: Dict[str, Dict] = {}
PR_RULES_VERSION: Optional[str] = None


def load_pr_rules() -> None:
    """启动阶段读取 YAML 规则，加载到内存以提升请求性能。"""
    global PR_FEATURE_RULES, PR_RULES_VERSION

    rules_path = current_app.config.get("PR_RULES_PATH")
    if not rules_path:
        raise RuntimeError("PR_RULES_PATH not configured")
    if not os.path.exists(rules_path):
        raise FileNotFoundError(f"PR rules file not found: {rules_path}")

    with open(rules_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    version = data.get("version")
    if not version:
        raise RuntimeError("PR rules missing 'version'")

    PR_RULES_VERSION = str(version)
    # drop the version key, keep the feature specific rules
    PR_FEATURE_RULES = {k: v for k, v in data.items() if k != "version"}


def get_pr_rules_version() -> Optional[str]:
    """对外暴露规则版本号，便于前端排查配置差异。"""
    return PR_RULES_VERSION


# =========================
# 映射引擎
# =========================
@dataclass(frozen=True)
class GroupCodeRule:
    """描述 group+code 的命中条件。"""

    group: str
    codes: Set[str]


@dataclass
class CandidateRule:
    """单个候选取值的匹配规则。"""

    value: str
    exact_items: Set[str]
    group_code_rules: List[GroupCodeRule]
    priority: int


def _normalize_group_code_rules(raw: List[dict]) -> List[GroupCodeRule]:
    """将 YAML 中的 group_codes 配置转换为数据类便于处理。"""
    rules: List[GroupCodeRule] = []
    for r in raw or []:
        group = (r.get("group") or "").strip()
        codes = {
            (c or "").strip()
            for c in (r.get("codes") or [])
            if (c or "").strip()
        }
        if group and codes:
            rules.append(GroupCodeRule(group=group, codes=codes))
    return rules


def _load_feature_candidates(feature_conf: dict) -> List[CandidateRule]:
    """构建候选规则列表，并按 priority 倒序排列。"""
    candidates: List[CandidateRule] = []
    for c in feature_conf.get("candidates", []) or []:
        value = c.get("value")
        if not value:
            continue

        exact_items = {
            (x or "").strip()
            for x in (c.get("exact_items") or [])
            if (x or "").strip()
        }
        group_code_rules = _normalize_group_code_rules(c.get("group_codes") or [])
        priority = int(c.get("priority", 0))

        candidates.append(
            CandidateRule(
                value=value,
                exact_items=exact_items,
                group_code_rules=group_code_rules,
                priority=priority,
            )
        )

    candidates.sort(key=lambda x: x.priority, reverse=True)
    return candidates


def _candidate_match(
    cand: CandidateRule,
    item_set: Set[str],
    group_index: Dict[str, Set[str]],
) -> bool:
    """判断候选规则是否命中（exact_items / group_codes 二选一满足即可）。"""
    if cand.exact_items and (cand.exact_items & item_set):
        return True

    for r in cand.group_code_rules:
        codes = group_index.get(r.group)
        if not codes:
            continue
        if codes & r.codes:
            return True

    return False


def map_pr_to_features(
    item_set: Set[str],
    group_index: Dict[str, Set[str]],
    *,
    strict_conflict: bool = False,
) -> Tuple[Dict[str, Optional[str]], Dict]:
    """
    将 PR 组合映射为特征输出。

    Returns:
        features: {feature: value}
        debug:    {feature: {...}} with selection details
    """
    if not PR_FEATURE_RULES:
        raise RuntimeError("PR rules not loaded. Call load_pr_rules() in create_app().")

    features: Dict[str, Optional[str]] = {}
    debug: Dict[str, Dict] = {}

    for feature, conf in PR_FEATURE_RULES.items():
        default = conf.get("default")
        candidates = _load_feature_candidates(conf)

        matched: List[str] = []
        selected: Optional[str] = None

        for cand in candidates:
            if _candidate_match(cand, item_set, group_index):
                matched.append(cand.value)
                if selected is None:
                    selected = cand.value  # priority 越大越先命中
        conflict = len(matched) > 1
        if conflict and strict_conflict:
            raise RuntimeError(
                f"PR mapping conflict: feature={feature}, matched={matched}"
            )

        features[feature] = selected if selected is not None else default
        debug[feature] = {
            "matched_values": matched,
            "selected": features[feature],
            "conflict": conflict,
        }

    return features, debug
