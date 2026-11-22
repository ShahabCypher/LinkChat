package com.linkchat.ui

import androidx.compose.foundation.background
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
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.VerifiedUser
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextDirection
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.linkchat.model.MessageModel
import com.linkchat.model.PeerModel
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun ChatScreen(
    messages: List<MessageModel>,
    dmPeer: PeerModel?,
    onSendMessage: (String) -> Unit,
    onOpenVerify: (PeerModel) -> Unit,
    modifier: Modifier = Modifier,
) {
    val strings = LocalStrings.current
    val isRtl = LocalLayoutDirection.current == LayoutDirection.Rtl
    var draft by rememberSaveable(dmPeer?.nodeIdHex ?: "#public") { mutableStateOf("") }
    val listState = rememberLazyListState()

    LaunchedEffect(messages.size, dmPeer?.nodeIdHex) {
        if (messages.isNotEmpty()) {
            listState.animateScrollToItem(messages.lastIndex)
        }
    }

    Column(modifier = modifier.fillMaxSize()) {
        if (dmPeer != null) {
            DmEncryptionBanner(peer = dmPeer, onOpenVerify = { onOpenVerify(dmPeer) })
        }

        if (messages.isEmpty()) {
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(24.dp),
                contentAlignment = Alignment.Center,
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(
                        text = if (dmPeer == null) {
                            strings.emptyPublicTitle
                        } else {
                            strings.emptyDmTitle(dmPeer.nickname)
                        },
                        style = MaterialTheme.typography.titleMedium,
                        color = LinkChatColors.TextPrimary,
                    )
                    Spacer(modifier = Modifier.size(6.dp))
                    Text(
                        text = if (dmPeer == null) {
                            strings.emptyPublicDesc
                        } else {
                            strings.emptyDmDesc
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = LinkChatColors.TextMuted,
                    )
                }
            }
        } else {
            LazyColumn(
                state = listState,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                items(messages, key = { it.msgId }) { msg ->
                    MessageBubble(msg = msg, showSender = dmPeer == null)
                }
            }
        }

        Surface(
            color = LinkChatColors.BgPanel,
            tonalElevation = 2.dp,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OutlinedTextField(
                    value = draft,
                    onValueChange = { draft = it },
                    modifier = Modifier.weight(1f),
                    textStyle = MaterialTheme.typography.bodyLarge.copy(
                        textDirection = TextDirection.Content,
                        fontFamily = if (isRtl || draft.any { isPersianChar(it) }) {
                            VazirmatnFontFamily
                        } else {
                            null
                        },
                    ),
                    placeholder = {
                        Text(
                            text = if (dmPeer == null) {
                                strings.composerPublicPlaceholder
                            } else {
                                strings.composerDmPlaceholder(dmPeer.nickname)
                            },
                            color = LinkChatColors.TextMuted,
                        )
                    },
                    maxLines = 4,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                    keyboardActions = KeyboardActions(
                        onSend = {
                            if (draft.isNotBlank()) {
                                onSendMessage(draft)
                                draft = ""
                            }
                        }
                    ),
                    shape = RoundedCornerShape(20.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedContainerColor = LinkChatColors.BgInput,
                        unfocusedContainerColor = LinkChatColors.BgInput,
                        focusedBorderColor = LinkChatColors.AccentCyan,
                        unfocusedBorderColor = LinkChatColors.BorderSubtle,
                        focusedTextColor = LinkChatColors.TextPrimary,
                        unfocusedTextColor = LinkChatColors.TextPrimary,
                    ),
                )
                Spacer(modifier = Modifier.width(8.dp))
                FilledIconButton(
                    onClick = {
                        if (draft.isNotBlank()) {
                            onSendMessage(draft)
                            draft = ""
                        }
                    },
                    enabled = draft.isNotBlank(),
                    colors = IconButtonDefaults.filledIconButtonColors(
                        containerColor = LinkChatColors.AccentCyan,
                        contentColor = LinkChatColors.BgRoot,
                    ),
                ) {
                    Icon(Icons.AutoMirrored.Filled.Send, contentDescription = strings.send)
                }
            }
        }
    }
}

