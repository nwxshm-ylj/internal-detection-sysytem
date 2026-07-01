package com.interior.detection.data.api

import com.interior.detection.data.model.ApiResponse
import com.interior.detection.data.model.FinishSessionResponse
import com.interior.detection.data.model.FrameUploadResponse
import com.interior.detection.data.model.HealthResponse
import com.interior.detection.data.model.SessionDetail
import com.interior.detection.data.model.StartSessionRequest
import com.interior.detection.data.model.StartSessionResponse
import okhttp3.MultipartBody
import okhttp3.RequestBody
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Path

interface InspectionApi {

    // ============== v2 会话多帧 ==============

    @GET("api/v2/health")
    suspend fun health(): ApiResponse<HealthResponse>

    @GET("api/v2/health")
    suspend fun healthV2(): ApiResponse<HealthResponse>

    @POST("api/v2/session/start")
    suspend fun startSession(@Body req: StartSessionRequest): ApiResponse<StartSessionResponse>

    @Multipart
    @POST("api/v2/session/{id}/frame")
    suspend fun uploadFrame(
        @Path("id") sessionId: Int,
        @Part("frame_index") frameIndex: RequestBody,
        @Part image: MultipartBody.Part
    ): ApiResponse<FrameUploadResponse>

    @POST("api/v2/session/{id}/finish")
    suspend fun finishSession(@Path("id") sessionId: Int): ApiResponse<FinishSessionResponse>

    @GET("api/v2/session/{id}")
    suspend fun getSession(@Path("id") sessionId: Int): ApiResponse<SessionDetail>
}
