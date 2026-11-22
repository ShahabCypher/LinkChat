package com.linkchat.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDirection
import com.linkchat.R

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

val VazirmatnFontFamily = FontFamily(
    Font(R.font.vazirmatn_regular, FontWeight.Normal),
    Font(R.font.vazirmatn_bold, FontWeight.Bold),
)

private val DefaultTypography = Typography()

private fun Typography.withFontFamily(family: FontFamily): Typography = Typography(
    displayLarge = displayLarge.copy(fontFamily = family),
    displayMedium = displayMedium.copy(fontFamily = family),
    displaySmall = displaySmall.copy(fontFamily = family),
    headlineLarge = headlineLarge.copy(fontFamily = family),
    headlineMedium = headlineMedium.copy(fontFamily = family),
    headlineSmall = headlineSmall.copy(fontFamily = family),
    titleLarge = titleLarge.copy(fontFamily = family),
    titleMedium = titleMedium.copy(fontFamily = family),
    titleSmall = titleSmall.copy(fontFamily = family),
    bodyLarge = bodyLarge.copy(fontFamily = family),
    bodyMedium = bodyMedium.copy(fontFamily = family),
    bodySmall = bodySmall.copy(fontFamily = family),
    labelLarge = labelLarge.copy(fontFamily = family),
    labelMedium = labelMedium.copy(fontFamily = family),
    labelSmall = labelSmall.copy(fontFamily = family),
)

private val PersianTypography = DefaultTypography.withFontFamily(VazirmatnFontFamily)

fun isPersianChar(ch: Char): Boolean {
    val code = ch.code
    return code in 0x0600..0x06FF ||
        code in 0x0750..0x077F ||
        code in 0x08A0..0x08FF ||
        code in 0xFB50..0xFDFF ||
        code in 0xFE70..0xFEFF
}

fun containsPersian(text: String): Boolean = text.any { isPersianChar(it) }

fun isRtlText(text: String, defaultRtl: Boolean = false): Boolean {
    if (containsPersian(text)) return true
    for (ch in text) {
        when (Character.getDirectionality(ch)) {
            Character.DIRECTIONALITY_RIGHT_TO_LEFT,
            Character.DIRECTIONALITY_RIGHT_TO_LEFT_ARABIC -> return true
            Character.DIRECTIONALITY_LEFT_TO_RIGHT -> return false
        }
    }
    return defaultRtl
}

fun textDirectionFor(text: String, defaultRtl: Boolean = false): TextDirection =
    if (isRtlText(text, defaultRtl)) TextDirection.Rtl else TextDirection.Ltr

fun styledBidiText(text: String): AnnotatedString {
    if (text.none { isPersianChar(it) }) {
        return AnnotatedString(text)
    }
    return buildAnnotatedString {
        append(text)
        var i = 0
        while (i < text.length) {
            if (isPersianChar(text[i])) {
                val start = i
                while (i < text.length && (isPersianChar(text[i]) || text[i] == ' ' || text[i] == '\u200C')) {
                    i++
                }
                addStyle(
                    style = SpanStyle(fontFamily = VazirmatnFontFamily),
                    start = start,
                    end = i,
                )
            } else {
                i++
            }
        }
    }
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
fun LinkChatTheme(
    isPersian: Boolean = true,
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = DarkScheme,
        typography = if (isPersian) PersianTypography else DefaultTypography,
        content = content,
    )
}
