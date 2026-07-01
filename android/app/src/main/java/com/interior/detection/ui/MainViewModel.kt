package com.interior.detection.ui

import android.graphics.Bitmap
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.interior.detection.data.model.AggregatedEnvelope
import com.interior.detection.data.model.CompareItem
import com.interior.detection.data.model.FrameFeatureResult
import com.interior.detection.data.repository.SessionRepository
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.io.ByteArrayOutputStream
import java.util.UUID

/**
 * v2 多帧会话流程：
 *   扫码 → start_session → 倒计时 → 连续拍 N 帧（每帧上传） → finish → 显示聚合结果
 */
enum class FlowStep {
    IDLE,             // 等待开始
    SCANNING,         // 扫码中
    VIN_READY,        // VIN 已就绪
    STARTING_SESSION, // 调用 start_session
    COUNTDOWN,        // 倒计时
    CAPTURING,        // 正在拍摄第 N 帧
    UPLOADING,        // 正在上传第 N 帧
    FINISHING,        // 调用 finish
    DONE,             // 完成
    ERROR             // 出错
}

data class MainUiState(
    val step: FlowStep = FlowStep.IDLE,
    val vin: String = "",
    val countdown: Int = 0,
    val statusText: String = "等待开始",

    // 会话相关
    val sessionId: Int? = null,
    val totalFrames: Int = DEFAULT_TOTAL_FRAMES,
    val currentFrameIndex: Int = 0,           // 即将/正在处理的帧序号 [0..totalFrames)
    val perFramePreview: List<FrameFeatureResult?> = emptyList(),

    // 聚合结果（finish 后填充）
    val overall: String? = null,
    val aggregated: AggregatedEnvelope? = null,
    val compare: Map<String, CompareItem>? = null,

    val errorMsg: String? = null,
    /** 始终用后置；保留字段以兼容 CameraPreview 接口 */
    val useBackCamera: Boolean = true,
    /** 请求拍照的信号；CameraPreview 监听到非 null 即拍一张 */
    val captureRequest: String? = null
) {
    val progressText: String
        get() = if (totalFrames > 0) "$currentFrameIndex / $totalFrames" else "-"
}

class MainViewModel : ViewModel() {

    private val repo = SessionRepository()

    private val _ui = MutableStateFlow(MainUiState())
    val ui: StateFlow<MainUiState> = _ui.asStateFlow()

    /** 当前流程的客户端会话 id，用于幂等 */
    private var clientSessionId: String = ""

    // ---------------- 扫码 / VIN ----------------
    fun onBarcodeScan(barcode: String) {
        val vin = barcode.trim()
        if (vin.isEmpty()) return
        _ui.value = _ui.value.copy(
            vin = vin,
            step = FlowStep.VIN_READY,
            statusText = "VIN 已识别: $vin"
        )
    }

    fun onVinInput(vin: String) {
        _ui.value = _ui.value.copy(vin = vin)
    }

    fun startScanning() {
        _ui.value = _ui.value.copy(
            step = FlowStep.SCANNING,
            statusText = "扫码中…"
        )
    }

    fun confirmVin() {
        val vin = _ui.value.vin.trim()
        if (vin.isEmpty()) return
        _ui.value = _ui.value.copy(
            vin = vin,
            step = FlowStep.VIN_READY,
            statusText = "VIN 已确认: $vin"
        )
    }

    // ---------------- 主流程 ----------------
    fun startAutoFlow() {
        val vin = _ui.value.vin.trim()
        if (vin.isEmpty()) return

        clientSessionId = UUID.randomUUID().toString()

        viewModelScope.launch {
            try {
                // 1) 创建会话
                _ui.value = _ui.value.copy(
                    step = FlowStep.STARTING_SESSION,
                    statusText = "正在创建检测会话…",
                    sessionId = null,
                    overall = null,
                    aggregated = null,
                    compare = null,
                    perFramePreview = List(DEFAULT_TOTAL_FRAMES) { null },
                    currentFrameIndex = 0,
                    errorMsg = null
                )

                val startResp = repo.start(vin, clientSessionId)
                if (startResp.code != 200 || startResp.data == null) {
                    failFlow(startResp.msg.ifBlank { "创建会话失败" })
                    return@launch
                }
                val sid = startResp.data.sessionId
                _ui.value = _ui.value.copy(
                    sessionId = sid,
                    statusText = "会话已创建 #$sid，准备拍摄"
                )

                // 2) 倒计时
                for (i in COUNTDOWN_SECONDS downTo 1) {
                    _ui.value = _ui.value.copy(
                        step = FlowStep.COUNTDOWN,
                        countdown = i,
                        statusText = "倒计时 ${i}s，请缓慢移动手机覆盖待检零件"
                    )
                    delay(1000)
                }

                // 3) 触发首帧拍摄；后续帧由 onPhotoCaptured 链式驱动
                requestCapture(0)
            } catch (e: Exception) {
                failFlow(e.message ?: "未知错误")
            }
        }
    }

