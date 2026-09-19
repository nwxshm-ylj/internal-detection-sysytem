# 内饰检测系统项目交接文档

> 项目：InteriorDetection / internal-detection-sysytem  
> 交接目标：帮助后续维护同事快速理解当前项目结构、主要功能、业务流程、配置、部署方式和维护风险。  
> 核对基线：main 分支，2026-09-19。  
> 说明：本文以当前仓库代码为准。根目录 README.md 中部分流程说明已经落后于当前 v2 实现，差异已在本文中标出。

---

## 1. 项目定位

本项目用于汽车内饰门板颜色自动检测。

当前真正投入代码实现的核心业务特征为：

- `door_trim_color`：门内饰条颜色

当前支持的颜色标签：

- `panel_black`：黑色
- `panel_grey`：灰色
- `panel_yellow`：黄色

项目不是让 YOLO 直接完成颜色三分类，而是采用“目标定位 + 颜色判定”的两阶段方案：

```text
VIN
  ↓
获取车辆标准配置（LES / PR SOAP / Mock）
  ↓
PR 规则映射出标准门板颜色
  ↓
Android 连续拍摄多帧
  ↓
YOLOv8 定位 panel_color 区域
  ↓
裁剪 ROI
  ↓
Lab 颜色空间统计
  ↓
与颜色 Prototype 比较
  ↓
得到 panel_black / panel_grey / panel_yellow / None
  ↓
多帧结果聚合
  ↓
与标准配置比对
  ↓
OK / NG / UNKNOWN
```

系统由两个主要部分组成：

1. **Flask 后端**
   - 标准配置获取
   - 图片接收与校验
   - YOLOv8 推理
   - Lab 颜色分类
   - 多帧聚合
   - 标准/检测结果比对
   - 数据库存储
   - 在线颜色原型校准

2. **Android APP**
   - VIN 扫码或手工输入
   - 创建检测会话
   - 自动倒计时
   - 连续拍照
   - 调用 v2 API
   - 显示实时识别与最终结果

---

## 2. 当前版本关系

项目同时保留 v1 和 v2 两套接口。

### 2.1 v2：当前主流程

主要代码：

```text
app/api/v2.py
app/services/inference_service_v2.py
app/services/aggregation_service.py
app/models/inspection_session.py
app/repositories/session_repo.py
android/
```

v2 的设计是“一辆车一次检测 = 一个 Session + N 个 Frame”。

当前 Android 实际参数：

- 默认连续拍摄：8 帧
- 开始前倒计时：5 秒
- 帧间隔：700 ms
- 当前始终使用后置摄像头
- JPEG 压缩质量：85

v2 支持：

- Session 幂等
- Frame 幂等
- 每帧实时推理
- 多帧加权投票
- 最终聚合判定
- Session 级完整历史记录

后续新增业务功能，优先基于 v2 开发。

### 2.2 v1：兼容旧单图流程

主要代码：

```text
app/api/v1.py
app/services/inference_service.py
app/models/inspection.py
app/repositories/inspection_repo.py
```

v1 一次请求上传一张图片，直接完成标准配置获取、推理、比对和落库。

幂等键：

```text
VIN + client_event_id
```

除非需要维护旧客户端兼容问题，否则不建议继续在 v1 上扩展新能力。

---

## 3. v2 主业务流程

### 3.1 创建检测会话

接口：

```text
POST /api/v2/session/start
```

请求示例：

```json
{
  "vin": "LSVXXXXXXXXXXXXXX",
  "client_session_id": "APP生成的UUID"
}
```

主要逻辑：

1. 校验 VIN 是否为空。
2. `client_session_id` 为空时由后端自动生成 UUID。
3. 根据 `VIN + client_session_id` 查询是否已经存在会话。
4. 已存在则直接返回原会话，并标记 `idempotent_hit=true`。
5. 调用 `get_standard_config(vin)` 获取标准配置。
6. 创建 `inspection_session`。
7. 将标准配置写入 `standard_json`。

