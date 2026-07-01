# =============================================================
# v2 多帧会话 API 一键自测脚本 (PowerShell / Windows)
# 用法: 在 PowerShell 中执行
#   cd d:\CursorProjects\InteriorDetection
#   .\scripts\v2-selftest.ps1
# 可选参数:
#   -BaseUrl   后端地址，默认 http://127.0.0.1:5000
#   -Vin       测试用 VIN，默认 LSVNV2180G2123456
#   -ClientId  幂等 key，默认 selftest-001
#   -Image     测试图路径，默认 test_data\sample_panel.jpg
#   -Frames    拍摄帧数，默认 8（与 APP 保持一致）
#   -Python    Python 可执行文件路径，默认 .venv\Scripts\python.exe
# =============================================================

param(
    [string]$BaseUrl  = "http://127.0.0.1:5000",
    [string]$Vin      = "LSVNV2180G2123456",
    [string]$ClientId = "selftest-001",
    [string]$Image    = "test_data\sample_panel.jpg",
    [int]$Frames      = 8,
    [string]$Python   = ".venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Write-Ok($msg) {
    Write-Host "  [OK] $msg" -ForegroundColor Green
}

function Write-Fail($msg) {
    Write-Host "  [FAIL] $msg" -ForegroundColor Red
}

function Jget($path, $key) {
    # 从 stdbuf 管道提取 JSON 字段；用 Python 做 JSON 解析保证正确
    $py = @"
import sys, json
try:
    data = json.load(sys.stdin)
except Exception as e:
    print('__PARSE_ERROR__:' + str(e))
    sys.exit(0)
keys = "$key".split('.')
cur = data
for k in keys:
    if isinstance(cur, dict) and k in cur:
        cur = cur[k]
    else:
        print('')
        sys.exit(0)
print(cur if cur is not None else '')
"@
    return $path | & $Python -c $py
}

# -------------------- 0. 前置检查 --------------------
Write-Step "0. 前置检查"

if (-not (Test-Path $Python)) {
    Write-Fail "找不到 Python: $Python  (请先创建 .venv 或通过 -Python 指定)"
    exit 1
}
Write-Ok "Python: $Python"

if (-not (Test-Path $Image)) {
    Write-Fail "找不到测试图: $Image"
    Write-Host "        请先放一张 jpg/png 到该路径，或通过 -Image 指定" -ForegroundColor Yellow
    exit 1
}
Write-Ok "测试图: $Image (大小 $((Get-Item $Image).Length) bytes)"

Write-Step "0.1 数据库迁移状态"
& $Python -m flask db current
if ($LASTEXITCODE -ne 0) {
    Write-Fail "数据库迁移检查失败 (exit=$LASTEXITCODE)"
    exit 1
}
Write-Ok "数据库迁移 OK"

# -------------------- 1. 健康检查 --------------------
Write-Step "1. 健康检查 $BaseUrl/api/v2/health"
$health = curl.exe -s "$BaseUrl/api/v2/health"
Write-Host "    $health"
if ($health -notmatch '"status":"up"') {
    Write-Fail "后端未启动或 health 不正常，请先执行："
    Write-Host "        $Python -m flask run --host=0.0.0.0 --port=5000" -ForegroundColor Yellow
    exit 1
}
Write-Ok "后端在线"

