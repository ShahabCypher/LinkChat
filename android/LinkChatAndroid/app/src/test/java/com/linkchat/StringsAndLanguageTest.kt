package com.linkchat

import androidx.compose.ui.text.style.TextDirection
import com.linkchat.model.BleStatus
import com.linkchat.model.BleStatusKind
import com.linkchat.ui.AppLanguage
import com.linkchat.ui.EnglishStrings
import com.linkchat.ui.PersianStrings
import com.linkchat.ui.containsPersian
import com.linkchat.ui.isPersianChar
import com.linkchat.ui.isRtlText
import com.linkchat.ui.stringsFor
import com.linkchat.ui.styledBidiText
import com.linkchat.ui.textDirectionFor
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class StringsAndLanguageTest {

    @Test
    fun defaultLanguageIsPersianAndRtl() {
        assertEquals(AppLanguage.FA, AppLanguage.DEFAULT)
        assertTrue(AppLanguage.FA.isRtl)
        assertFalse(AppLanguage.EN.isRtl)
        assertEquals(AppLanguage.FA, AppLanguage.fromCode(null))
        assertEquals(AppLanguage.FA, AppLanguage.fromCode("unknown"))
        assertEquals(AppLanguage.EN, AppLanguage.fromCode("en"))
        assertEquals(PersianStrings, stringsFor(AppLanguage.FA))
        assertEquals(EnglishStrings, stringsFor(AppLanguage.EN))
    }

    @Test
    fun publicChannelAndDigitsStayConsistent() {
        assertEquals("#public", PersianStrings.tabPublic)
        assertEquals("#public", EnglishStrings.tabPublic)
        assertEquals("لینک‌چت", PersianStrings.appName)
        assertEquals("LinkChat", EnglishStrings.appName)
        assertEquals("2 جهش", PersianStrings.hopsLabel(2))
        assertEquals("1 اتصال مستقیم", PersianStrings.notifDirectLinks(1))
        val advErr = BleStatus(statusKind = BleStatusKind.ADV_ERROR, errorCode = 18)
        assertTrue(PersianStrings.notifStatus(advErr).contains("18"))
        assertTrue(EnglishStrings.notifStatus(advErr).contains("18"))
    }

    @Test
    fun styledBidiTextSpansPersianRuns() {
        assertTrue(isPersianChar('س'))
        assertFalse(isPersianChar('A'))

        val englishOnly = styledBidiText("Hello #public")
        assertTrue(englishOnly.spanStyles.isEmpty())

        val mixed = styledBidiText("Hello سلام دنیا test")
        assertEquals(1, mixed.spanStyles.size)
        assertEquals("Hello سلام دنیا test", mixed.text)
    }

    @Test
    fun persianTextResolvesToRtlDirection() {
        assertTrue(containsPersian("نام:"))
        assertTrue(containsPersian("Hello سلام:"))
        assertFalse(containsPersian("Hello #public"))

        assertTrue(isRtlText("نام:", defaultRtl = false))
        assertTrue(isRtlText("Hello سلام:", defaultRtl = false))
        assertFalse(isRtlText("Hello world:", defaultRtl = true))
        assertTrue(isRtlText("123", defaultRtl = true))
        assertFalse(isRtlText("123", defaultRtl = false))

        assertEquals(TextDirection.Rtl, textDirectionFor("Hello سلام:", defaultRtl = false))
        assertEquals(TextDirection.Ltr, textDirectionFor("Hello world:", defaultRtl = true))
    }
}
