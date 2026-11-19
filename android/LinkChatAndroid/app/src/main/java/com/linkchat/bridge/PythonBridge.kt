package com.linkchat.bridge

import android.content.Context
import android.util.Log
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import com.linkchat.model.FingerprintModel
import com.linkchat.model.LogEntryModel
import com.linkchat.model.MessageModel
import com.linkchat.model.PeerModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Thread-safe Kotlin <-> Chaquopy bridge.
 *
 * All Python bridge invocations are serialized onto a single dedicated executor
 * as required by PROJECT.md so Python core state stays consistent.
 */
class PythonBridge(private val context: Context) {

    interface ChunkSender {
        fun sendChunk(peerHandle: String, chunk: ByteArray)
    }

    private inner class TransportSink {
        @Suppress("unused") // Called from bridge.py via Chaquopy
        fun sendChunk(peerHandle: String, chunk: ByteArray) {
            chunkSender?.sendChunk(peerHandle, chunk)
        }
    }

    private inner class BridgeEventListener {
        @Suppress("unused") // Called from bridge.py via Chaquopy
        fun onEvent(eventJson: String) {
            handleEventJson(eventJson)
        }
    }

    private val executor: ExecutorService = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "linkchat-py-bridge").apply { isDaemon = true }
    }
    private val started = AtomicBoolean(false)

    @Volatile
    private var module: PyObject? = null

    @Volatile
    private var chunkSender: ChunkSender? = null

    private val _isReady = MutableStateFlow(false)
    val isReady: StateFlow<Boolean> = _isReady.asStateFlow()

    private val _ownNodeId = MutableStateFlow("")
    val ownNodeId: StateFlow<String> = _ownNodeId.asStateFlow()

    private val _shortTag = MutableStateFlow("")
    val shortTag: StateFlow<String> = _shortTag.asStateFlow()

    private val _nickname = MutableStateFlow("Android")
    val nickname: StateFlow<String> = _nickname.asStateFlow()

    private val _peers = MutableStateFlow<Map<String, PeerModel>>(emptyMap())
    val peers: StateFlow<Map<String, PeerModel>> = _peers.asStateFlow()

    private val _messages = MutableStateFlow<Map<String, List<MessageModel>>>(
        mapOf("#public" to emptyList())
    )
    val messages: StateFlow<Map<String, List<MessageModel>>> = _messages.asStateFlow()

    private val _unreadCounts = MutableStateFlow<Map<String, Int>>(emptyMap())
    val unreadCounts: StateFlow<Map<String, Int>> = _unreadCounts.asStateFlow()

    private val _meshLogs = MutableStateFlow<List<LogEntryModel>>(emptyList())
    val meshLogs: StateFlow<List<LogEntryModel>> = _meshLogs.asStateFlow()

    private val _lastError = MutableStateFlow<String?>(null)
    val lastError: StateFlow<String?> = _lastError.asStateFlow()

    private val loadedChannels = mutableSetOf("#public")

    @Volatile
    var activeChannel: String = "#public"

    fun setChunkSender(sender: ChunkSender?) {
        chunkSender = sender
    }

    fun start(initialNickname: String? = null, onReady: ((String) -> Unit)? = null) {
        executor.execute {
            try {
                if (!Python.isStarted()) {
                    Python.start(AndroidPlatform(context.applicationContext))
                }
                val py = Python.getInstance()
                val mod = py.getModule("bridge")
                module = mod

                if (started.compareAndSet(false, true)) {
                    val dataDir = context.filesDir.absolutePath
                    val readyJson = mod.callAttr(
                        "start",
                        dataDir,
                        TransportSink(),
                        BridgeEventListener(),
                        initialNickname,
                    ).toString()
                    handleEventJson(readyJson)
                    onReady?.invoke(_shortTag.value)
                } else {
                    onReady?.invoke(_shortTag.value)
                }
            } catch (t: Throwable) {
                Log.e(TAG, "Failed to start Chaquopy LinkChatNode", t)
                started.set(false)
                _lastError.value = "Core startup failed: ${t.message}"
            }
        }
    }

    fun stop() {
        executor.execute {
            try {
                if (started.compareAndSet(true, false)) {
                    module?.callAttr("stop")
                }
            } catch (t: Throwable) {
                Log.w(TAG, "Error stopping PythonBridge", t)
            } finally {
                _isReady.value = false
            }
        }
    }

    fun onLinkUp(handle: String, mtu: Int, rssi: Int) {
        executor.execute {
            runCatching { module?.callAttr("on_link_up", handle, mtu, rssi) }
                .onFailure { Log.w(TAG, "on_link_up failed", it) }
        }
    }

    fun onLinkDown(handle: String) {
        executor.execute {
            runCatching { module?.callAttr("on_link_down", handle) }
                .onFailure { Log.w(TAG, "on_link_down failed", it) }
        }
    }

    fun onChunk(handle: String, data: ByteArray) {
        val copy = data.copyOf()
        executor.execute {
            runCatching { module?.callAttr("on_chunk", handle, copy) }
                .onFailure { Log.w(TAG, "on_chunk failed", it) }
        }
    }

    fun sendPublic(text: String) {
        val cleaned = text.trim()
        if (cleaned.isEmpty()) return
        executor.execute {
            runCatching { module?.callAttr("send_public", cleaned) }
                .onFailure { _lastError.value = it.message }
        }
    }

    fun sendDm(targetIdHex: String, text: String) {
        val cleaned = text.trim()
        if (cleaned.isEmpty()) return
        executor.execute {
            runCatching { module?.callAttr("send_dm", targetIdHex, cleaned) }
                .onFailure { _lastError.value = it.message }
        }
    }

    fun setNickname(nickname: String) {
        val cleaned = nickname.trim()
        if (cleaned.isEmpty()) return
        executor.execute {
            runCatching { module?.callAttr("set_nickname", cleaned) }
                .onFailure { _lastError.value = it.message }
        }
    }

    fun verifyPeer(nodeIdHex: String, verified: Boolean) {
        executor.execute {
            runCatching { module?.callAttr("verify_peer", nodeIdHex, verified) }
                .onFailure { _lastError.value = it.message }
        }
    }

    fun loadHistoryIfNeeded(channelOrPeer: String) {
        executor.execute {
            if (loadedChannels.contains(channelOrPeer)) return@execute
            runCatching {
                val json = module?.callAttr("get_history", channelOrPeer, 200)?.toString()
                    ?: return@execute
                val arr = JSONArray(json)
                val list = buildList {
                    for (i in 0 until arr.length()) {
                        add(parseMessage(arr.getJSONObject(i)))
                    }
                }
                loadedChannels.add(channelOrPeer)
                _messages.update { current ->
                    val existing = current[channelOrPeer].orEmpty()
                    val merged = mergeMessages(list, existing)
                    current + (channelOrPeer to merged)
                }
            }.onFailure { Log.w(TAG, "loadHistory failed for $channelOrPeer", it) }
        }
    }

    fun requestSafetyFingerprint(nodeIdHex: String, onResult: (Result<FingerprintModel>) -> Unit) {
        executor.execute {
            try {
                val mod = module ?: error("Core not ready")
                val json = mod.callAttr("get_safety_fingerprint", nodeIdHex).toString()
                val obj = JSONObject(json)
                val groupsArr = obj.getJSONArray("groups")
                val emojisArr = obj.getJSONArray("emojis")
                val fp = FingerprintModel(
                    nodeIdHex = obj.getString("node_id_hex"),
                    safetyNumber = obj.getString("safety_number"),
                    emojiHash = obj.getString("emoji_hash"),
                    groups = List(groupsArr.length()) { idx -> groupsArr.getString(idx) },
                    emojis = List(emojisArr.length()) { idx -> emojisArr.getString(idx) },
                )
                onResult(Result.success(fp))
            } catch (t: Throwable) {
                onResult(Result.failure(t))
            }
        }
    }

    fun markChannelRead(channel: String) {
        activeChannel = channel
        _unreadCounts.update { it - channel }
    }

    fun clearLogs() {
        _meshLogs.value = emptyList()
    }

    fun clearError() {
        _lastError.value = null
    }

    private fun handleEventJson(eventJson: String) {
        try {
            val obj = JSONObject(eventJson)
            when (obj.optString("type")) {
                "node_ready" -> {
                    _ownNodeId.value = obj.optString("node_id_hex")
                    _shortTag.value = obj.optString("short_tag")
                    _nickname.value = obj.optString("nickname", "Android")
                    val peersArr = obj.optJSONArray("peers") ?: JSONArray()
                    val peerMap = linkedMapOf<String, PeerModel>()
                    for (i in 0 until peersArr.length()) {
                        val peer = parsePeer(peersArr.getJSONObject(i))
                        peerMap[peer.nodeIdHex] = peer
                    }
                    _peers.value = peerMap

                    val histArr = obj.optJSONArray("public_history") ?: JSONArray()
                    val pubMsgs = buildList {
                        for (i in 0 until histArr.length()) {
                            add(parseMessage(histArr.getJSONObject(i)))
                        }
                    }
                    loadedChannels.add("#public")
                    _messages.update { current ->
                        current + ("#public" to mergeMessages(pubMsgs, current["#public"].orEmpty()))
                    }
                    _isReady.value = true
                }

                "peer_updated" -> {
                    val peer = parsePeer(obj.getJSONObject("peer"))
                    _peers.update { it + (peer.nodeIdHex to peer) }
                }

                "public_message", "dm_received" -> {
                    val msg = parseMessage(obj.getJSONObject("record"))
                    _messages.update { current ->
                        val existing = current[msg.channel].orEmpty()
                        current + (msg.channel to mergeMessages(existing, listOf(msg)))
                    }
                    if (!msg.isOutgoing && msg.channel != activeChannel) {
                        _unreadCounts.update { counts ->
                            counts + (msg.channel to ((counts[msg.channel] ?: 0) + 1))
                        }
                    }
                }

                "dm_status_changed" -> {
                    val msgId = obj.getString("msg_id")
                    val newStatus = obj.getString("status")
                    _messages.update { current ->
                        current.mapValues { (_, list) ->
                            list.map { m ->
                                if (m.msgId == msgId) m.copy(status = newStatus) else m
                            }
                        }
                    }
                }

                "mesh_log" -> {
                    val entry = parseLog(obj.getJSONObject("entry"))
                    _meshLogs.update { current ->
                        (current + entry).takeLast(MAX_MESH_LOGS)
                    }
                }

                "nickname_changed" -> {
                    _nickname.value = obj.optString("nickname", _nickname.value)
                }

                "error" -> {
                    _lastError.value = obj.optString("message", "Unknown bridge error")
                }
            }
        } catch (t: Throwable) {
            Log.e(TAG, "Failed to parse bridge event: $eventJson", t)
        }
    }

    private fun mergeMessages(
        base: List<MessageModel>,
        incoming: List<MessageModel>,
    ): List<MessageModel> {
        val byId = LinkedHashMap<String, MessageModel>(base.size + incoming.size)
        for (m in base) byId[m.msgId] = m
        for (m in incoming) byId[m.msgId] = m
        return byId.values.sortedBy { it.timestampMs }
    }

    private fun parsePeer(obj: JSONObject): PeerModel {
        val hex = obj.getString("node_id_hex")
        return PeerModel(
            nodeIdHex = hex,
            shortTag = obj.optString("short_tag", hex.take(4)),
            nickname = obj.optString("nickname", hex.take(4)),
            hopCount = obj.optInt("hop_count", 1),
            rssi = obj.optInt("rssi", -70),
            direct = obj.optBoolean("direct", false),
            connected = obj.optBoolean("connected", false),
            verified = obj.optBoolean("verified", false),
            keyChanged = obj.optBoolean("key_changed", false),
            lastSeen = obj.optDouble("last_seen", 0.0),
            linkHandle = if (obj.isNull("link_handle")) null else obj.optString("link_handle"),
        )
    }

    private fun parseMessage(obj: JSONObject): MessageModel {
        return MessageModel(
            msgId = obj.getString("msg_id"),
            channel = obj.getString("channel"),
            originId = obj.getString("origin_id"),
            targetId = obj.getString("target_id"),
            senderNick = obj.optString("sender_nick", ""),
            text = obj.getString("text"),
            timestampMs = obj.getLong("timestamp_ms"),
            isOutgoing = obj.optBoolean("is_outgoing", false),
            status = obj.optString("status", "delivered"),
            hopCount = obj.optInt("hop_count", 0),
        )
    }

    private fun parseLog(obj: JSONObject): LogEntryModel {
        return LogEntryModel(
            timestampMs = obj.getLong("timestamp_ms"),
            eventType = obj.optString("event_type", "INFO"),
            message = obj.optString("message", ""),
            pktType = obj.optString("pkt_type", ""),
            msgId = obj.optString("msg_id", ""),
            originId = obj.optString("origin_id", ""),
            targetId = obj.optString("target_id", ""),
            hop = obj.optInt("hop", 0),
            ttl = obj.optInt("ttl", 0),
        )
    }

    companion object {
        private const val TAG = "LinkChatPyBridge"
        private const val MAX_MESH_LOGS = 300
    }
}
