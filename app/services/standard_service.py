from __future__ import annotations

from flask import current_app

from app.clients.les_client import fetch_les_by_vin
from app.clients.les_client import fetch_pr_group, extract_pr_group_from_response, PRServiceError
from app.services.pr_mapping import map_pr_to_features, get_pr_rules_version


def parse_pr_group(pr_group: str) -> dict:
    
    if not pr_group:
        return {
            "items": [],
            "pairs": [],
            "group_index": {},
            "item_set": set(),
            "invalid_items": [],
        }

    raw_items = [x.strip() for x in pr_group.split(",")]
    items = [x for x in raw_items if x]

    pairs = []
    invalid_items = []
    group_index = {}

    for it in items:
        if "~" not in it:
            invalid_items.append(it)
            continue

        group, code = it.split("~", 1)
        group = group.strip()
        code = code.strip()

        if not group or not code:
            invalid_items.append(it)
            continue

        pairs.append({"group": group, "code": code})
        group_index.setdefault(group, set()).add(code)

    return {
        "items": items,
        "pairs": pairs,
        "group_index": group_index,
        "item_set": set(items),
        "invalid_items": invalid_items,
    }


def _mock_standard(vin: str) -> dict:
    mock = current_app.config["MOCK_STANDARD"]
    pr_group = mock.get("prGroup", "")
    pr_parsed = parse_pr_group(pr_group)

    features, mapping_debug = map_pr_to_features(
        pr_parsed["item_set"],
        pr_parsed["group_index"],
        strict_conflict=current_app.config.get("PR_STRICT_CONFLICT", False),
    )

    return {
        "source": "mock",
        "vin": vin,
        "model": mock.get("model"),
        "color_code": mock.get("color_code"),
        "interior_code": mock.get("interior_code"),
        "rules_version": get_pr_rules_version(),
        "pr": {
            "raw": pr_group,
            "items": pr_parsed["items"],
            "pairs": pr_parsed["pairs"],
            "invalid_items": pr_parsed["invalid_items"],
            "mapping_debug": mapping_debug,
        },
        "features": features,
    }


def _soap_pr_standard(vin: str) -> dict:
    """
    只通过 PR SOAP 拿 prGroup，然后做 PR→features 映射。
    车型/色号等如果暂时拿不到，可以置空或从 mock 填充。
    """
    data = fetch_pr_group(vin)
    pr_group = extract_pr_group_from_response(data, vin) or ""
    pr_parsed = parse_pr_group(pr_group)

    features, mapping_debug = map_pr_to_features(
        pr_parsed["item_set"],
        pr_parsed["group_index"],
        strict_conflict=current_app.config.get("PR_STRICT_CONFLICT", False),
    )

    # 如果你希望在 dev 阶段把 model/color/interior 也填上，可以从 MOCK_STANDARD 兜底
    mock = current_app.config.get("MOCK_STANDARD", {})

    return {
        "source": "pr_soap",
        "vin": vin,
        "model": mock.get("model"),  # 暂用 mock，后续接 LES 再替换
        "color_code": mock.get("color_code"),
        "interior_code": mock.get("interior_code"),
        "rules_version": get_pr_rules_version(),
        "pr": {
            "raw": pr_group,
            "items": pr_parsed["items"],
            "pairs": pr_parsed["pairs"],
            "invalid_items": pr_parsed["invalid_items"],
            "mapping_debug": mapping_debug,
        },
        "features": features,
    }


def _les_standard(vin: str) -> dict:
    raw = fetch_les_by_vin(vin)

    pr_group = raw.get("prGroup", "")
    pr_parsed = parse_pr_group(pr_group)

    features, mapping_debug = map_pr_to_features(
        pr_parsed["item_set"],
        pr_parsed["group_index"],
        strict_conflict=current_app.config.get("PR_STRICT_CONFLICT", False),
    )

    return {
        "source": "les",
        "vin": raw.get("vin", vin),
        "model": raw.get("model"),
        "color_code": raw.get("farbau"),
        "interior_code": raw.get("farbin"),
        "rules_version": get_pr_rules_version(),
        "pr": {
            "raw": pr_group,
            "items": pr_parsed["items"],
            "pairs": pr_parsed["pairs"],
            "invalid_items": pr_parsed["invalid_items"],
            "mapping_debug": mapping_debug,
        },
        "features": features,
    }


def get_standard_config(vin: str) -> dict:
    """
    标准配置统一入口
    优先级建议：
      1) USE_LES=True → LES
      2) USE_PR_SOAP=True → SOAP PR
      3) 否则 → MOCK
    同时支持 dev fallback。
    """
    vin = (vin or "").strip()
    if not vin:
        return _mock_standard(vin)

    use_les = current_app.config.get("USE_LES", False)
    use_pr = current_app.config.get("USE_PR_SOAP", False)

    # 1) LES
    if use_les:
        try:
            return _les_standard(vin)
        except Exception as e:
            if current_app.debug and current_app.config.get("DEV_FALLBACK_TO_MOCK", True):
                return _mock_standard(vin)
            raise e

    # 2) PR SOAP
    if use_pr:
        try:
            return _soap_pr_standard(vin)
        except PRServiceError as e:
            if current_app.debug and current_app.config.get("DEV_FALLBACK_TO_MOCK", True):
                return _mock_standard(vin)
            raise e

    # 3) mock
    return _mock_standard(vin)
