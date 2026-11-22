package com.linkchat.model

data class PeerModel(
    val nodeIdHex: String,
    val shortTag: String,
    val nickname: String,
    val hopCount: Int,
    val rssi: Int,
    val direct: Boolean,
    val connected: Boolean,
    val verified: Boolean,
    val keyChanged: Boolean,
    val lastSeen: Double,
    val linkHandle: String? = null,
    val blocked: Boolean = false,
)

data class MessageModel(
    val msgId: String,
    val channel: String,
    val originId: String,
    val targetId: String,
    val senderNick: String,
    val text: String,
    val timestampMs: Long,
    val isOutgoing: Boolean,
    val status: String,
    val hopCount: Int,
)

data class LogEntryModel(
    val timestampMs: Long,
    val eventType: String,
    val message: String,
    val pktType: String = "",
    val msgId: String = "",
    val originId: String = "",
    val targetId: String = "",
    val hop: Int = 0,
    val ttl: Int = 0,
)

data class FingerprintModel(
    val nodeIdHex: String,
    val safetyNumber: String,
    val emojiHash: String,
    val groups: List<String>,
    val emojis: List<String>,
)

enum class BleStatusKind {
    IDLE,
    MISSING_PERMISSIONS,
    BLUETOOTH_OFF,
    DUAL_ROLE,
    CENTRAL_ONLY,
    ADV_ERROR,
    RESETTING,
    STOPPED,
}

data class BleStatus(
    val serviceRunning: Boolean = false,
    val advertising: Boolean = false,
    val scanning: Boolean = false,
    val centralLinks: Int = 0,
    val peripheralLinks: Int = 0,
    val bluetoothEnabled: Boolean = true,
    val statusNote: String = "Idle",
    val statusKind: BleStatusKind = BleStatusKind.IDLE,
    val errorCode: Int? = null,
) {
    val totalLinks: Int get() = centralLinks + peripheralLinks
}

enum class MainTab {
    PUBLIC,
    PEERS,
    INSPECTOR,
}
