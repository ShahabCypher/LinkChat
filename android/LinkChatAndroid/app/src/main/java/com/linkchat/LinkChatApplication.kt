package com.linkchat

import android.app.Application
import com.linkchat.bridge.PythonBridge
import com.linkchat.model.BleStatus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

class LinkChatApplication : Application() {

    interface BleResetHandler {
        fun stopAndClearForReset()
        fun restartAfterReset(newShortTag: String)
    }

    lateinit var pythonBridge: PythonBridge
        private set

    private val _bleStatus = MutableStateFlow(BleStatus())
    val bleStatus: StateFlow<BleStatus> = _bleStatus.asStateFlow()

    val blockedTags = MutableStateFlow<Set<String>>(emptySet())

    @Volatile
    var bleResetHandler: BleResetHandler? = null

    override fun onCreate() {
        super.onCreate()
        pythonBridge = PythonBridge(this)
    }

    fun updateBleStatus(transform: (BleStatus) -> BleStatus) {
        _bleStatus.value = transform(_bleStatus.value)
    }

    fun resetAllData() {
        blockedTags.value = emptySet()
        val handler = bleResetHandler
        pythonBridge.resetAllData(
            onBeforeCoreReset = { handler?.stopAndClearForReset() },
            onAfterCoreReset = { newTag -> handler?.restartAfterReset(newTag) },
        )
    }
}
