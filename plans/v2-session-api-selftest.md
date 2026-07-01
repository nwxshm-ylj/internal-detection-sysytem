# V2 多帧会话 API 自测说明

> 适用版本：v2 阶段一骨架
> 目标：用最少的外部依赖（curl + 一两张图）端到端跑通
> `/api/v2/session/start` → 多次 `/frame` → `/finish` → `/session/<id>` 完整流程

---

## 1. 前置准备

### 1.1 启动服务

```bash
cd d:\CursorProjects\InteriorDetection
.venv\Scripts\python.exe -m flask run
```

默认监听 `http://127.0.0.1:5000`，下文 `BASE` 即此地址。

### 1.2 准备一张测试图

任意 jpg/png 即可，建议放项目根目录以便引用。例如：

```
d:\CursorProjects\InteriorDetection\test_data\sample_panel.jpg
```

> 当前骨架使用项目内已有的 YOLO 模型（`YOLO_MODEL_PATH`）。
> 如果模型尚未加载或样本图无目标，识别结果可能为空——这不影响流程自测。

### 1.3 确认数据库已升级

v2 表已通过迁移脚本落地：

```bash
.venv\Scripts\python.exe -m flask db current
# 应输出 a1e8244ddc81 (head)
```

如未升级：

```bash
.venv\Scripts\python.exe -m flask db upgrade
```

---

## 2. 端到端自测脚本（PowerShell）

下方脚本在 PowerShell 下可直接复制粘贴运行（Windows 11 默认 shell）：

```powershell
$BASE   = "http://127.0.0.1:5000"
$VIN    = "LSVNV2180G2123456"        # 17 位示例 VIN
$CLIENT = "selftest-001"            # APP 侧会话 id（幂等 key 之一）
$IMG    = "test_data\sample_panel.jpg"

# 2.1 健康检查
curl.exe "$BASE/api/v2/health"

# 2.2 创建会话
$SESSION_ID = curl.exe -s -X POST "$BASE/api/v2/session/start" `
    -H "Content-Type: application/json" `
    -d "{`"vin`":`"$VIN`",`"client_session_id`":`"$CLIENT`"}" `
    | python -c "import sys,json;print(json.load(sys.stdin)['session_id'])"

Write-Host "==> session_id = $SESSION_ID"

# 2.3 上传第 1 帧
curl.exe -X POST "$BASE/api/v2/session/$SESSION_ID/frame" `
    -F "frame_index=0" `
    -F "image=@$IMG"

# 2.4 上传第 2 帧
curl.exe -X POST "$BASE/api/v2/session/$SESSION_ID/frame" `
    -F "frame_index=1" `
    -F "image=@$IMG"

# 2.5 结束会话（触发聚合 + 比对）
curl.exe -X POST "$BASE/api/v2/session/$SESSION_ID/finish"

# 2.6 拉取完整结果
curl.exe "$BASE/api/v2/session/$SESSION_ID"
```

成功后第 2.6 步会返回：

```json
{
  "session_id": 1,
  "vin": "LSVNV2180G2123456",
  "status": "FINISHED",
  "overall": "OK" | "NG" | "UNKNOWN",
  "standard": { "door_trim_color": { "standard_label": "panel_black", ... } },
  "aggregated": {
    "door_trim_color": {
      "label": "panel_black",
      "confidence": 0.83,
      "frame_count": 2,
      "unanimous": true,
      "inlier_ratio": 1.0
    }
  },
  "compare": {
    "door_trim_color": { "expected": "panel_black", "actual": "panel_black", "result": "OK" }
  },
  "frames": [...]
}
```

---

## 3. 边界场景

### 3.1 幂等：重复 start 同一 (vin, client_session_id)

```powershell
# 第二次 start 返回已有 session_id，不会创建新记录
curl.exe -X POST "$BASE/api/v2/session/start" `
    -H "Content-Type: application/json" `
    -d "{`"vin`":`"$VIN`",`"client_session_id`":`"$CLIENT`"}"
```

### 3.2 幂等：重复上传同一 frame_index

```powershell
# 已存在的 frame_index 会复用记录，覆盖 detected_json，不会插入重复行
curl.exe -X POST "$BASE/api/v2/session/$SESSION_ID/frame" `
    -F "frame_index=0" `
    -F "image=@$IMG"
```

### 3.3 finish 后再上传帧

```powershell
# 应返回 4xx，状态不可逆
curl.exe -X POST "$BASE/api/v2/session/$SESSION_ID/frame" `
    -F "frame_index=2" -F "image=@$IMG"
```

预期：`400` / `409`，提示 session 已结束。

### 3.4 空帧数 finish

```powershell
# 仅 start + finish（不上传任何 frame）：返回 overall=UNKNOWN，compare 为空
curl.exe -X POST "$BASE/api/v2/session/empty-test/start" `
    -H "Content-Type: application/json" `
    -d "{`"vin`":`"EMPTYVIN000000000`",`"client_session_id`":`"empty-001`"}"
```

---

## 4. 常见失败排查

| 现象                                | 可能原因                              | 处置                            |
|-------------------------------------|---------------------------------------|---------------------------------|
| `500 / KeyError: yolo_model`        | `YOLO_MODEL_PATH` 未配置或文件不存在  | 检查 `.env` 中 `YOLO_MODEL_PATH`|
| 帧上传 `400 invalid image`          | 未传 `image` 字段或 MIME 非图像       | `-F "image=@xxx.jpg"` 形式      |
| finish 后 `overall=UNKNOWN`         | 至少有一个 feature 未在任何帧命中      | 检查 YOLO 类名 → feature 映射   |
| 比对结果都是 `NG`                   | 标准配置读取失败 / VIN 解析异常       | 检查 LES / PR 配置 mock 数据    |

---

## 5. 下一步（待你确认事项落地后补充）

- 多 feature 验收用例（按用户提供的零件清单）
- 视频/连续帧采集方案 A/B/C 接入后的批量端点
- NG 阈值与一致率下限的产品化参数