**关键设计：标准配置在 Session 创建时保存为快照。**  
后续 finish 阶段不会重新拉取 LES/PR，因此一次检测过程中标准不会发生变化。

### 3.2 上传单帧

接口：

```text
POST /api/v2/session/{session_id}/frame
Content-Type: multipart/form-data
```

参数：

| 参数 | 说明 |
|---|---|
| `image` | jpg/png 图片，必填 |
| `frame_index` | 帧序号，APP 从 0 开始 |

后端校验内容：

- 文件是否存在
- 扩展名
- MIME
- 文件大小
- OpenCV 是否能正常解码
- 图片宽高
- 总像素数

默认限制：

| 配置 | 默认值 |
|---|---:|
| `MAX_UPLOAD_BYTES` | 10 MB |
| `MAX_IMAGE_PIXELS` | 20,000,000 |
| `MAX_IMAGE_WIDTH` | 8000 |
| `MAX_IMAGE_HEIGHT` | 8000 |
| `ALLOWED_IMAGE_EXT` | jpg/jpeg/png |

图片保存位置：

```text
uploads/YYYYMMDD/{vin}_{client_session_id}_{frame_index}_{timestamp}.jpg
```

数据库中保存相对于 `UPLOAD_DIR` 的路径。

Frame 幂等键：

```text
session_id + frame_index
```

同一个 `frame_index` 重复上传时，接口直接返回已有结果，不再重复插入数据库。

### 3.3 单帧 AI 推理

核心入口：

```text
app.services.inference_service_v2.infer_frame()
```

当前模型文件：

```text
app/models/door_interior_yolov8.pt
```

当前业务映射：

```text
door_trim_color → YOLO class panel_color
```

推理过程：

1. OpenCV 读取图片。
2. 懒加载 Ultralytics YOLO 模型，进程内只加载一次。
3. 根据 `YOLO_IMG_SIZE` 和 `YOLO_CONF` 执行推理。
4. 根据 `YOLO_FEATURE_CLASS_MAP` 把 YOLO 类转换为业务 feature。
5. 同一个 feature 有多个框时，只保留置信度最高的框。
6. 裁剪 ROI。
7. 对 ROI 进行 Lab 颜色分类。
8. 返回 feature 的 `label / conf / bbox / yolo_class / lab_meta`。

当前代码虽然预留了多 feature 能力，但**当前模型实际仍只支持 `door_trim_color`**。

### 3.4 Lab 颜色分类

主要代码：

```text
app/services/inference_service_v2.py
app/services/color_calibration_service.py
app/repositories/color_prototype_repo.py
```

默认冷启动颜色 Prototype：

| 标签 | Lab Prototype |
|---|---|
| `panel_black` | (20, 128, 128) |
| `panel_grey` | (55, 128, 128) |
| `panel_yellow` | (70, 110, 170) |

处理过程：

1. 取 YOLO bbox 对应 ROI。
2. 再取 ROI 中心约 70% 区域，降低边缘背景干扰。
3. BGR 转 Lab。
4. 过滤过暗和过亮像素：`L <= 20` 或 `L >= 235`。
5. 计算剩余像素的 Lab 中位数。
6. 与各 Prototype 计算欧氏距离。
7. 选择距离最小的颜色。
8. 若最小距离大于 `COLOR_DIST_THRESHOLD`，返回 `None`，避免强行误判。

默认 `COLOR_DIST_THRESHOLD=25`。

排查颜色问题时，优先查看 `lab_meta` 中：

- `lab_median`
- `distances`
- `selected`
- `selected_dist`
- `threshold`
- `reason`

### 3.5 在线颜色校准

当满足以下条件时：

- `COLOR_CALIBRATION_ENABLED=1`
- 标准配置存在合法颜色
- 当前检测标签与标准标签一致
- bbox 有效

