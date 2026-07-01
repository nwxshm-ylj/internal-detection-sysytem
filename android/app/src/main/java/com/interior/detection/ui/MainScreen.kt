package com.interior.detection.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.interior.detection.ui.camera.BarcodeScannerView
import com.interior.detection.ui.camera.CameraPreview
import com.interior.detection.ui.components.SessionResultCard

@Composable
fun MainScreen(viewModel: MainViewModel) {
    val state by viewModel.ui.collectAsState()
    var showVinDialog by remember { mutableStateOf(false) }
    var pendingVin by remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFFF6F7F9))
    ) {
        // 顶部状态栏
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .background(Color.White)
                .padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "内饰检测 v2",
                fontWeight = FontWeight.Bold,
                fontSize = 18.sp
            )
            Spacer(Modifier.weight(1f))
            Text(
                text = state.statusText,
                fontSize = 13.sp,
                color = Color.Gray
            )
        }

        Column(
            modifier = Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState())
                .padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            // 相机预览区域
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(300.dp)
                    .clip(RoundedCornerShape(14.dp))
                    .background(Color.Black)
            ) {
                when (state.step) {
                    FlowStep.SCANNING -> {
                        BarcodeScannerView(
                            onBarcodeDetected = { barcode ->
                                pendingVin = barcode
                                showVinDialog = true
                            }
                        )
                        Text(
                            text = "将条码对准画面中央",
                            color = Color.White,
                            fontSize = 13.sp,
                            modifier = Modifier
                                .align(Alignment.BottomCenter)
                                .padding(bottom = 16.dp)
                                .background(
                                    Color(0x88111111),
                                    RoundedCornerShape(999.dp)
                                )
                                .padding(horizontal = 12.dp, vertical = 6.dp)
                        )
                    }

                    FlowStep.STARTING_SESSION,
                    FlowStep.COUNTDOWN,
                    FlowStep.CAPTURING,
                    FlowStep.UPLOADING,
                    FlowStep.FINISHING -> {
                        CameraPreview(
                            useBackCamera = state.useBackCamera,
                            captureSignal = state.captureRequest,
                            onPhotoCaptured = { bitmap ->
                                viewModel.onPhotoCaptured(bitmap)
                            },
                            onCaptureConsumed = {
                                viewModel.consumeCaptureRequest()
                            }
                        )

                        // 进度提示
                        Text(
                            text = "进度 ${state.progressText}",
                            color = Color.White,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.Bold,
                            modifier = Modifier
                                .align(Alignment.TopStart)
                                .padding(10.dp)
                                .background(
                                    Color(0x88111111),
                                    RoundedCornerShape(999.dp)
                                )
                                .padding(horizontal = 10.dp, vertical = 4.dp)
                        )

                        if (state.step == FlowStep.COUNTDOWN) {
                            Text(
                                text = "${state.countdown}",
                                color = Color.White,
                                fontSize = 64.sp,
                                fontWeight = FontWeight.ExtraBold,
                                modifier = Modifier.align(Alignment.Center)
                            )
                        }
                    }

                    else -> {
                        Box(
                            modifier = Modifier.fillMaxSize(),
                            contentAlignment = Alignment.Center
                        ) {
                            Text(
                                text = when (state.step) {
                                    FlowStep.DONE -> "检测完成"
                                    FlowStep.ERROR -> "出错了"
                                    else -> "点击下方按钮开始"
                                },
                                color = Color.White,
                                fontSize = 16.sp
                            )
                        }
                    }
                }
            }

            // 拍摄进度条（仅在多帧采集阶段显示）
            if (state.step == FlowStep.CAPTURING ||
                state.step == FlowStep.UPLOADING ||
                state.step == FlowStep.FINISHING
            ) {
                val total = state.totalFrames.coerceAtLeast(1)
                val done = state.currentFrameIndex + when (state.step) {
                    FlowStep.UPLOADING, FlowStep.FINISHING -> 1
                    else -> 0
                }
                LinearProgressIndicator(
                    progress = (done.toFloat() / total).coerceIn(0f, 1f),
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(6.dp)
                        .clip(RoundedCornerShape(3.dp))
                )
            }

            // VIN 输入区
            OutlinedTextField(
                value = state.vin,
                onValueChange = { viewModel.onVinInput(it) },
                label = { Text("VIN（扫码或手动输入）") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { viewModel.confirmVin() })
            )

            // 操作按钮
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Button(
                    onClick = { viewModel.startScanning() },
                    enabled = state.step == FlowStep.IDLE ||
                            state.step == FlowStep.VIN_READY ||
                            state.step == FlowStep.DONE ||
                            state.step == FlowStep.ERROR,
                    modifier = Modifier.weight(1f)
                ) {
                    Text("扫描条码")
                }

                Button(
                    onClick = { viewModel.startAutoFlow() },
                    enabled = state.step == FlowStep.VIN_READY,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = Color(0xFF1F6FEB)
                    ),
                    modifier = Modifier.weight(1f)
                ) {
                    Text("开始检测")
                }

                OutlinedButton(
                    onClick = { viewModel.reset() },
                    enabled = state.step != FlowStep.IDLE,
                    modifier = Modifier.weight(1f)
                ) {
                    Text("重置")
                }
            }

            // 流程说明
            Text(
                text = "流程：确认VIN → 创建会话 → 倒计时 → 连续拍 ${MainViewModel.DEFAULT_TOTAL_FRAMES} 帧 → 汇总结果",
                fontSize = 12.sp,
                color = Color.Gray
            )

            // 聚合结果卡片
            SessionResultCard(
                sessionId = state.sessionId,
                overall = state.overall,
                aggregated = state.aggregated,
                compare = state.compare
            )

            // 错误信息
            if (state.errorMsg != null) {
                Text(
                    text = "错误: ${state.errorMsg}",
                    color = Color(0xFFD64545),
                    fontSize = 13.sp,
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(Color(0xFFFFF0F0), RoundedCornerShape(8.dp))
                        .padding(12.dp)
                )
            }

            Spacer(Modifier.height(60.dp))
        }
    }

    // VIN 确认弹窗
    if (showVinDialog) {
        AlertDialog(
            onDismissRequest = { showVinDialog = false },
            title = { Text("确认 VIN") },
            text = {
                Column {
                    Text("扫码识别到：")
                    Text(
                        text = pendingVin,
                        fontWeight = FontWeight.ExtraBold,
                        fontSize = 18.sp,
                        modifier = Modifier.padding(top = 8.dp)
                    )
                    Text(
                        text = "确认后将创建检测会话，倒计时结束后开始连续拍摄多帧。",
                        fontSize = 13.sp,
                        color = Color.Gray,
                        modifier = Modifier.padding(top = 8.dp)
                    )
                }
            },
            confirmButton = {
                Button(onClick = {
                    showVinDialog = false
                    viewModel.onBarcodeScan(pendingVin)
                    viewModel.startAutoFlow()
                }) {
                    Text("确认并开始")
                }
            },
            dismissButton = {
                TextButton(onClick = { showVinDialog = false }) {
                    Text("取消")
                }
            }
        )
    }
}