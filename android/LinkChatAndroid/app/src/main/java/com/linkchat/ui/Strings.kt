package com.linkchat.ui

import androidx.compose.runtime.staticCompositionLocalOf
import com.linkchat.model.BleStatus
import com.linkchat.model.BleStatusKind

enum class AppLanguage(val code: String) {
    FA("fa"),
    EN("en");

    val isRtl: Boolean
        get() = this == FA

    companion object {
        val DEFAULT = FA

        fun fromCode(code: String?): AppLanguage =
            entries.firstOrNull { it.code == code } ?: DEFAULT
    }
}

data class AppStrings(
    val appName: String,
    val langToggleLabel: String,
    val back: String,
    val editNickname: String,
    val resetIdentity: String,
    val tabPublic: String,
    val tabPeers: String,
    val tabInspector: String,
    val blePermissions: String,
    val bleBtOff: String,
    val bleIdle: String,
    val blePermissionsBanner: String,
    val grant: String,
    val connectingPeers: String,
    val resetDialogTitle: String,
    val resetDialogBody: String,
    val wipeAndReset: String,
    val cancel: String,
    val changeNicknameTitle: String,
    val nicknameLabel: String,
    val save: String,
    val directLabel: String,
    val hopsLabel: (Int) -> String,
    val offlineLabel: String,
    val emptyPublicTitle: String,
    val emptyPublicDesc: String,
    val emptyDmTitle: (String) -> String,
    val emptyDmDesc: String,
    val composerPublicPlaceholder: String,
    val composerDmPlaceholder: (String) -> String,
    val send: String,
    val keyChangedBanner: (String) -> String,
    val e2eeVerifiedBanner: (String, String) -> String,
    val e2eeActiveBanner: String,
    val verified: String,
    val verify: String,
    val msgDirectBadge: String,
    val dmDelivered: String,
    val dmRelayed: String,
    val dmSending: String,
    val scanningBleMesh: String,
    val scanningBleDesc: String,
    val keyChangedPill: String,
    val unblock: String,
    val dmBlockedBanner: String,
    val composerDmBlockedPlaceholder: String,
    val verifySafetyNumber: String,
    val toggleBlockPeer: String,
    val openEncryptedDm: String,
    val clearLogs: String,
    val noMeshEvents: String,
    val safetyFingerprintTitle: (String) -> String,
    val verifyKeyChangedWarning: String,
    val fingerprintError: (String) -> String,
    val compareFingerprintsHint: (String) -> String,
    val revokeVerification: String,
    val markAsVerified: String,
    val notifTitle: String,
    val notifStarting: String,
    val notifStop: String,
    val notifDirectLinks: (Int) -> String,
    val notifStatus: (BleStatus) -> String,
)