系统会重新计算 ROI 的 Lab 中位数，并更新 `color_prototype` 表中的 running mean。

更新思想：

```text
new_mean = (old_mean × n + current_value) / (n + 1)
```

校准异常不会中断检测主流程。

### 3.6 多帧聚合

主要代码：

```text
app/services/aggregation_service.py
```

当前策略：

```text
confidence_weighted_voting
```

示例：

```text
frame 1: black, conf=0.90
frame 2: black, conf=0.80
frame 3: grey,  conf=0.60

black 总权重 = 1.70
grey  总权重 = 0.60

最终结果 = black
```

每个 feature 的聚合结果包含：

- `label`
- `confidence`
- `frame_count`
- `label_votes`
- `unanimous`
- `inlier_ratio`

注意：

- `label=None` 的帧不参与投票。
- 但仍计入 `frame_count`。
- 如果所有帧都未识别，该 feature 最终 `label=None`。

### 3.7 标准比对

主要代码：

```text
app/services/compare_service.py
app/domain/feature_registry.py
```

当前 Feature Registry：

```text
feature: door_trim_color
mandatory: true
allowed:
  panel_black
  panel_grey
  panel_yellow
```

规则：

| 场景 | 结果 |
|---|---|
| 标准值缺失 | UNKNOWN |
| 检测值缺失且 mandatory=true | NG |
| 检测值缺失且 mandatory=false | UNKNOWN |
| 检测值不在 allowed 中 | NG |
| 标准值 = 检测值 | OK |
| 标准值 != 检测值 | NG |

`door_trim_color` 当前为 mandatory，因此检测不到会直接使整车 `overall=NG`。

---

## 4. Android APP 实际流程

主要目录：

```text
android/app/src/main/java/com/interior/detection/
├── data/
│   ├── api/
│   │   ├── InspectionApi.kt
│   │   └── RetrofitClient.kt
│   ├── model/
│   │   └── SessionDtos.kt
│   └── repository/
│       └── SessionRepository.kt
└── ui/
    ├── MainActivity.kt
    ├── MainScreen.kt
    ├── MainViewModel.kt
    ├── camera/
    │   ├── BarcodeScanner.kt
    │   └── CameraPreview.kt
    └── components/
        └── SessionResultCard.kt
```

### 4.1 MainViewModel 状态机

```text
IDLE
→ SCANNING
→ VIN_READY
→ STARTING_SESSION
→ COUNTDOWN
→ CAPTURING
→ UPLOADING
→ ...
→ FINISHING
→ DONE

异常时：
→ ERROR
```

实际流程：

1. 扫描条码或手工输入 VIN。
2. APP 生成 `clientSessionId=UUID.randomUUID()`。
3. 调用 `startSession`。
4. 倒计时 5 秒。
5. 连续拍 8 帧。
6. 每帧压缩为 JPEG quality=85。
7. 每帧调用 `uploadFrame`。
8. APP 显示当前帧简略结果。
9. 8 帧全部完成后调用 `finish`。
10. 显示 `overall / aggregated / compare_result`。

### 4.2 网络层

Retrofit Base URL：

```text
BuildConfig.API_BASE_URL
```

当前仓库默认地址：

```text
http://172.20.10.8:5000
```

换服务器、电脑、热点或现场网段时必须重新修改并打包 APK。

网络超时：

- connectTimeout：15 秒
- readTimeout：30 秒
- writeTimeout：30 秒

Debug 包开启 HTTP BODY 日志。

AndroidManifest 当前允许明文 HTTP：

```text
android:usesCleartextTraffic="true"
```

---

## 5. 后端目录结构