# -------------------- 2. 创建会话 --------------------
Write-Step "2. 创建会话  vin=$Vin  client=$ClientId"
$startBody = "{`"vin`":`"$Vin`",`"client_session_id`":`"$ClientId`"}"
$startResp = curl.exe -s -X POST "$BaseUrl/api/v2/session/start" `
    -H "Content-Type: application/json" `
    -d $startBody

Write-Host "    响应: $startResp"
$sessionId = Jget $startResp "data.session_id"
if ([string]::IsNullOrEmpty($sessionId)) {
    Write-Fail "未能从 start 响应中解析 session_id"
    exit 1
}
Write-Ok "session_id = $sessionId"

# 幂等检测
if ($startResp -match '"idempotent_hit":true') {
    Write-Host "    注意：命中已有会话 (idempotent_hit=true)" -ForegroundColor Yellow
}

# -------------------- 3. 上传 N 帧 --------------------
Write-Step "3. 上传 $Frames 帧"
for ($i = 0; $i -lt $Frames; $i++) {
    $frameResp = curl.exe -s -X POST "$BaseUrl/api/v2/session/$sessionId/frame" `
        -F "frame_index=$i" `
        -F "image=@$Image"

    # 提取首个 feature label（如果有）作实时预览
    $preview = Jget $frameResp "data.detected.features"
    $firstFeat = ""
    if (-not [string]::IsNullOrEmpty($preview)) {
        # preview 是 dict 字面量字符串，简单取第一个 key:value
        if ($preview -match '"([^"]+)":\s*\{[^}]*"label":\s*"([^"]+)"') {
            $firstFeat = "$($Matches[1])=$($Matches[2])"
        }
    }
    $idem = if ($frameResp -match '"idempotent_hit":true') { "(幂等)" } else { "" }
    Write-Host "    帧 $i : $firstFeat $idem"
}
Write-Ok "$Frames 帧上传完成"

# -------------------- 4. 结束会话 --------------------
Write-Step "4. 触发 finish（聚合 + 比对）"
$finishResp = curl.exe -s -X POST "$BaseUrl/api/v2/session/$sessionId/finish"
Write-Host "    响应: $finishResp"

$overall = Jget $finishResp "data.overall"
$frameCount = Jget $finishResp "data.frame_count"
if ([string]::IsNullOrEmpty($overall)) {
    Write-Fail "未能从 finish 响应中解析 overall"
    exit 1
}

$overallColor = switch ($overall.ToUpper()) {
    "OK"   { "Green" }
    "NG"   { "Red" }
    default { "Yellow" }
}
Write-Host "    overall    = $overall" -ForegroundColor $overallColor
Write-Host "    frame_count= $frameCount" -ForegroundColor Cyan
Write-Ok "finish 成功"

# -------------------- 5. 拉详情 --------------------
Write-Step "5. 拉取完整会话详情"
$detail = curl.exe -s "$BaseUrl/api/v2/session/$sessionId"
Write-Host "    响应: $detail"

# 打印关键字段汇总
$std  = Jget $detail "data.standard"
$agg  = Jget $detail "data.aggregated"
$cmp  = Jget $detail "data.compare_result"
Write-Host ""
Write-Host "    standard        : $std"
Write-Host "    aggregated      : $agg"
Write-Host "    compare_result  : $cmp"

# -------------------- 6. 边界场景 --------------------
Write-Step "6. 边界场景 - 重复 start (幂等)"
$start2 = curl.exe -s -X POST "$BaseUrl/api/v2/session/start" `
    -H "Content-Type: application/json" `
    -d $startBody
$id2 = Jget $start2 "data.session_id"
if ($id2 -eq $sessionId) {
    Write-Ok "幂等 OK：返回相同 session_id=$id2"
} else {
    Write-Fail "幂等失败：首次=$sessionId  二次=$id2"
}

Write-Step "7. 边界场景 - finish 后再 upload (应 409)"
$lateResp = curl.exe -s -w "`nHTTP_STATUS=%{http_code}" -X POST `
    "$BaseUrl/api/v2/session/$sessionId/frame" `
    -F "frame_index=999" -F "image=@$Image"
Write-Host "    $lateResp"
if ($lateResp -match "HTTP_STATUS=409") {
    Write-Ok "边界 OK：状态不可逆，返回 409"
} else {
    Write-Host "    注意：返回码不是 409，请确认业务行为" -ForegroundColor Yellow
}

# -------------------- 收尾 --------------------
Write-Step "全部完成 ✅"
Write-Host "  session_id  = $sessionId" -ForegroundColor Cyan
Write-Host "  overall     = $overall" -ForegroundColor $overallColor
Write-Host ""
Write-Host "如需查看完整会话 JSON，再次执行：" -ForegroundColor Gray
Write-Host "  curl.exe `"$BaseUrl/api/v2/session/$sessionId`"" -ForegroundColor Gray