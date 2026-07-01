from __future__ import annotations

from flask import Flask

from app.extensions import init_extensions
from app.services.pr_mapping import load_pr_rules


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object("app.config.BaseConfig")

    # 初始化扩展（db/migrate 等）
    init_extensions(app)

    # 确保新模型被加载（供 migrate 扫描）
    from app.models.color_prototype import ColorPrototype  # noqa: F401

    # PR 规则需在 app_context 内加载
    with app.app_context():
        load_pr_rules()

    from app.api.v1 import api_v1_bp
    app.register_blueprint(api_v1_bp, url_prefix="/api/v1")

    return app