```text
.
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── extensions.py
│   ├── api/
│   │   ├── v1.py
│   │   └── v2.py
│   ├── clients/
│   │   └── les_client.py
│   ├── domain/
│   │   └── feature_registry.py
│   ├── models/
│   │   ├── door_interior_yolov8.pt
│   │   ├── inspection.py
│   │   ├── inspection_session.py
│   │   └── color_prototype.py
│   ├── repositories/
│   │   ├── inspection_repo.py
│   │   ├── session_repo.py
│   │   └── color_prototype_repo.py
│   ├── resources/
│   │   └── pr_rules.yaml
│   ├── services/
│   │   ├── standard_service.py
│   │   ├── pr_mapping.py
│   │   ├── inference_service.py
│   │   ├── inference_service_v2.py
│   │   ├── aggregation_service.py
│   │   ├── compare_service.py
│   │   └── color_calibration_service.py
│   ├── utils/
│   │   └── response_utils.py
│   └── web/
│       └── routes.py
├── android/
├── datasets/
├── migrations/
├── plans/
├── scripts/
│   └── v2-selftest.ps1
├── test_data/
├── run.py
├── wsgi.py
└── requirements.txt
```

### 5.1 主要文件职责

| 文件 | 职责 |
|---|---|
| `app/__init__.py` | Flask Application Factory、注册 Blueprint、启动加载 PR 规则 |
| `app/config.py` | 后端集中配置 |
| `app/extensions.py` | SQLAlchemy 和 Flask-Migrate 初始化 |
| `app/api/v1.py` | 旧版单图检测 |
| `app/api/v2.py` | 当前 Session + Frame 多帧主接口 |
| `app/clients/les_client.py` | LES HTTP / PR SOAP 调用 |
| `app/domain/feature_registry.py` | feature 允许值与 mandatory 规则 |
| `app/services/standard_service.py` | 标准配置统一入口 |
| `app/services/pr_mapping.py` | PR 规则映射 |
| `app/services/inference_service_v2.py` | YOLO + Lab 单帧推理 |
| `app/services/aggregation_service.py` | 多帧聚合 |
| `app/services/compare_service.py` | 标准/检测比对 |
| `app/services/color_calibration_service.py` | 在线颜色校准 |
| `app/repositories/session_repo.py` | Session / Frame 数据访问 |
| `app/repositories/color_prototype_repo.py` | Prototype 数据访问 |
| `app/resources/pr_rules.yaml` | PR → feature 配置规则 |
| `scripts/v2-selftest.ps1` | v2 API 端到端自测 |

---

## 6. 标准配置与 PR 映射

统一入口：

```text
get_standard_config(vin)
```

优先级：

```text
USE_LES=1
    ↓
LES

否则 USE_PR_SOAP=1
    ↓
PR SOAP

否则
    ↓
Mock
```

### 6.1 LES HTTP

当前代码约定：

```text
GET LES_API_URL?vin=<VIN>
```

期望返回至少可以提供：

- vin
- model
- farbau
- farbin
- prGroup

### 6.2 PR SOAP

默认 WSDL：

```text
http://172.29.76.49:47220/backend/services/IPrService?wsdl
```

生产现场应通过配置维护真实地址，不建议依赖代码中的默认值。

### 6.3 当前 PR 规则

文件：

```text
app/resources/pr_rules.yaml
```

规则版本：

```text
2025-01-01
```

当前映射：

| PR | 标准结果 | Priority |
|---|---|---:|
| `MCK~08Z` | panel_yellow | 100 |
| `MCK~08Y` | panel_black | 90 |
| `MCK~08W` | panel_grey | 80 |

默认情况下，同一 feature 多个规则同时命中时按 priority 选择。

设置 `PR_STRICT_CONFLICT=1` 后，多规则冲突会直接报错。

后续修改标准配置规则时优先维护 YAML，不要把业务规则直接写进 API。

---

## 7. 数据库结构

默认数据库：

```text
sqlite:///inspection.db
```

可以通过 `DB_URL` 替换。

### 7.1 inspection_record

v1 单图检测记录。

关键字段：

- id
- vin
- client_event_id
- image_path
- standard_json
- detected_json
- compare_json
- overall
- created_at

唯一约束：

```text
(vin, client_event_id)
```