    /** 触发第 frameIndex 帧拍摄 */
    private fun requestCapture(frameIndex: Int) {
        _ui.value = _ui.value.copy(
            step = FlowStep.CAPTURING,
            currentFrameIndex = frameIndex,
            statusText = "拍摄第 ${frameIndex + 1} / ${_ui.value.totalFrames} 帧…",
            // 用 frame index 当 signal，确保每帧都触发 LaunchedEffect
            captureRequest = "frame_$frameIndex"
        )
    }

    // ---------------- 拍照完成 ----------------
    fun onPhotoCaptured(bitmap: Bitmap) {
        val current = _ui.value
        if (current.step != FlowStep.CAPTURING) return

        val sid = current.sessionId ?: run {
            failFlow("会话不存在")
            return
        }
        val frameIndex = current.currentFrameIndex
        val total = current.totalFrames

        viewModelScope.launch {
            try {
                val jpegBytes = bitmapToJpeg(bitmap)

                _ui.value = _ui.value.copy(
                    step = FlowStep.UPLOADING,
                    statusText = "上传第 ${frameIndex + 1} / $total 帧…",
                    captureRequest = null
                )

                val resp = repo.uploadFrame(sid, frameIndex, jpegBytes)
                if (resp.code != 200 || resp.data == null) {
                    failFlow(resp.msg.ifBlank { "第 ${frameIndex + 1} 帧上传失败" })
                    return@launch
                }

                // 把这一帧的预览结果合并进列表（取 detected.features 第一个值作为简略预览）
                val previewItem: FrameFeatureResult? = resp.data.detected
                    ?.features?.values?.firstOrNull()
                val newPreview = current.perFramePreview.toMutableList().apply {
                    while (size <= frameIndex) add(null)
                    this[frameIndex] = previewItem
                }
                _ui.value = _ui.value.copy(perFramePreview = newPreview)

                val nextIndex = frameIndex + 1
                if (nextIndex < total) {
                    // 帧间隔，给用户时间换角度
                    delay(FRAME_INTERVAL_MS)
                    requestCapture(nextIndex)
                } else {
                    // 全部拍完 → finish
                    finishSession(sid)
                }
            } catch (e: Exception) {
                failFlow(e.message ?: "上传异常")
            }
        }
    }

    private suspend fun finishSession(sessionId: Int) {
        _ui.value = _ui.value.copy(
            step = FlowStep.FINISHING,
            statusText = "正在汇总检测结果…",
            captureRequest = null
        )
        val resp = repo.finish(sessionId)
        if (resp.code != 200 || resp.data == null) {
            failFlow(resp.msg.ifBlank { "结束会话失败" })
            return
        }
        val d = resp.data
        _ui.value = _ui.value.copy(
            step = FlowStep.DONE,
            overall = d.overall,
            aggregated = d.aggregated,
            compare = d.compare,
            statusText = when (d.overall) {
                "OK" -> "检测完成：合格"
                "NG" -> "检测完成：不合格"
                else -> "检测完成：结果未定"
            }
        )
    }

    private fun failFlow(msg: String) {
        _ui.value = _ui.value.copy(
            step = FlowStep.ERROR,
            errorMsg = msg,
            statusText = "流程失败",
            captureRequest = null
        )
    }

    fun consumeCaptureRequest() {
        // 不立即清空：信号字符串会随 frameIndex 变化触发，这里只在异常时调用
        _ui.value = _ui.value.copy(captureRequest = null)
    }

    fun reset() {
        _ui.value = MainUiState()
        clientSessionId = ""
    }

    private fun bitmapToJpeg(bitmap: Bitmap, quality: Int = 85): ByteArray {
        val bos = ByteArrayOutputStream()
        bitmap.compress(Bitmap.CompressFormat.JPEG, quality, bos)
        return bos.toByteArray()
    }

    companion object {
        /** 默认连续拍摄帧数；用户提供采集方案后可调 */
        const val DEFAULT_TOTAL_FRAMES = 8

        /** 帧间隔，给用户旋转手机的时间 */
        const val FRAME_INTERVAL_MS = 700L

        /** 开始前的倒计时秒数 */
        const val COUNTDOWN_SECONDS = 5
    }
}