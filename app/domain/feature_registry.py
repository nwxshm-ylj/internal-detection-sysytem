"""Domain specific feature constraints.

定义所有业务特征的取值范围与 mandatory 设置，供比对流程统一引用。

V2 扩展：
- 仍以 FEATURE_REGISTRY 字典对外暴露
- 新增辅助函数 register_feature() 便于运行时动态注册（测试 / 配置驱动）
- 后续扩展零件时，只需在下方追加 FeatureSpec 条目
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Set


@dataclass(frozen=True)
class FeatureSpec:
    """描述单个特征如何校验、是否会影响 overall 结果。"""

    name: str
    allowed: Optional[Set[str]] = None  # None 表示不做枚举校验
    mandatory: bool = False  # True 表示影响 overall


FEATURE_REGISTRY: Dict[str, FeatureSpec] = {
    "door_trim_color": FeatureSpec(
        name="door_trim_color",
        allowed={"panel_black", "panel_yellow", "panel_grey"},
        mandatory=True,
    ),
    # ===== 后续扩展示例（待业务确认后启用）=====
    # "seat_color": FeatureSpec(
    #     name="seat_color",
    #     allowed={"seat_black", "seat_brown", "seat_beige"},
    #     mandatory=True,
    # ),
    # "dashboard_color": FeatureSpec(
    #     name="dashboard_color",
    #     allowed={"dashboard_black", "dashboard_grey"},
    #     mandatory=True,
    # ),
    # "steering_wheel_color": FeatureSpec(
    #     name="steering_wheel_color",
    #     allowed={"sw_black", "sw_brown"},
    #     mandatory=False,
    # ),
}


def register_feature(spec: FeatureSpec) -> None:
    """运行时注册新 feature（测试 / 配置驱动场景使用）。"""
    FEATURE_REGISTRY[spec.name] = spec


def get_feature_spec(name: str) -> FeatureSpec:
    """获取 feature 规格；不存在则返回宽松默认（不做校验）。"""
    return FEATURE_REGISTRY.get(name, FeatureSpec(name=name, allowed=None, mandatory=False))


def list_feature_names() -> list[str]:
    """返回所有已注册的 feature 名（按注册顺序）。"""
    return list(FEATURE_REGISTRY.keys())
