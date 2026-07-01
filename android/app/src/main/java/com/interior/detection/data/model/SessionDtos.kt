package com.interior.detection.data.model

import com.google.gson.annotations.SerializedName

/**
 * 通用 API 响应包装
 * 后端 ok/fail 返回: {code, msg, data, trace_id}
 */
data class ApiResponse<T>(
    val code: Int,
    val msg: String?,
    val data: T?,
    @SerializedName("trace_id") val traceId: String? = null
)

/**
 * 健康检查响应
 */
data class HealthResponse(
    val status: String
)

/**
 * 比对结果条目
 */
data class CompareItem(
    val result: String?,
    val mandatory: Boolean?,
    val reason: String?,
    val standard: String?,
    val detected: String?,
    @SerializedName("standard_value") val standardValue: String? = null,
    @SerializedName("detected_value") val detectedValue: String? = null
)

/**
 * v2 会话接口的 DTO 定义
 * 对应后端 /api/v2/session/* 协议
 */

// ---------- POST /api/v2/session/start ----------
data class StartSessionRequest(
    val vin: String,
    @SerializedName("client_session_id") val clientSessionId: String
)

data class StartSessionResponse(
    @SerializedName("session_id") val sessionId: Int,
    val vin: String,
    @SerializedName("client_session_id") val clientSessionId: String,
    val status: String,
    @SerializedName("standard_available") val standardAvailable: Boolean = true,
    @SerializedName("idempotent_hit") val idempotentHit: Boolean = false
)

// ---------- POST /api/v2/session/<id>/frame ----------
// 后端返回：detected = { features: { feature: {label, conf, bbox, ...} }, meta: {...} }
data class FrameUploadResponse(
    @SerializedName("session_id") val sessionId: Int,
    @SerializedName("frame_index") val frameIndex: Int,
    @SerializedName("image_path") val imagePath: String? = null,
    @SerializedName("frame_id") val frameId: Int? = null,
    @SerializedName("idempotent_hit") val idempotentHit: Boolean? = null,
    val detected: DetectedEnvelope?
)

data class DetectedEnvelope(
    val features: Map<String, FrameFeatureResult>? = null,
    val meta: Map<String, Any>? = null
)

data class FrameFeatureResult(
    val label: String?,
    val conf: Double?,
    val bbox: List<Double>? = null
)

// ---------- POST /api/v2/session/<id>/finish ----------
// 后端实际返回：aggregated = { features: { feature: AggregatedFeature } , ... }
data class AggregatedEnvelope(
    val features: Map<String, AggregatedFeature>? = null
)

data class FinishSessionResponse(
    @SerializedName("session_id") val sessionId: Int,
    val status: String,
    val overall: String?,
    val standard: Map<String, Any>?,
    val aggregated: AggregatedEnvelope?,
    @SerializedName("compare_result") val compare: Map<String, CompareItem>?,
    @SerializedName("frame_count") val frameCount: Int
)

data class AggregatedFeature(
    val label: String?,
    val confidence: Double?,
    @SerializedName("frame_count") val frameCount: Int?,
    val unanimous: Boolean?,
    @SerializedName("inlier_ratio") val inlierRatio: Double?,
    @SerializedName("label_votes") val labelVotes: Map<String, Int>?
)

// ---------- GET /api/v2/session/<id> ----------
data class SessionDetail(
    @SerializedName("session_id") val sessionId: Int,
    val vin: String,
    @SerializedName("client_session_id") val clientSessionId: String,
    val status: String,
    val overall: String?,
    val standard: Map<String, Any>?,
    val aggregated: AggregatedEnvelope?,
    @SerializedName("compare_result") val compare: Map<String, CompareItem>?,
    @SerializedName("frame_count") val frameCount: Int,
    val frames: List<SessionFrameRef>?
)

data class SessionFrameRef(
    @SerializedName("frame_index") val frameIndex: Int,
    @SerializedName("image_path") val imagePath: String?,
    val detected: Map<String, Any>?,
    @SerializedName("created_at") val createdAt: String?
)