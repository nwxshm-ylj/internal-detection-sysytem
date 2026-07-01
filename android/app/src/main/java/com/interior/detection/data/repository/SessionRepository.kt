package com.interior.detection.data.repository

import com.interior.detection.data.api.RetrofitClient
import com.interior.detection.data.model.ApiResponse
import com.interior.detection.data.model.FinishSessionResponse
import com.interior.detection.data.model.FrameUploadResponse
import com.interior.detection.data.model.SessionDetail
import com.interior.detection.data.model.StartSessionRequest
import com.interior.detection.data.model.StartSessionResponse
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody

/**
 * v2 会话仓储：封装 session 全生命周期
 *  start → uploadFrame*N → finish → getDetail
 */
class SessionRepository {

    private val api = RetrofitClient.api

    suspend fun start(
        vin: String,
        clientSessionId: String
    ): ApiResponse<StartSessionResponse> {
        return api.startSession(StartSessionRequest(vin, clientSessionId))
    }

    suspend fun uploadFrame(
        sessionId: Int,
        frameIndex: Int,
        jpegBytes: ByteArray,
        fileName: String = "frame_$frameIndex.jpg"
    ): ApiResponse<FrameUploadResponse> {
        val frameIndexBody = frameIndex.toString()
            .toRequestBody("text/plain".toMediaType())
        val imagePart = MultipartBody.Part.createFormData(
            "image",
            fileName,
            jpegBytes.toRequestBody("image/jpeg".toMediaType())
        )
        return api.uploadFrame(sessionId, frameIndexBody, imagePart)
    }

    suspend fun finish(sessionId: Int): ApiResponse<FinishSessionResponse> {
        return api.finishSession(sessionId)
    }

    suspend fun detail(sessionId: Int): ApiResponse<SessionDetail> {
        return api.getSession(sessionId)
    }
}