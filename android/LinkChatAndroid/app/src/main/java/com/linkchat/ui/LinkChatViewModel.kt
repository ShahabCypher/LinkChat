package com.linkchat.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.linkchat.LinkChatApplication
import com.linkchat.model.BleStatus
import com.linkchat.model.FingerprintModel
import com.linkchat.model.LogEntryModel
import com.linkchat.model.MainTab
import com.linkchat.model.MessageModel
import com.linkchat.model.PeerModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn

data class VerifyDialogState(
    val peer: PeerModel,
    val fingerprint: FingerprintModel? = null,
    val loading: Boolean = true,
    val error: String? = null,
)

data class LinkChatUiState(
    val isReady: Boolean = false,
    val ownNodeId: String = "",
    val shortTag: String = "----",
    val nickname: String = "Android",
    val bleStatus: BleStatus = BleStatus(),
    val peers: List<PeerModel> = emptyList(),
    val activeTab: MainTab = MainTab.PUBLIC,
    val activeDmPeerId: String? = null,
    val messagesByChannel: Map<String, List<MessageModel>> = emptyMap(),
    val unreadCounts: Map<String, Int> = emptyMap(),
    val meshLogs: List<LogEntryModel> = emptyList(),
    val verifyState: VerifyDialogState? = null,
    val lastError: String? = null,
    val language: AppLanguage = AppLanguage.DEFAULT,
) {
    val activeChannel: String
        get() = activeDmPeerId ?: "#public"

    val activeMessages: List<MessageModel>
        get() = messagesByChannel[activeChannel].orEmpty()

    val activeDmPeer: PeerModel?
        get() = activeDmPeerId?.let { id -> peers.firstOrNull { it.nodeIdHex == id } }

    val totalUnreadDm: Int
        get() = unreadCounts.filterKeys { it != "#public" }.values.sum()
}

class LinkChatViewModel(application: Application) : AndroidViewModel(application) {

    private val app = application as LinkChatApplication
    private val bridge = app.pythonBridge

    private val activeTab = MutableStateFlow(MainTab.PUBLIC)
    private val activeDmPeerId = MutableStateFlow<String?>(null)
    private val verifyState = MutableStateFlow<VerifyDialogState?>(null)

    private val corePart = combine(
        bridge.isReady,
        bridge.ownNodeId,
        bridge.shortTag,
        bridge.nickname,
        bridge.peers,
    ) { ready, ownId, tag, nick, peersMap ->
        CorePart(ready, ownId, tag, nick, peersMap)
    }

    private val chatPart = combine(
        bridge.messages,
        bridge.unreadCounts,
        bridge.meshLogs,
        bridge.lastError,
        app.bleStatus,
    ) { msgs, unread, logs, err, ble ->
        ChatPart(msgs, unread, logs, err, ble)
    }

    private val navPart = combine(
        activeTab,
        activeDmPeerId,
        verifyState,
        app.language,
    ) { tab, dmId, verify, lang ->
        NavPart(tab, dmId, verify, lang)
    }

    val uiState: StateFlow<LinkChatUiState> = combine(
        corePart,
        chatPart,
        navPart,
    ) { core, chat, nav ->
        val sortedPeers = core.peersMap.values.sortedWith(
            compareByDescending<PeerModel> { it.connected }
                .thenByDescending { it.direct }
                .thenBy { it.hopCount }
                .thenBy { it.nickname.lowercase() }
        )
        val refreshedVerify = nav.verify?.let { vs ->
            val updatedPeer = core.peersMap[vs.peer.nodeIdHex] ?: vs.peer
            vs.copy(peer = updatedPeer)
        }
        LinkChatUiState(
            isReady = core.ready,
            ownNodeId = core.ownId,
            shortTag = core.tag.ifBlank { "----" },
            nickname = core.nick,
            bleStatus = chat.ble,
            peers = sortedPeers,
            activeTab = nav.tab,
            activeDmPeerId = nav.dmId,
            messagesByChannel = chat.msgs,
            unreadCounts = chat.unread,
            meshLogs = chat.logs,
            verifyState = refreshedVerify,
            lastError = chat.err,
            language = nav.lang,
        )
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5_000),
        initialValue = LinkChatUiState(),
    )

    fun selectTab(tab: MainTab) {
        activeDmPeerId.value = null
        activeTab.value = tab
        if (tab == MainTab.PUBLIC) {
            bridge.markChannelRead("#public")
        } else {
            bridge.activeChannel = ""
        }
    }

    fun openDm(peerIdHex: String) {
        activeDmPeerId.value = peerIdHex
        bridge.loadHistoryIfNeeded(peerIdHex)
        bridge.markChannelRead(peerIdHex)
    }

    fun closeDm() {
        activeDmPeerId.value = null
        if (activeTab.value == MainTab.PUBLIC) {
            bridge.markChannelRead("#public")
        } else {
            bridge.activeChannel = ""
        }
    }

    fun sendMessage(text: String) {
        val dmTarget = activeDmPeerId.value
        if (dmTarget != null) {
            bridge.sendDm(dmTarget, text)
        } else {
            bridge.sendPublic(text)
        }
    }

    fun setNickname(nickname: String) {
        bridge.setNickname(nickname)
    }

    fun openVerifySheet(peer: PeerModel) {
        verifyState.value = VerifyDialogState(peer = peer, loading = true)
        bridge.requestSafetyFingerprint(peer.nodeIdHex) { result ->
            verifyState.value = result.fold(
                onSuccess = { fp ->
                    VerifyDialogState(peer = peer, fingerprint = fp, loading = false)
                },
                onFailure = { err ->
                    VerifyDialogState(peer = peer, loading = false, error = err.message)
                },
            )
        }
    }

    fun closeVerifySheet() {
        verifyState.value = null
    }

    fun verifyPeer(nodeIdHex: String, verified: Boolean) {
        bridge.verifyPeer(nodeIdHex, verified)
    }

    fun setPeerBlocked(nodeIdHex: String, blocked: Boolean) {
        bridge.setPeerBlocked(nodeIdHex, blocked)
    }

    fun clearLogs() {
        bridge.clearLogs()
    }

    fun dismissError() {
        bridge.clearError()
    }

    fun resetAllData() {
        activeDmPeerId.value = null
        activeTab.value = MainTab.PUBLIC
        verifyState.value = null
        app.resetAllData()
    }

    fun toggleLanguage() {
        app.toggleLanguage()
    }

    private data class CorePart(
        val ready: Boolean,
        val ownId: String,
        val tag: String,
        val nick: String,
        val peersMap: Map<String, PeerModel>,
    )

    private data class ChatPart(
        val msgs: Map<String, List<MessageModel>>,
        val unread: Map<String, Int>,
        val logs: List<LogEntryModel>,
        val err: String?,
        val ble: BleStatus,
    )

    private data class NavPart(
        val tab: MainTab,
        val dmId: String?,
        val verify: VerifyDialogState?,
        val lang: AppLanguage,
    )
}
