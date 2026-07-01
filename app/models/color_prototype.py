from __future__ import annotations

from datetime import datetime
from app.extensions import db


class ColorPrototype(db.Model):
    """
    在线校准用：记录某个 feature 的某个颜色 label 的 Lab running-mean。

    feature: "door_trim_color"
    label:   "panel_black" / "panel_grey" / "panel_yellow"
    """

    __tablename__ = "color_prototype"

    id = db.Column(db.Integer, primary_key=True)

    feature = db.Column(db.String(64), nullable=False)
    label = db.Column(db.String(64), nullable=False)

    # running mean in Lab
    lab_l = db.Column(db.Float, nullable=False, default=0.0)
    lab_a = db.Column(db.Float, nullable=False, default=0.0)
    lab_b = db.Column(db.Float, nullable=False, default=0.0)
    n = db.Column(db.Integer, nullable=False, default=0)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("feature", "label", name="uq_feature_label"),
    )
