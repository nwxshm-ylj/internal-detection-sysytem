"""WSGI entrypoint for production deployments.

生产环境通常由 uwsgi/gunicorn 等 WSGI 容器导入该模块。
"""

from app import create_app

# 当 WSGI 服务器导入模块时即完成应用实例化
app = create_app()
