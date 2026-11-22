package com.linkchat

import android.Manifest
import com.linkchat.ble.BleTieBreaker
import com.linkchat.ble.LinkChatGattProfile
import com.linkchat.model.BleStatus
import com.linkchat.model.PeerModel
import com.linkchat.model.PermissionHelper
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TieBreakerAndModelsTest {

    @Test
    fun gattProfileUuidsMatchProjectSpec() {
        assertEquals("7b4e1000-8f2a-4c3b-9d1e-4c696e6b4368", LinkChatGattProfile.SERVICE_UUID.toString())
        assertEquals("7b4e1001-8f2a-4c3b-9d1e-4c696e6b4368", LinkChatGattProfile.RX_CHAR_UUID.toString())
        assertEquals("7b4e1002-8f2a-4c3b-9d1e-4c696e6b4368", LinkChatGattProfile.TX_CHAR_UUID.toString())
        assertEquals("00002902-0000-1000-8000-00805f9b34fb", LinkChatGattProfile.CCCD_UUID.toString())
    }

    @Test
    fun parseLinkChatTagAndDeterministicTieBreaker() {
        assertEquals("1a2b", BleTieBreaker.parseLinkChatTag("LC-1a2b"))
        assertEquals("ffff", BleTieBreaker.parseLinkChatTag("LC-FFFF"))
        assertNull(BleTieBreaker.parseLinkChatTag("LC-xyz1"))
        assertNull(BleTieBreaker.parseLinkChatTag("Windows-PC"))
        assertNull(BleTieBreaker.parseLinkChatTag(null))

        assertTrue(BleTieBreaker.shouldInitiateCentral("5000", "LC-9000"))
        assertFalse(BleTieBreaker.shouldInitiateCentral("5000", "LC-1000"))
        assertTrue(BleTieBreaker.shouldInitiateCentral("5000", "LC-5000"))
        assertTrue(BleTieBreaker.shouldInitiateCentral("5000", "Windows-PC"))
    }

    @Test
    fun peerModelDefaultsAndBlockedFlag() {
        val peer = PeerModel(
            nodeIdHex = "a1b2c3d4e5f60708",
            shortTag = "a1b2",
            nickname = "Alice",
            hopCount = 1,
            rssi = -55,
            direct = true,
            connected = true,
            verified = false,
            keyChanged = false,
            lastSeen = 100.0,
        )
        assertFalse(peer.blocked)
        assertTrue(peer.copy(blocked = true).blocked)
    }

    @Test
    fun permissionHelperCoversAndroidVersions() {
        val api30 = PermissionHelper.requiredBleServicePermissions(30)
        assertEquals(listOf(Manifest.permission.ACCESS_FINE_LOCATION), api30)

        val api31 = PermissionHelper.requiredBleServicePermissions(31)
        assertEquals(
            listOf(
                Manifest.permission.BLUETOOTH_SCAN,
                Manifest.permission.BLUETOOTH_ADVERTISE,
                Manifest.permission.BLUETOOTH_CONNECT,
            ),
            api31,
        )

        val api33All = PermissionHelper.allStartupPermissions(33)
        assertTrue(api33All.contains(Manifest.permission.POST_NOTIFICATIONS))
        assertTrue(api33All.contains(Manifest.permission.BLUETOOTH_CONNECT))
    }

    @Test
    fun bleStatusTotalLinks() {
        val status = BleStatus(centralLinks = 2, peripheralLinks = 1)
        assertEquals(3, status.totalLinks)
    }
}
