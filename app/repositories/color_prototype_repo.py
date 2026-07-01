from __future__ import annotations

from datetime import datetime
from typing import Dict, Tuple

from app.extensions import db
from app.models.color_prototype import ColorPrototype


def get_prototypes(feature: str) -> Dict[str, Tuple[float, float, float]]:
    """
    返回 {label: (L, a, b)}，若为空 dict 表示尚未校准。
    """
    rows = (
        db.session.query(ColorPrototype)
        .filter(ColorPrototype.feature == feature)
        .all()
    )
    out: Dict[str, Tuple[float, float, float]] = {}
    for r in rows:
        out[r.label] = (float(r.lab_l), float(r.lab_a), float(r.lab_b))
    return out


def upsert_running_mean(feature: str, label: str, lab: Tuple[float, float, float]) -> None:
    """
    running mean 更新：new = (old*n + x) / (n+1)
    """
    l, a, b = lab
    row = (
        db.session.query(ColorPrototype)
        .filter(ColorPrototype.feature == feature, ColorPrototype.label == label)
        .one_or_none()
    )

    if row is None:
        row = ColorPrototype(
            feature=feature,
            label=label,
            lab_l=l,
            lab_a=a,
            lab_b=b,
            n=1,
            updated_at=datetime.utcnow(),
        )
        db.session.add(row)
        db.session.commit()
        return

    n0 = int(row.n)
    n1 = n0 + 1
    row.lab_l = (row.lab_l * n0 + l) / n1
    row.lab_a = (row.lab_a * n0 + a) / n1
    row.lab_b = (row.lab_b * n0 + b) / n1
    row.n = n1
    row.updated_at = datetime.utcnow()
    db.session.commit()
