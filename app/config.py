"""Application configuration objects.

集中定义 Flask 应用所需的所有配置项，可通过环境变量灵活覆盖。
"""

from __future__ import annotations

import os


class BaseConfig:
    """共享默认配置，供开发/生产环境继承。"""

    BASE_DIR = os.path.abspath(os.path.dirname(__file__))

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")

    # ===== PR 规则 =====
    PR_STRICT_CONFLICT = os.getenv("PR_STRICT_CONFLICT", "0") == "1"
    PR_RULES_PATH = os.getenv(
        "PR_RULES_PATH",
        os.path.join(BASE_DIR, "resources", "pr_rules.yaml"),
    )

    # ===== 上传目录 =====
    UPLOAD_DIR = os.getenv(
        "UPLOAD_DIR",
        os.path.join(BASE_DIR, "..", "uploads"),
    )
    # Upload validation
    MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))  # 10MB
    MAX_CONTENT_LENGTH = MAX_UPLOAD_BYTES
    ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png"}
    ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png"}
    MAX_IMAGE_PIXELS = int(os.getenv("MAX_IMAGE_PIXELS", str(20_000_000)))
    MAX_IMAGE_WIDTH = int(os.getenv("MAX_IMAGE_WIDTH", "8000"))
    MAX_IMAGE_HEIGHT = int(os.getenv("MAX_IMAGE_HEIGHT", "8000"))

    # ===== 是否启用 LES =====
    USE_LES = os.getenv("USE_LES", "0") == "1"

    # ===== LES API =====
    LES_API_URL = os.getenv("LES_API_URL", "http://les.example/api/config")
    LES_API_TIMEOUT = float(os.getenv("LES_API_TIMEOUT", "3.0"))

    # ===== 推理（原有字段保留）=====
    # 你现在要用 YOLOv8：建议把环境变量 INFERENCE_MODE 设为 "yolov8"
    # 兼容：仍保留 local/remote 的写法，不会破坏旧逻辑
    INFERENCE_MODE = os.getenv("INFERENCE_MODE", "yolov8")  # yolov8 / local / remote / mock
    INFERENCE_URL = os.getenv("INFERENCE_URL", "http://inference.example/api")
    INFERENCE_TIMEOUT = float(os.getenv("INFERENCE_TIMEOUT", "10.0"))

    # ===== DB =====
    SQLALCHEMY_DATABASE_URI = os.getenv("DB_URL", "sqlite:///inspection.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ===== Mock 标准配置（开发期使用）=====
    MOCK_STANDARD = {
        "model": os.getenv("MOCK_MODEL", "ZP12CK"),
        "color_code": os.getenv("MOCK_COLOR_CODE", "71A1"),
        "interior_code": os.getenv("MOCK_INTERIOR_CODE", "NA"),
        "prGroup": os.getenv("MOCK_PR_GROUP", "MCK~08Y"),
    }

    # ===== PR SOAP 开关（内网可用）=====
    USE_PR_SOAP = os.getenv("USE_PR_SOAP", "0") == "1"
    PR_SOAP_WSDL_URL = os.getenv(
        "PR_SOAP_WSDL_URL",
        "http://172.29.76.49:47220/backend/services/IPrService?wsdl",
    )
    PR_SOAP_TIMEOUT = float(os.getenv("PR_SOAP_TIMEOUT", "5.0"))
    PR_SOAP_VERIFY_SSL = os.getenv("PR_SOAP_VERIFY_SSL", "0") == "1"

    # 开发期：接口失败是否自动 fallback 到 mock
    DEV_FALLBACK_TO_MOCK = os.getenv("DEV_FALLBACK_TO_MOCK", "1") == "1"

    # =========================================================
    # YOLOv8（门内饰条：panel_color）
    # =========================================================

    # 模型路径（建议用绝对路径或相对项目根目录）
# app/config.py

    YOLO_MODEL_PATH = os.getenv(
        "YOLO_MODEL_PATH",
        os.path.join(BASE_DIR, "models", "door_interior_yolov8.pt"),
    )


    # 你的训练类别名已确认是 panel_color
    YOLO_PANEL_CLASSNAMES = ["panel_color"]

    # ===== V2：feature → YOLO 类名映射 =====
    # 当 YOLO 模型重训增加新类别后，在这里扩展映射即可
    # key = 业务 feature 名（与 FeatureRegistry 一致）
    # value = YOLO 模型中的类名列表（一个 feature 可能对应多个类名别名）
    YOLO_FEATURE_CLASS_MAP = {
        "door_trim_color": ["panel_color"],
        # 后续扩展示例（待模型重训后启用）：
        # "seat_color": ["seat"],
        # "dashboard_color": ["dashboard"],
        # "steering_wheel_color": ["steering_wheel"],
    }

    # YOLO 置信度阈值（你原来的字段）
    YOLO_CONF_TH = float(os.getenv("YOLO_CONF_TH", "0.5"))

    # 兼容字段：如果 inference_service 读取 YOLO_CONF，也能取到值
    YOLO_CONF = float(os.getenv("YOLO_CONF", str(YOLO_CONF_TH)))

    # 推理图像尺寸（可选；CPU 下可用 640/512）
    YOLO_IMG_SIZE = int(os.getenv("YOLO_IMG_SIZE", "640"))

    # ROI 内缩比例（你原来的字段）
    ROI_INSET_RATIO = float(os.getenv("ROI_INSET_RATIO", "0.15"))

    # =========================================================
    # 颜色判定阈值（Lab 距离）
    # =========================================================

    # 你原来的 OK/WARN 阈值保留
    COLOR_TH_OK = float(os.getenv("COLOR_TH_OK", "25.0"))
    COLOR_TH_WARN = float(os.getenv("COLOR_TH_WARN", "40.0"))

    # 兼容字段：如果代码读取 COLOR_DIST_THRESHOLD，则取 COLOR_TH_OK
    COLOR_DIST_THRESHOLD = float(os.getenv("COLOR_DIST_THRESHOLD", str(COLOR_TH_OK)))

    # 在线校准开关：建议默认开启
    COLOR_CALIBRATION_ENABLED = os.getenv("COLOR_CALIBRATION_ENABLED", "1") == "1"

    #（可选）当距离超阈值时是否强制输出最近类别（默认 False：更安全，避免误判）
    FORCE_COLOR_OUTPUT = os.getenv("FORCE_COLOR_OUTPUT", "0") == "1"


class DevConfig(BaseConfig):
    """开发环境配置，打开 DEBUG 方便排查。"""
    DEBUG = True


class ProdConfig(BaseConfig):
    """生产环境配置，默认关闭 DEBUG。"""
    DEBUG = False
