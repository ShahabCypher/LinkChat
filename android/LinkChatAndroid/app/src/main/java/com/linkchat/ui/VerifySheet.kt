package com.linkchat.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.VerifiedUser
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VerifySheet(
    state: VerifyDialogState,
    onDismiss: () -> Unit,
    onSetVerified: (String, Boolean) -> Unit,
) {
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        containerColor = LinkChatColors.BgPanel,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .padding(bottom = 28.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Icon(
                imageVector = if (state.peer.keyChanged) Icons.Default.Warning else Icons.Default.VerifiedUser,
                contentDescription = null,
                tint = when {
                    state.peer.keyChanged -> LinkChatColors.DangerRed
                    state.peer.verified -> LinkChatColors.VerifiedGreen
                    else -> LinkChatColors.AccentCyan
                },
                modifier = Modifier.size(36.dp),
            )
            Spacer(modifier = Modifier.size(8.dp))
            Text(
                text = "Safety Fingerprint • ${state.peer.nickname}",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                color = LinkChatColors.TextPrimary,
            )
            Text(
                text = state.peer.nodeIdHex,
                style = MaterialTheme.typography.labelMedium,
                fontFamily = FontFamily.Monospace,
                color = LinkChatColors.TextMuted,
            )

            if (state.peer.keyChanged) {
                Spacer(modifier = Modifier.size(12.dp))
                Surface(
                    color = LinkChatColors.DangerRed.copy(alpha = 0.16f),
                    shape = RoundedCornerShape(10.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        text = "Warning: this peer's identity key changed since last contact! Verify in person before trusting.",
                        style = MaterialTheme.typography.bodySmall,
                        color = LinkChatColors.DangerRed,
                        modifier = Modifier.padding(12.dp),
                    )
                }
            }

            Spacer(modifier = Modifier.size(16.dp))

            when {
                state.loading -> {
                    Box(modifier = Modifier.padding(24.dp), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(color = LinkChatColors.AccentCyan)
                    }
                }

                state.error != null -> {
                    Text(
                        text = "Could not compute fingerprint: ${state.error}",
                        color = LinkChatColors.DangerRed,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }

                state.fingerprint != null -> {
                    Text(
                        text = "Compare these 6 emojis & 30 digits with ${state.peer.nickname}:",
                        style = MaterialTheme.typography.bodySmall,
                        color = LinkChatColors.TextMuted,
                        textAlign = TextAlign.Center,
                    )
                    Spacer(modifier = Modifier.size(12.dp))

                    Surface(
                        color = LinkChatColors.BgCard,
                        shape = RoundedCornerShape(14.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 14.dp, horizontal = 8.dp),
                            horizontalArrangement = Arrangement.SpaceEvenly,
                        ) {
                            state.fingerprint.emojis.forEach { emoji ->
                                Text(text = emoji, fontSize = 28.sp)
                            }
                        }
                    }

                    Spacer(modifier = Modifier.size(12.dp))

                    Surface(
                        color = LinkChatColors.BgCard,
                        shape = RoundedCornerShape(14.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(14.dp),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            state.fingerprint.groups.chunked(3).forEach { rowGroups ->
                                Text(
                                    text = rowGroups.joinToString("   "),
                                    fontSize = 18.sp,
                                    fontFamily = FontFamily.Monospace,
                                    fontWeight = FontWeight.SemiBold,
                                    color = LinkChatColors.TextPrimary,
                                )
                            }
                        }
                    }

                    Spacer(modifier = Modifier.size(18.dp))

                    if (state.peer.verified) {
                        OutlinedButton(
                            onClick = { onSetVerified(state.peer.nodeIdHex, false) },
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text("Revoke Verification")
                        }
                    } else {
                        Button(
                            onClick = { onSetVerified(state.peer.nodeIdHex, true) },
                            modifier = Modifier.fillMaxWidth(),
                            colors = ButtonDefaults.buttonColors(
                                containerColor = LinkChatColors.VerifiedGreen,
                                contentColor = LinkChatColors.BgRoot,
                            ),
                        ) {
                            Text("Mark as Verified", fontWeight = FontWeight.Bold)
                        }
                    }
                }
            }
        }
    }
}
