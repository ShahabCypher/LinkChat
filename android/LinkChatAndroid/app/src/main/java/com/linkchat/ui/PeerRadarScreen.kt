package com.linkchat.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.Block
import androidx.compose.material.icons.filled.SignalCellularAlt
import androidx.compose.material.icons.filled.VerifiedUser
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Badge
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.linkchat.model.PeerModel

@Composable
fun PeerRadarScreen(
    peers: List<PeerModel>,
    unreadCounts: Map<String, Int>,
    blockedTags: Set<String>,
    onOpenDm: (PeerModel) -> Unit,
    onOpenVerify: (PeerModel) -> Unit,
    onToggleBlockTag: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    if (peers.isEmpty()) {
        Box(
            modifier = modifier
                .fillMaxSize()
                .padding(24.dp),
            contentAlignment = Alignment.Center,
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(
                    text = "Scanning BLE Mesh...",
                    style = MaterialTheme.typography.titleMedium,
                    color = LinkChatColors.TextPrimary,
                )
                Spacer(modifier = Modifier.size(6.dp))
                Text(
                    text = "Nearby Android and Windows LinkChat nodes will appear here automatically.",
                    style = MaterialTheme.typography.bodySmall,
                    color = LinkChatColors.TextMuted,
                )
            }
        }
        return
    }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(peers, key = { it.nodeIdHex }) { peer ->
            val unread = unreadCounts[peer.nodeIdHex] ?: 0
            val isBlocked = blockedTags.contains(peer.shortTag.lowercase())
            PeerCard(
                peer = peer,
                unreadCount = unread,
                isBlocked = isBlocked,
                onOpenDm = { onOpenDm(peer) },
                onOpenVerify = { onOpenVerify(peer) },
                onToggleBlock = { onToggleBlockTag(peer.shortTag) },
            )
        }
    }
}

@Composable
private fun PeerCard(
    peer: PeerModel,
    unreadCount: Int,
    isBlocked: Boolean,
    onOpenDm: () -> Unit,
    onOpenVerify: () -> Unit,
    onToggleBlock: () -> Unit,
) {
    Card(
        colors = CardDefaults.cardColors(containerColor = LinkChatColors.BgCard),
        shape = RoundedCornerShape(14.dp),
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onOpenDm),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(contentAlignment = Alignment.BottomEnd) {
                Box(
                    modifier = Modifier
                        .size(44.dp)
                        .clip(CircleShape)
                        .background(LinkChatColors.AccentCyan.copy(alpha = 0.18f)),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = peer.nickname.take(2).uppercase().ifBlank { "LC" },
                        fontWeight = FontWeight.Bold,
                        color = LinkChatColors.AccentCyan,
                    )
                }
                Box(
                    modifier = Modifier
                        .size(12.dp)
                        .clip(CircleShape)
                        .background(
                            if (peer.connected) LinkChatColors.VerifiedGreen
                            else LinkChatColors.TextMuted
                        ),
                )
            }

            Spacer(modifier = Modifier.width(12.dp))

            Column(modifier = Modifier.weight(1f)) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(
                        text = peer.nickname.ifBlank { "LC-${peer.shortTag}" },
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold,
                        color = LinkChatColors.TextPrimary,
                    )
                    Text(
                        text = "LC-${peer.shortTag}",
                        style = MaterialTheme.typography.labelSmall,
                        fontFamily = FontFamily.Monospace,
                        color = LinkChatColors.TextMuted,
                    )
                    if (unreadCount > 0) {
                        Badge(containerColor = LinkChatColors.AccentCyan) {
                            Text("$unreadCount", color = LinkChatColors.BgRoot)
                        }
                    }
                }

                Spacer(modifier = Modifier.size(4.dp))

                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    val hopLabel = when {
                        !peer.connected -> "Offline"
                        peer.direct -> "Direct"
                        else -> "${peer.hopCount} hops"
                    }
                    val hopColor = when {
                        !peer.connected -> LinkChatColors.TextMuted
                        peer.direct -> LinkChatColors.VerifiedGreen
                        else -> LinkChatColors.AccentCyan
                    }
                    Pill(text = hopLabel, color = hopColor)

                    if (peer.connected && peer.direct) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(
                                imageVector = Icons.Default.SignalCellularAlt,
                                contentDescription = null,
                                tint = LinkChatColors.TextMuted,
                                modifier = Modifier.size(13.dp),
                            )
                            Text(
                                text = " ${peer.rssi} dBm",
                                style = MaterialTheme.typography.labelSmall,
                                color = LinkChatColors.TextMuted,
                            )
                        }
                    }

                    if (peer.keyChanged) {
                        Pill(text = "Key Changed!", color = LinkChatColors.DangerRed)
                    }

                    if (isBlocked) {
                        Pill(text = "Blocked", color = LinkChatColors.WarningAmber)
                    }
                }
            }

            IconButton(onClick = onOpenVerify) {
                Icon(
                    imageVector = if (peer.keyChanged) Icons.Default.Warning else Icons.Default.VerifiedUser,
                    contentDescription = "Verify Safety Number",
                    tint = when {
                        peer.keyChanged -> LinkChatColors.DangerRed
                        peer.verified -> LinkChatColors.VerifiedGreen
                        else -> LinkChatColors.TextMuted
                    },
                )
            }
            IconButton(onClick = onToggleBlock) {
                Icon(
                    imageVector = Icons.Default.Block,
                    contentDescription = "Toggle Debug Tag Block",
                    tint = if (isBlocked) LinkChatColors.WarningAmber else LinkChatColors.TextMuted.copy(alpha = 0.6f),
                )
            }
            IconButton(onClick = onOpenDm) {
                Icon(
                    imageVector = Icons.AutoMirrored.Filled.Chat,
                    contentDescription = "Open Encrypted DM",
                    tint = LinkChatColors.AccentCyan,
                )
            }
        }
    }
}

@Composable
private fun Pill(text: String, color: Color) {
    Surface(
        color = color.copy(alpha = 0.16f),
        shape = RoundedCornerShape(6.dp),
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelSmall,
            color = color,
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
        )
    }
}
