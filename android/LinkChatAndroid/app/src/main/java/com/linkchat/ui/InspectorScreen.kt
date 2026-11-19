package com.linkchat.ui

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.linkchat.model.LogEntryModel
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun InspectorScreen(
    logs: List<LogEntryModel>,
    blockedTags: Set<String>,
    onToggleBlockedTag: (String) -> Unit,
    onClearLogs: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var selectedFilter by rememberSaveable { mutableStateOf("ALL") }
    var tagInput by rememberSaveable { mutableStateOf("") }

    val filters = listOf("ALL", "HELLO", "RELAY", "SYNC", "DM", "DROP")
    val filtered = if (selectedFilter == "ALL") {
        logs.asReversed()
    } else {
        logs.filter {
            it.eventType.contains(selectedFilter, ignoreCase = true) ||
                it.pktType.contains(selectedFilter, ignoreCase = true)
        }.asReversed()
    }

    Column(modifier = modifier.fillMaxSize()) {
        // Debug tag block filter for simulating physical multi-hop separation
        Surface(color = LinkChatColors.BgPanel, modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(
                        value = tagInput,
                        onValueChange = { if (it.length <= 4) tagInput = it },
                        label = { Text("Block LC tag (4-hex demo filter)") },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    OutlinedButton(
                        onClick = {
                            onToggleBlockedTag(tagInput)
                            tagInput = ""
                        },
                        enabled = tagInput.trim().length == 4,
                    ) {
                        Text("Toggle")
                    }
                    IconButton(onClick = onClearLogs) {
                        Icon(
                            Icons.Default.DeleteOutline,
                            contentDescription = "Clear Logs",
                            tint = LinkChatColors.TextMuted,
                        )
                    }
                }
                if (blockedTags.isNotEmpty()) {
                    Spacer(modifier = Modifier.size(6.dp))
                    Text(
                        text = "Blocked tags: ${blockedTags.joinToString { "LC-$it" }}",
                        style = MaterialTheme.typography.labelSmall,
                        color = LinkChatColors.WarningAmber,
                    )
                }
            }
        }

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState())
                .padding(horizontal = 12.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            filters.forEach { f ->
                FilterChip(
                    selected = selectedFilter == f,
                    onClick = { selectedFilter = f },
                    label = { Text(f) },
                )
            }
        }

        if (filtered.isEmpty()) {
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = "No mesh events recorded yet.",
                    color = LinkChatColors.TextMuted,
                )
            }
        } else {
            LazyColumn(
                modifier = Modifier.weight(1f),
                contentPadding = PaddingValues(12.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                items(filtered) { entry ->
                    LogRow(entry)
                }
            }
        }
    }
}

@Composable
private fun LogRow(entry: LogEntryModel) {
    val badgeColor = when {
        entry.eventType.contains("DROP", true) -> LinkChatColors.DangerRed
        entry.eventType.contains("RELAY", true) -> LinkChatColors.WarningAmber
        entry.eventType.contains("HELLO", true) -> LinkChatColors.VerifiedGreen
        else -> LinkChatColors.AccentCyan
    }
    Surface(
        color = LinkChatColors.BgCard,
        shape = RoundedCornerShape(10.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(10.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Surface(
                    color = badgeColor.copy(alpha = 0.16f),
                    shape = RoundedCornerShape(4.dp),
                ) {
                    Text(
                        text = entry.eventType,
                        fontSize = 10.sp,
                        fontWeight = FontWeight.Bold,
                        color = badgeColor,
                        modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
                    )
                }
                if (entry.pktType.isNotBlank()) {
                    Text(
                        text = entry.pktType,
                        fontSize = 11.sp,
                        fontFamily = FontFamily.Monospace,
                        color = LinkChatColors.TextMuted,
                    )
                }
                if (entry.ttl > 0 || entry.hop > 0) {
                    Text(
                        text = "hop=${entry.hop} ttl=${entry.ttl}",
                        fontSize = 11.sp,
                        fontFamily = FontFamily.Monospace,
                        color = LinkChatColors.TextMuted,
                    )
                }
                Spacer(modifier = Modifier.weight(1f))
                Text(
                    text = formatLogTime(entry.timestampMs),
                    fontSize = 10.sp,
                    fontFamily = FontFamily.Monospace,
                    color = LinkChatColors.TextMuted,
                )
            }
            Spacer(modifier = Modifier.size(4.dp))
            Text(
                text = entry.message,
                fontSize = 12.sp,
                fontFamily = FontFamily.Monospace,
                color = LinkChatColors.TextPrimary,
            )
        }
    }
}

private fun formatLogTime(ts: Long): String {
    return SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date(ts))
}