### 7.2 inspection_session

v2 会话主表。

关键字段：

- id
- vin
- client_session_id
- status
- standard_json
- aggregated_json
- compare_json
- overall
- frame_count
- created_at
- finished_at

状态设计：

- RUNNING
- FINISHED
- ABORTED

当前接口实际主要使用 RUNNING / FINISHED，暂未提供单独 abort API。

唯一约束：

```text
(vin, client_session_id)
```

### 7.3 inspection_frame

v2 单帧表。

字段：

- id
- session_id
- frame_index
- image_path
- detected_json
- created_at

唯一约束：

```text
(session_id, frame_index)
```

### 7.4 color_prototype

在线颜色原型表。

字段：

- feature
- label
- lab_l
- lab_a
- lab_b
- n
- updated_at

唯一约束：

```text
(feature, label)
```

---

## 8. API 清单

统一响应结构：

```json
{
  "code": 200,
  "msg": "ok",
  "data": {},
  "trace_id": "..."
}
```

客户端可以在请求头传 `X-Trace-Id`；未传时后端自动生成。

### 8.1 v2

```text
GET  /api/v2/health
POST /api/v2/session/start
POST /api/v2/session/{id}/frame
POST /api/v2/session/{id}/finish
GET  /api/v2/session/{id}
```

### 8.2 v1

```text
GET  /api/v1/health
POST /api/v1/inspection
```

v1 inspection 参数：

- vin
- client_event_id
- image

---

## 9. 关键环境配置

主要配置在 `app/config.py`。

| 环境变量 | 说明 |
|---|---|
| `SECRET_KEY` | Flask Secret，生产必须修改 |
| `DB_URL` | 数据库地址 |
| `UPLOAD_DIR` | 图片保存目录 |
| `USE_LES` | 是否使用 LES |
| `LES_API_URL` | LES HTTP 地址 |
| `LES_API_TIMEOUT` | LES 超时 |
| `USE_PR_SOAP` | 是否使用 PR SOAP |
| `PR_SOAP_WSDL_URL` | PR SOAP WSDL |
| `PR_SOAP_TIMEOUT` | SOAP 超时 |
| `PR_SOAP_VERIFY_SSL` | SOAP SSL 校验 |
| `DEV_FALLBACK_TO_MOCK` | Debug 时外部接口失败是否回退 Mock |
| `MOCK_PR_GROUP` | Mock PR |
| `INFERENCE_MODE` | yolov8 / local / mock |
| `YOLO_MODEL_PATH` | 模型路径 |
| `YOLO_CONF` | YOLO 阈值 |
| `YOLO_IMG_SIZE` | 推理尺寸 |
| `COLOR_DIST_THRESHOLD` | Lab 距离阈值 |
| `COLOR_CALIBRATION_ENABLED` | 在线校准开关 |
| `PR_STRICT_CONFLICT` | PR 冲突是否直接报错 |

部分字段属于历史或预留配置，例如：

- INFERENCE_URL
- INFERENCE_TIMEOUT
- COLOR_TH_WARN
- FORCE_COLOR_OUTPUT
- ROI_INSET_RATIO

当前 v2 主链并未完整使用这些字段。修改配置前先全局搜索调用点。

---

## 10. 后端启动与数据库迁移

### 10.1 Python

建议 Python 3.10+。

安装基础依赖：

```bash
pip install -r requirements.txt
pip install ultralytics opencv-python-headless numpy PyYAML
```

当前 `requirements.txt` 并未完整覆盖实际代码依赖，详见后面的已知问题。

### 10.2 数据库迁移

建议显式指定 Flask APP：

```bash
python -m flask --app wsgi:app db upgrade
python -m flask --app wsgi:app db current
```

### 10.3 开发启动

```bash
python run.py
```

当前监听：

```text
0.0.0.0:5000
```

`run.py` 当前直接 `debug=True`，只用于开发调试。

### 10.4 生产入口

