# 内饰检测系统（InteriorDetection）

汽车内饰门板颜色自动检测系统，通过 YOLOv8 目标检测 + Lab 颜色分类，自动判断门内饰条颜色是否与标准配置一致。

系统分为两部分：
- **Flask 后端**：接收图片、运行 YOLOv8 推理、颜色比对、返回检测结果
- **Android APP**：扫描 VIN 条码、拍照、调用后端 API、展示检测结果

---

## 检测流程

```
扫描VIN条码 → 获取标准配置(PR码映射) → 拍照上传
    → YOLOv8检测门板区域 → Lab颜色分类 → 与标准比对 → OK/NG
```

1. 通过 VIN 获取该车的标准配置（PR 码 → 门板颜色映射）
2. YOLOv8 模型检测图片中的门内饰条区域（panel_color）
3. 裁剪 ROI，计算 Lab 颜色空间中位数
4. 与颜色原型（panel_black / panel_grey / panel_yellow）做距离比对
5. 将识别结果与标准配置比对，输出 OK / NG / UNKNOWN

---

## 项目结构

```
InteriorDetection/
├── app/                              # Flask 后端
│   ├── api/v1.py                     # REST API（/api/v1/inspection）
│   ├── services/
│   │   ├── inference_service.py      # YOLOv8 推理 + Lab 颜色分类
│   │   ├── standard_service.py       # 标准配置获取（LES/SOAP/Mock）
│   │   ├── compare_service.py        # 标准 vs 检测结果比对
│   │   ├── color_calibration_service.py  # 在线颜色校准
│   │   └── pr_mapping.py            # PR码 → 特征映射
│   ├── models/
│   │   ├── door_interior_yolov8.pt   # YOLOv8 模型文件
│   │   ├── inspection.py             # 检测记录 ORM
│   │   └── color_prototype.py        # 颜色原型 ORM
│   ├── resources/pr_rules.yaml       # PR码映射规则
│   ├── clients/les_client.py         # LES/SOAP 客户端
│   └── web/routes.py                 # Web 页面路由
├── android/                          # Android APP
│   └── app/src/main/java/com/interior/detection/
│       ├── data/
│       │   ├── api/InspectionApi.kt      # Retrofit API 接口
│       │   ├── api/RetrofitClient.kt     # 网络客户端
│       │   ├── model/ApiResponse.kt      # 数据模型
│       │   └── repository/InspectionRepository.kt
│       └── ui/
│           ├── MainActivity.kt           # 入口 + 权限
│           ├── MainScreen.kt             # 主界面 Compose UI
│           ├── MainViewModel.kt          # 业务逻辑状态机
│           ├── camera/CameraPreview.kt   # CameraX 拍照
│           ├── camera/BarcodeScanner.kt  # ML Kit 条码扫描
│           └── components/ResultCard.kt  # 结果展示卡片
├── run.py                            # Flask 开发启动入口
├── .env                              # 环境变量配置
└── requirements.txt                  # Python 依赖
```

---

## 快速开始

### 1. 启动 Flask 后端

```bash
# 安装依赖
pip install -r requirements.txt
pip install ultralytics opencv-python-headless

# 启动服务（监听 0.0.0.0:5000）
python run.py
```

### 2. 构建 Android APP

1. 用 Android Studio 打开 `android/` 目录
2. 修改 `android/app/build.gradle.kts` 中的 `API_BASE_URL` 为服务器局域网 IP：
   ```kotlin
   buildConfigField("String", "API_BASE_URL", "\"http://192.168.1.100:5000\"")
   ```
3. Build → Build APK(s)，生成的 APK 在 `android/app/build/outputs/apk/debug/app-debug.apk`
4. 安装到手机（USB 调试或直接传输 APK 安装）

### 3. 使用

1. 确保手机和服务器在同一局域网
2. 打开 APP，授予相机权限
3. 扫描 VIN 条码（或手动输入）
4. 确认 VIN 后进入 10 秒倒计时
5. 自动后置拍摄 → 上传检测 → 前置拍摄 → 上传检测
6. 查看检测结果（OK / NG）

---

## 环境变量配置（.env）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `USE_LES` | `0` | 是否启用 LES 标准配置接口 |
| `USE_PR_SOAP` | `0` | 是否启用 PR SOAP 接口 |
| `INFERENCE_MODE` | `yolov8` | 推理模式：yolov8 / mock |
| `MOCK_PR_GROUP` | `MCK~08Y` | Mock 模式下的 PR 码（08Y=黑色, 08W=灰色, 08Z=黄色） |
| `YOLO_CONF` | `0.25` | YOLOv8 置信度阈值 |
| `COLOR_TH_OK` | `25.0` | 颜色 Lab 距离 OK 阈值 |
| `COLOR_CALIBRATION_ENABLED` | `1` | 是否启用在线颜色校准 |

---

## API 接口

### 健康检查
```
GET /api/v1/health
```

### 检测接口
```
POST /api/v1/inspection
Content-Type: multipart/form-data

参数：
  vin              - 车架号（必填）
  client_event_id  - 事件ID，用于幂等（可选，自动生成）
  image            - JPEG/PNG 图片（必填）

返回：
{
  "code": 200,
  "msg": "ok",
  "data": {
    "record_id": 1,
    "vin": "LSVXXXXXXXX",
    "overall": "OK",          // OK / NG / UNKNOWN
    "standard": { ... },       // 标准配置
    "detected": { ... },       // 检测结果
    "compare_result": { ... }  // 比对详情
  }
}
```

---

## 标准配置来源

按优先级：
1. **LES HTTP**（`USE_LES=1`）— 内网 LES 系统，根据 VIN 获取完整配置
2. **PR SOAP**（`USE_PR_SOAP=1`）— SOAP 接口获取 PR 码组合
3. **Mock**（默认）— 使用 `.env` 中的固定 PR 码

PR 码通过 `app/resources/pr_rules.yaml` 映射为门板颜色：
- `MCK~08Y` → panel_black（黑色）
- `MCK~08W` → panel_grey（灰色）
- `MCK~08Z` → panel_yellow（黄色）

---

## 技术栈

**后端：**
- Python 3.10+、Flask 3.0、SQLAlchemy、Flask-Migrate
- YOLOv8（ultralytics）、OpenCV
- SQLite（开发）/ 可切换 PostgreSQL

**Android APP：**
- Kotlin、Jetpack Compose、Material 3
- CameraX（拍照）、ML Kit（条码扫描）
- Retrofit + OkHttp（网络请求）
- MVVM 架构