val PersianStrings = AppStrings(
    appName = "لینک‌چت",
    langToggleLabel = "EN",
    back = "بازگشت",
    editNickname = "ویرایش نام",
    resetIdentity = "بازنشانی هویت",
    tabPublic = "#public",
    tabPeers = "همتایان",
    tabInspector = "تحلیلگر",
    blePermissions = "مجوزها",
    bleBtOff = "بلوتوث خاموش",
    bleIdle = "آماده",
    blePermissionsBanner = "برای کشف و بازپخش همتایان مش به مجوزهای بلوتوث نیاز است.",
    grant = "اعطا",
    connectingPeers = "در حال اتصال به همتایان نزدیک...",
    resetDialogTitle = "پاک کردن تمام داده‌ها و بازنشانی هویت؟",
    resetDialogBody = "این کار کلیدهای رمزنگاری، نام مستعار، همتایان، سوابق اعتماد، همتایان مسدودشده و تمام تاریخچه گفتگو را برای همیشه پاک می‌کند. به عنوان کاربر جدید به شبکه بازمی‌گردید.",
    wipeAndReset = "پاک کردن و بازنشانی",
    cancel = "انصراف",
    changeNicknameTitle = "تغییر نام مستعار نمایشی",
    nicknameLabel = "نام مستعار",
    save = "ذخیره",
    directLabel = "مستقیم",
    hopsLabel = { hops -> "$hops جهش" },
    offlineLabel = "آفلاین",
    emptyPublicTitle = "هنوز پیامی در #public نیست",
    emptyPublicDesc = "پیام‌های عمومی از طریق گره‌های بلوتوث ویندوز و اندروید نزدیک بازپخش می‌شوند.",
    emptyDmTitle = { nick -> "گفتگوی رمزنگاری‌شده با $nick" },
    emptyDmDesc = "پیام‌ها با X25519 + ChaCha20-Poly1305 به صورت سرتاسری رمزنگاری می‌شوند.",
    composerPublicPlaceholder = "پیام در شبکه #public...",
    composerDmPlaceholder = { nick -> "پیام رمزنگاری‌شده به $nick..." },
    send = "ارسال",
    keyChangedBanner = { nick -> "کلید $nick تغییر کرده است! شماره امنیتی را تایید کنید." },
    e2eeVerifiedBanner = { nick, tag -> "رمزنگاری تاییدشده • $nick (LC-$tag)" },
    e2eeActiveBanner = "رمزنگاری فعال • برای مقایسه ایموجی‌های امنیتی تایید را بزنید",
    verified = "تایید شده",
    verify = "تایید",
    msgDirectBadge = "• مستقیم",
    dmDelivered = "تحویل شد ✓✓",
    dmRelayed = "بازپخش شد ✓",
    dmSending = "در حال ارسال...",
    scanningBleMesh = "در حال اسکن شبکه بلوتوث...",
    scanningBleDesc = "گره‌های لینک‌چت اندروید و ویندوز نزدیک به صورت خودکار اینجا ظاهر می‌شوند.",
    keyChangedPill = "تغییر کلید!",
    unblock = "رفع مسدودیت",
    dmBlockedBanner = "شما این کاربر را مسدود کرده‌اید. برای ارسال یا دریافت پیام خصوصی مسدودیت را بردارید.",
    composerDmBlockedPlaceholder = "کاربر مسدود شده است — پیام خصوصی غیرفعال است",
    verifySafetyNumber = "تایید شماره امنیتی",
    toggleBlockPeer = "مسدود کردن یا رفع مسدودیت همتا",
    openEncryptedDm = "باز کردن پیام خصوصی رمزنگاری‌شده",
    clearLogs = "پاک کردن گزارش‌ها",
    noMeshEvents = "هنوز رویدادی در شبکه ثبت نشده است.",
    safetyFingerprintTitle = { nick -> "اثرانگشت امنیتی • $nick" },
    verifyKeyChangedWarning = "هشدار: کلید هویت این همتا از آخرین تماس تغییر کرده است! پیش از اعتماد حضوری تایید کنید.",
    fingerprintError = { err -> "محاسبه اثرانگشت ممکن نشد: $err" },
    compareFingerprintsHint = { nick -> "این 6 ایموجی و 30 رقم را با $nick مقایسه کنید:" },
    revokeVerification = "لغو تاییدیه",
    markAsVerified = "علامت‌گذاری به عنوان تاییدشده",
    notifTitle = "شبکه بلوتوث لینک‌چت",
    notifStarting = "در حال راه‌اندازی شبکه بلوتوث لینک‌چت...",
    notifStop = "توقف",
    notifDirectLinks = { links -> "$links اتصال مستقیم" },
    notifStatus = { status ->
        when (status.statusKind) {
            BleStatusKind.IDLE -> "آماده"
            BleStatusKind.MISSING_PERMISSIONS -> "نیازمند مجوز بلوتوث"
            BleStatusKind.BLUETOOTH_OFF -> "بلوتوث خاموش است"
            BleStatusKind.DUAL_ROLE,
            BleStatusKind.CENTRAL_ONLY -> "شبکه مش فعال"
            BleStatusKind.ADV_ERROR -> "شبکه مش فعال (خطای تبلیغ ${status.errorCode ?: 0})"
            BleStatusKind.RESETTING -> "در حال بازنشانی..."
            BleStatusKind.STOPPED -> "متوقف"
        }
    },
)