生产 WSGI 入口：

```text
wsgi.py:app
```

仓库目前没有完整提供 Gunicorn/uWSGI/systemd/NSSM 等生产进程配置。

真正部署时需要根据现场补齐：

- WSGI Server
- 服务守护和开机启动
- 日志切割
- 端口/防火墙
- 反向代理或网络策略
- 备份与磁盘空间监控

---

## 11. Android 构建

使用 Android Studio 打开 `android/` 目录。

当前配置：

| 项目 | 值 |
|---|---:|
| compileSdk | 34 |
| minSdk | 26 |
| targetSdk | 34 |
| Java/Kotlin JVM | 17 |
| versionName | 1.0.0 |

后端地址位于：

```text
android/app/build.gradle.kts
```

当前：

```text
http://172.20.10.8:5000
```

换现场 IP 后需要重新 Build APK。

仓库中已经存在历史 build 目录和 APK，但交接后建议使用本机重新构建，不要把历史 APK 当成唯一发布包。

---

## 12. v2 自测

现有脚本：

```text
scripts/v2-selftest.ps1
```

默认验证：

1. 数据库迁移状态
2. v2 health
3. start session
4. 上传 8 帧
5. finish
6. 获取 session detail
7. 重复 start 的幂等性
8. FINISHED 后继续上传是否返回 409

执行：

```powershell
.\scripts\v2-selftest.ps1
```

建议新同事第一次接手时先跑通：

```text
flask db upgrade
    ↓
python run.py
    ↓
GET /api/v2/health
    ↓
v2-selftest.ps1
    ↓
Android 真机测试
```

---

## 13. 常见问题排查

### 13.1 APP 无法连接后端

依次检查：

1. 手机和服务器是否同一网络。
2. `API_BASE_URL` 是否仍是旧 IP。
3. 服务器 5000 端口是否开放。
4. Flask 是否监听 `0.0.0.0`。
5. 手机浏览器能否访问 `/api/v2/health`。
6. Retrofit Debug 日志是 ConnectTimeout 还是 Connection Refused。

### 13.2 Session 创建失败

检查：

1. 数据库 migration。
2. `USE_LES / USE_PR_SOAP`。
3. LES/PR 接口是否可达。
4. PR SOAP 地址是否正确。
5. 当前是否处于 Debug。
6. `DEV_FALLBACK_TO_MOCK` 是否开启。

### 13.3 YOLO 模型找不到

检查：

- `YOLO_MODEL_PATH`
- `app/models/door_interior_yolov8.pt`

### 13.4 YOLO 有框，但颜色返回 None

优先看：

1. bbox 是否正确。
2. `lab_meta.lab_median`。
3. `lab_meta.distances`。
4. `lab_meta.selected_dist`。
5. `COLOR_DIST_THRESHOLD`。
6. `color_prototype` 数据。
7. 现场光照、曝光和白平衡。

### 13.5 检测与 PR 不一致

按以下链路逐层排查：

```text
standard.pr.raw
→ standard.pr.items
→ standard.pr.mapping_debug
→ standard.features
→ detected / aggregated.features
→ compare_result
→ overall
```

不要只看最终 `overall`。

---

## 14. 新增检测零件时需要修改的位置

当前代码已经预留多 feature 架构，但真正新增零件需要同步维护多个层次。

### 14.1 YOLO 模型

重训模型并增加新的 class，例如：

- seat
- dashboard
- steering_wheel

### 14.2 YOLO class 到业务 feature 的映射

修改 `app/config.py` 中的 `YOLO_FEATURE_CLASS_MAP`。

例如：

```text
door_trim_color → panel_color
seat_color      → seat
```

### 14.3 Feature Registry

修改：

```text
app/domain/feature_registry.py
```

定义：

- feature 名
- allowed 值
- mandatory 是否影响 overall

### 14.4 PR 标准规则

修改：

```text
app/resources/pr_rules.yaml
```

