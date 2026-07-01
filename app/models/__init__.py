"""Models package.

显式 import 所有 ORM 类，确保 Flask-Migrate / Alembic 能在 autogenerate 时
发现所有表（否则只在 repo 中懒加载的模型会被遗漏）。
"""

from app.models.color_prototype import ColorPrototype  # noqa: F401
from app.models.inspection import InspectionRecord  # noqa: F401
from app.models.inspection_session import InspectionFrame, InspectionSession  # noqa: F401

__all__ = [
    "ColorPrototype",
    "InspectionRecord",
    "InspectionSession",
    "InspectionFrame",
]