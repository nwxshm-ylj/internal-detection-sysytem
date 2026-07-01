"""Flask application factory.

集中在此处完成应用配置、扩展初始化及蓝图注册，以便 run.py 与 WSGI 入口复用。
"""

from __future__ import annotations

from flask import Flask

from app.extensions import init_extensions
from app.services.pr_mapping import load_pr_rules


def create_app() -> Flask:
    """应用工厂：供命令行与 WSGI 容器复用。"""
    # 指定模板目录为 app/templates
    app = Flask(__name__, template_folder="templates")
    app.config.from_object("app.config.BaseConfig")

    # 初始化数据库、迁移等扩展
    init_extensions(app)

    # 显式 import 所有模型，确保 Alembic autogenerate 能发现表
    with app.app_context():
        from app import models  # noqa: F401  (注册所有 ORM 类)
        load_pr_rules()

    # 注册 REST API v1（注意：这里统一加前缀）
    from app.api.v1 import api_v1_bp
    app.register_blueprint(api_v1_bp, url_prefix="/api/v1")

    # 注册 REST API v2（会话化检测流程）
    from app.api.v2 import api_v2_bp
    app.register_blueprint(api_v2_bp, url_prefix="/api/v2")

    # 注册 Web（页面 + 上传）
    from app.web import web_bp
    app.register_blueprint(web_bp)

    return app