val EnglishStrings = AppStrings(
    appName = "LinkChat",
    langToggleLabel = "فارسی",
    back = "Back",
    editNickname = "Edit nickname",
    resetIdentity = "Reset Identity",
    tabPublic = "#public",
    tabPeers = "Peers",
    tabInspector = "Inspector",
    blePermissions = "Permissions",
    bleBtOff = "BT Off",
    bleIdle = "Idle",
    blePermissionsBanner = "Bluetooth permissions are needed to discover & relay mesh peers.",
    grant = "Grant",
    connectingPeers = "Connecting to nearby peers...",
    resetDialogTitle = "Erase All Data & Reset Identity?",
    resetDialogBody = "This permanently wipes your cryptographic keys, nickname, peers, trust records, blocked peers, and all chat history. You will rejoin the mesh as a brand-new user.",
    wipeAndReset = "Wipe & Reset",
    cancel = "Cancel",
    changeNicknameTitle = "Change Display Nickname",
    nicknameLabel = "Nickname",
    save = "Save",
    directLabel = "Direct",
    hopsLabel = { hops -> "$hops hops" },
    offlineLabel = "Offline",
    emptyPublicTitle = "No #public messages yet",
    emptyPublicDesc = "Broadcast messages relay across nearby Windows and Android BLE nodes.",
    emptyDmTitle = { nick -> "Encrypted chat with $nick" },
    emptyDmDesc = "Messages are end-to-end encrypted with X25519 + ChaCha20-Poly1305.",
    composerPublicPlaceholder = "Message #public mesh...",
    composerDmPlaceholder = { nick -> "Encrypted DM to $nick..." },
    send = "Send",
    keyChangedBanner = { nick -> "Key changed for $nick! Verify safety number." },
    e2eeVerifiedBanner = { nick, tag -> "E2EE Verified • $nick (LC-$tag)" },
    e2eeActiveBanner = "E2EE Active • Tap Verify to compare safety emojis",
    verified = "Verified",
    verify = "Verify",
    msgDirectBadge = "• direct",
    dmDelivered = "Delivered ✓✓",
    dmRelayed = "Relayed ✓",
    dmSending = "Sending...",
    scanningBleMesh = "Scanning BLE Mesh...",
    scanningBleDesc = "Nearby Android and Windows LinkChat nodes will appear here automatically.",
    keyChangedPill = "Key Changed!",
    unblock = "Unblock",
    dmBlockedBanner = "You blocked this user. Unblock to send or receive private messages.",
    composerDmBlockedPlaceholder = "User is blocked — private chat disabled",
    verifySafetyNumber = "Verify Safety Number",
    toggleBlockPeer = "Block or Unblock Peer",
    openEncryptedDm = "Open Encrypted DM",
    clearLogs = "Clear Logs",
    noMeshEvents = "No mesh events recorded yet.",
    safetyFingerprintTitle = { nick -> "Safety Fingerprint • $nick" },
    verifyKeyChangedWarning = "Warning: this peer's identity key changed since last contact! Verify in person before trusting.",
    fingerprintError = { err -> "Could not compute fingerprint: $err" },
    compareFingerprintsHint = { nick -> "Compare these 6 emojis & 30 digits with $nick:" },
    revokeVerification = "Revoke Verification",
    markAsVerified = "Mark as Verified",
    notifTitle = "LinkChat BLE Mesh",
    notifStarting = "Starting LinkChat BLE mesh...",
    notifStop = "Stop",
    notifDirectLinks = { links -> if (links == 1) "1 direct link" else "$links direct links" },
    notifStatus = { status ->
        when (status.statusKind) {
            BleStatusKind.IDLE -> "Idle"
            BleStatusKind.MISSING_PERMISSIONS -> "Missing BLE permissions"
            BleStatusKind.BLUETOOTH_OFF -> "Bluetooth is off"
            BleStatusKind.DUAL_ROLE,
            BleStatusKind.CENTRAL_ONLY -> "Mesh active"
            BleStatusKind.ADV_ERROR -> "Mesh active (adv err ${status.errorCode ?: 0})"
            BleStatusKind.RESETTING -> "Resetting..."
            BleStatusKind.STOPPED -> "Stopped"
        }
    },
)

fun stringsFor(language: AppLanguage): AppStrings =
    when (language) {
        AppLanguage.FA -> PersianStrings
        AppLanguage.EN -> EnglishStrings
    }

val LocalStrings = staticCompositionLocalOf { PersianStrings }
