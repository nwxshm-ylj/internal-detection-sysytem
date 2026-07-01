"""Application wide extensions (SQLAlchemy, Flask-Migrate, etc.).

统一在此模块声明扩展，避免循环依赖。
"""

from __future__ import annotations

import os

from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
migrate = Migrate()


def init_extensions(app: Flask) -> None:
    """集中初始化扩展，保证 app factory 保持精简。"""
    # 上传目录可能不存在，这里确保自动创建
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)
    db.init_app(app)
    migrate.init_app(app, db)
