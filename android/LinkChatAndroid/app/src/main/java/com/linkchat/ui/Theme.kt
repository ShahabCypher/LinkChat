package com.linkchat.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

object LinkChatColors {
    val BgRoot = Color(0xFF0B1117)
    val BgPanel = Color(0xFF111923)
    val BgCard = Color(0xFF172230)
    val BgInput = Color(0xFF1D2A3A)
    val BorderSubtle = Color(0xFF253549)

    val AccentCyan = Color(0xFF38BDF8)
    val AccentCyanDark = Color(0xFF0284C7)
    val VerifiedGreen = Color(0xFF22C55E)
    val WarningAmber = Color(0xFFF59E0B)
    val DangerRed = Color(0xFFEF4444)

    val TextPrimary = Color(0xFFF1F5F9)
    val TextMuted = Color(0xFF94A3B8)
    val OutgoingBubble = Color(0xFF0E4A6F)
    val IncomingBubble = Color(0xFF1A2636)
}

private val DarkScheme = darkColorScheme(
    primary = LinkChatColors.AccentCyan,
    onPrimary = LinkChatColors.BgRoot,
    primaryContainer = LinkChatColors.OutgoingBubble,
    onPrimaryContainer = LinkChatColors.TextPrimary,
    secondary = LinkChatColors.VerifiedGreen,
    onSecondary = LinkChatColors.BgRoot,
    background = LinkChatColors.BgRoot,
    onBackground = LinkChatColors.TextPrimary,
    surface = LinkChatColors.BgPanel,
    onSurface = LinkChatColors.TextPrimary,
    surfaceVariant = LinkChatColors.BgCard,
    onSurfaceVariant = LinkChatColors.TextMuted,
    outline = LinkChatColors.BorderSubtle,
    error = LinkChatColors.DangerRed,
    onError = Color.White,
)

@Composable
fun LinkChatTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkScheme,
        content = content,
    )
}