@Composable
private fun DmEncryptionBanner(
    peer: PeerModel,
    onOpenVerify: () -> Unit,
) {
    val strings = LocalStrings.current
    val bgColor = if (peer.keyChanged) {
        LinkChatColors.DangerRed.copy(alpha = 0.16f)
    } else {
        LinkChatColors.BgCard
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(bgColor)
            .padding(horizontal = 12.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = if (peer.keyChanged) Icons.Default.Warning else Icons.Default.Lock,
            contentDescription = null,
            tint = when {
                peer.keyChanged -> LinkChatColors.DangerRed
                peer.verified -> LinkChatColors.VerifiedGreen
                else -> LinkChatColors.AccentCyan
            },
            modifier = Modifier.size(16.dp),
        )
        Spacer(modifier = Modifier.width(8.dp))
        Text(
            text = when {
                peer.keyChanged -> styledBidiText(strings.keyChangedBanner(peer.nickname))
                peer.verified -> styledBidiText(strings.e2eeVerifiedBanner(peer.nickname, peer.shortTag))
                else -> styledBidiText(strings.e2eeActiveBanner)
            },
            style = MaterialTheme.typography.labelMedium,
            color = LinkChatColors.TextPrimary,
            modifier = Modifier.weight(1f),
        )
        TextButton(onClick = onOpenVerify) {
            Icon(
                imageVector = Icons.Default.VerifiedUser,
                contentDescription = null,
                modifier = Modifier.size(15.dp),
            )
            Spacer(modifier = Modifier.width(4.dp))
            Text(if (peer.verified) strings.verified else strings.verify)
        }
    }
}

@Composable
private fun MessageBubble(
    msg: MessageModel,
    showSender: Boolean,
) {
    val strings = LocalStrings.current
    val isRtl = LocalLayoutDirection.current == LayoutDirection.Rtl
    // Keep outgoing bubbles on the right and incoming bubbles on the left even in RTL mode.
    val align = if (isRtl) {
        if (msg.isOutgoing) Alignment.Start else Alignment.End
    } else {
        if (msg.isOutgoing) Alignment.End else Alignment.Start
    }
    val bubbleColor = if (msg.isOutgoing) {
        LinkChatColors.OutgoingBubble
    } else {
        LinkChatColors.IncomingBubble
    }
    val shape = if (isRtl) {
        if (msg.isOutgoing) {
            RoundedCornerShape(16.dp, 16.dp, 16.dp, 4.dp)
        } else {
            RoundedCornerShape(16.dp, 16.dp, 4.dp, 16.dp)
        }
    } else {
        if (msg.isOutgoing) {
            RoundedCornerShape(16.dp, 16.dp, 4.dp, 16.dp)
        } else {
            RoundedCornerShape(16.dp, 16.dp, 16.dp, 4.dp)
        }
    }

    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = align,
    ) {
        Surface(
            color = bubbleColor,
            shape = shape,
            modifier = Modifier.widthIn(max = 310.dp),
        ) {
            val headerMetaStyle = MaterialTheme.typography.labelSmall.copy(lineHeight = 14.sp)
            val footerStyle = MaterialTheme.typography.labelSmall.copy(
                fontSize = 10.sp,
                lineHeight = 12.sp,
            )

            Column(
                modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                if (!msg.isOutgoing && showSender) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        Text(
                            text = styledBidiText(msg.senderNick.ifBlank { msg.originId.take(4) }),
                            style = MaterialTheme.typography.labelMedium.copy(lineHeight = 14.sp),
                            fontWeight = FontWeight.SemiBold,
                            color = LinkChatColors.AccentCyan,
                        )
                        CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) {
                            Text(
                                text = "LC-${msg.originId.take(4)}",
                                style = headerMetaStyle,
                                fontFamily = FontFamily.Monospace,
                                color = LinkChatColors.TextMuted,
                            )
                        }
                        if (msg.hopCount > 0) {
                            Text(
                                text = if (msg.hopCount == 1) strings.msgDirectBadge else "• ${msg.hopCount}h",
                                style = headerMetaStyle,
                                color = LinkChatColors.TextMuted,
                            )
                        }
                    }
                }

                Text(
                    text = styledBidiText(msg.text),
                    style = MaterialTheme.typography.bodyMedium.copy(
                        lineHeight = 20.sp,
                        textDirection = TextDirection.Content,
                    ),
                    color = LinkChatColors.TextPrimary,
                )

                Row(
                    modifier = Modifier.align(Alignment.End),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(
                        text = formatTime(msg.timestampMs),
                        style = footerStyle,
                        color = LinkChatColors.TextMuted,
                    )
                    if (msg.isOutgoing && msg.channel != "#public") {
                        val (label, color) = when (msg.status) {
                            "delivered" -> strings.dmDelivered to LinkChatColors.VerifiedGreen
                            "relayed" -> strings.dmRelayed to LinkChatColors.WarningAmber
                            else -> strings.dmSending to LinkChatColors.TextMuted
                        }
                        Text(
                            text = label,
                            style = footerStyle,
                            fontWeight = FontWeight.Medium,
                            color = color,
                        )
                    }
                }
            }
        }
    }
}

private fun formatTime(timestampMs: Long): String {
    val fmt = SimpleDateFormat("HH:mm", Locale.US)
    return fmt.format(Date(timestampMs))
}
