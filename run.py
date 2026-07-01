"""Development entrypoint.

本模块作为本地开发入口，通过 `python run.py` 快速拉起应用。
"""

from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    # ssl_context="adhoc" 用于浏览器端 HTTPS 访问摄像头
    # 安卓 APP 客户端可直接用 HTTP，故默认关闭 SSL
    # 如需 HTTPS，取消下面注释并注释掉 HTTP 行
    # app.run(host="0.0.0.0", port=5000, ssl_context="adhoc", debug=True)
    app.run(host="0.0.0.0", port=5000, debug=True)
