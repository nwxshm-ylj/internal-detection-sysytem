package com.interior.detection.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.interior.detection.data.model.AggregatedEnvelope
import com.interior.detection.data.model.AggregatedFeature
import com.interior.detection.data.model.CompareItem

private val okColor = Color(0xFF0A8F3D)
private val ngColor = Color(0xFFD64545)
private val warnColor = Color(0xFFB8860B)
private val idleColor = Color(0xFF6B7280)

/**
 * v2 会话级结果卡片：展示聚合后各零件颜色判定与最终 OK/NG
 */
@Composable
fun SessionResultCard(
    sessionId: Int?,
    overall: String?,
    aggregated: AggregatedEnvelope?,
    compare: Map<String, CompareItem>?,
    modifier: Modifier = Modifier
) {
    val features: Map<String, AggregatedFeature> = aggregated?.features ?: emptyMap()
    Card(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
    ) {
        Column(modifier = Modifier.padding(14.dp)) {

            // 顶部：标题 + overall 徽标
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "聚合检测结果",
                    fontWeight = FontWeight.Bold,
                    fontSize = 15.sp
                )

                val ov = overall?.uppercase()
                val badgeColor = when (ov) {
                    "OK" -> okColor
                    "NG" -> ngColor
                    else -> if (overall != null) warnColor else idleColor
                }
                val badgeText = when (ov) {
                    "OK" -> "OK"
                    "NG" -> "NG"
                    else -> if (overall == null) "等待" else overall
                }
                Text(
                    text = badgeText,
                    color = Color.White,
                    fontWeight = FontWeight.ExtraBold,
                    fontSize = 14.sp,
                    modifier = Modifier
                        .clip(RoundedCornerShape(999.dp))
                        .background(badgeColor)
                        .padding(horizontal = 12.dp, vertical = 6.dp)
                )
            }

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 6.dp)
            ) {
                Text(
                    text = "session #$sessionId",
                    fontSize = 12.sp,
                    color = Color.Gray
                )
            }

            // 各零件明细
            if (features.isNotEmpty()) {
                Column(modifier = Modifier.padding(top = 10.dp)) {
                    features.entries.forEach { (feature, agg) ->
                        FeatureRow(
                            feature = feature,
                            agg = agg,
                            compare = compare?.get(feature)
                        )
                    }
                }
            } else if (overall == null) {
                Text(
                    text = "尚未开始检测",
                    fontSize = 13.sp,
                    color = Color.Gray,
                    modifier = Modifier.padding(top = 10.dp)
                )
            }
        }
    }
}

@Composable
private fun FeatureRow(
    feature: String,
    agg: AggregatedFeature,
    compare: CompareItem?
) {
    val cr = compare?.result?.uppercase()
    val rowColor = when (cr) {
        "OK" -> Color(0xFFE7F6EC)
        "NG" -> Color(0xFFFCE7E7)
        else -> Color(0xFFF3F4F6)
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 6.dp)
            .clip(RoundedCornerShape(8.dp))
            .background(rowColor)
            .padding(10.dp)
    ) {
        Text(
            text = feature,
            fontWeight = FontWeight.Bold,
            fontSize = 13.sp
        )
        Text(
            text = buildString {
                append("识别: ")
                append(agg.label ?: "-")
                append("  置信度: ")
                append(String.format("%.2f", agg.confidence ?: 0.0))
                append("  帧数: ${agg.frameCount ?: 0}")
                if (agg.unanimous == true) append("  一致")
            },
            fontSize = 12.sp,
            modifier = Modifier.padding(top = 2.dp)
        )
        if (compare != null) {
            Text(
                text = "标准: ${compare.standard ?: "-"}  →  ${compare.result ?: "-"}  ${compare.reason ?: ""}",
                fontSize = 12.sp,
                color = Color.Gray,
                modifier = Modifier.padding(top = 2.dp)
            )
        }
    }
}