让 PR 能映射到新增 feature 的标准值。

### 14.5 属性判定逻辑

如果新增 feature 仍是颜色属性，需要增加对应 Prototype。

如果新增 feature 不是颜色，例如：

- 有/无
- 车型
- 装配状态
- 零件型号

则不应强行复用 Lab 分类，应为该 feature 单独设计后处理逻辑。

### 14.6 Android 展示

后端数据结构已使用 Map，可以承载多个 feature，但 Android UI 仍需要检查：

- MainScreen.kt
- SessionResultCard.kt
- SessionDtos.kt

---

## 15. 当前已知问题与技术债

以下内容建议接手后优先确认。

### P0：颜色 Prototype 存在“部分覆盖默认值”的风险

当前逻辑是：

```text
数据库中只要存在任意 prototype
    ↓
整个 feature 都只使用数据库 prototype
    ↓
不再使用默认 prototype
```

例如数据库中只有：

```text
door_trim_color / panel_black
```

那么 grey 和 yellow 的默认 prototype 可能不会参与本次分类。

建议修改为：

```text
完整默认 Prototype
    +
数据库中已有 label 逐项覆盖
    =
最终 Prototype
```

这是当前最值得优先修复的逻辑问题之一。

### P1：Android DTO 与后端 v2 响应存在协议漂移

目前至少有以下差异：

1. 后端 `label_votes` 是置信度累加，值实际为浮点数；Android 定义为 `Map<String, Int>`。
2. Android `FinishSessionResponse` 定义了 `status` 和 `standard`，但当前 finish API 的直接返回没有完整返回这两个字段。
3. 后端推理元信息字段为 `_meta`，Android DTO 定义为 `meta`。
4. Android `StartSessionResponse` 定义 `standard_available`，但后端当前未明确返回。

建议后续固定 API Contract，最好增加 OpenAPI 或自动化接口测试，避免两端手工维护继续漂移。

### P1：根目录 README 已过时

README 当前仍描述：

- 10 秒倒计时
- 后置拍摄后再前置拍摄

当前 `MainViewModel.kt` 实际为：

- 5 秒倒计时
- 连续 8 帧
- 帧间隔 700 ms
- 始终使用后置摄像头

维护时以当前代码和本文为准，后续建议同步更新 README。

### P1：LES_MODE 没有正式进入 BaseConfig

`les_client.py` 会读取 `LES_MODE`，并支持：

- http
- soap_pr_only
- auto

但当前 `BaseConfig` 没有定义 `LES_MODE`。

因此仅在系统环境中设置 `LES_MODE`，不会自动被当前 `from_object` 配置方式加载，代码通常仍走默认 `http`。

如果现场需要 `soap_pr_only` 或 `auto`，应先把 `LES_MODE` 加入 `app/config.py`。

### P1：requirements.txt 不完整

当前实际代码直接使用但 requirements.txt 未完整固定的关键依赖包括：

- ultralytics
- opencv-python / opencv-python-headless
- numpy
- PyYAML

另外 `requests` 在 requirements 中重复。

建议交接后补齐并固定版本，保证服务器可以复现安装环境。

### P2：在线校准存在长期漂移风险

当前在线校准没有：

- 样本质量门槛
- 最大更新步长
- Prototype 版本
- 回滚机制
- 管理页面
- 校准失败日志

长期生产建议至少增加：

- 最低 YOLO 置信度
- 最大 Lab 偏移限制
- Prototype 版本记录
- 人工重置/回滚
- 各颜色样本数监控

### P2：默认 SQLite 只适合轻量运行

当前默认使用 SQLite。

如果后续出现：

- 多手机同时检测
- 多进程 WSGI
- 长期大量历史记录
- 后台统计查询

建议切换 PostgreSQL/MySQL，并重新验证唯一约束和并发幂等。

### P2：上传图片没有生命周期管理

`uploads/YYYYMMDD/` 会持续增加。

当前未见：

- 自动清理
- 定期归档
- 磁盘水位告警
- 对象存储

现场必须明确图片保存周期。

### P2：VIN 校验较宽松

当前后端主要只检查 VIN 非空，Android 也没有严格 17 位校验。

是否增加严格校验需要先确认现场是否存在测试 VIN、短码或非标准码。

### P2：仓库包含较多生成物和数据文件

当前仓库中存在：

- `android/.gradle`
- `android/app/build`
- APK
- datasets

这些会明显增大仓库体积，也会干扰新同事查看代码。

建议后续清理已经被 Git 跟踪的构建产物，并评估训练数据是否应放到独立数据存储。

### P2：生产安全配置仍偏开发状态

需要注意：

- `SECRET_KEY` 默认 `dev-secret`
- `run.py` 强制 `debug=True`
- Android 允许明文 HTTP
- 当前 API 未看到鉴权
- 内网 WSDL 默认地址直接存在代码默认配置中

如果仅部署于封闭产线内网，可以按现场安全规范处理；如果跨网段或外部访问，应单独加固。

---

## 16. 推荐接手阅读顺序

第一次接手建议按以下顺序看，不要先钻 datasets 或 Android build 目录：

1. README.md
2. PROJECT_HANDOVER.md
3. app/__init__.py
4. app/api/v2.py
5. app/services/standard_service.py
6. app/services/pr_mapping.py
7. app/services/inference_service_v2.py
8. app/services/aggregation_service.py
9. app/services/compare_service.py
10. app/models/inspection_session.py
11. app/repositories/session_repo.py
12. app/resources/pr_rules.yaml
13. android/app/src/main/java/com/interior/detection/ui/MainViewModel.kt
14. android/app/src/main/java/com/interior/detection/data/api/InspectionApi.kt
15. scripts/v2-selftest.ps1

看完这些文件基本可以掌握整个主流程。

---

## 17. 建议现场交接演示内容

交接时建议至少实际演示一次：

1. 启动 Flask。
2. health 正常。
3. 使用 Mock 标准跑一遍 v2 self-test。
4. 查看 `inspection_session` 和 `inspection_frame`。
5. 展示一辆车的 PR 原始值和 `mapping_debug`。
6. 展示一帧 YOLO bbox。
7. 展示 Lab distances 和 selected_dist。
8. 展示 8 帧 `label_votes`。
9. 展示 `compare_result` 和 `overall`。
10. Android 真机扫描 VIN。
11. 真机完成 8 帧自动拍摄。
12. 修改 `API_BASE_URL` 并重新打包 APK。
13. 演示替换 YOLO 模型的位置。
14. 演示修改 `pr_rules.yaml` 的位置。

---

## 18. 接手后建议优先处理清单

```text
P0  修复 DB Prototype 与默认 Prototype 的合并逻辑

P1  统一 Android / Flask v2 API Contract
P1  补齐 requirements.txt
P1  把 LES_MODE 加入 BaseConfig
P1  更新 README 到当前 v2 8 帧流程

P2  增加自动化 Python API 测试
P2  增加 Prototype 管理、版本和回滚
P2  增加上传图片清理策略
P2  清理已跟踪的 Android build/.gradle 生成物
P2  根据并发量评估 SQLite → PostgreSQL/MySQL
P2  补充生产 WSGI、日志、服务守护和监控配置
```

---

## 19. 一句话理解项目

当前系统可以概括为：

**Android 采集 VIN 和连续多帧图片；Flask 后端先通过 LES/PR 获取门板颜色标准，再用 YOLOv8 定位门内饰条、使用 Lab Prototype 完成颜色分类，通过多帧加权聚合与标准配置比对，最终输出 OK/NG，并保存完整 Session 和帧级检测记录。**

后续扩展建议保持当前分层：

```text
API
 ↓
Service
 ↓
Repository / Model
```

不要把新增零件的判断逻辑直接堆进 API 层。