package com.linkchat

import android.app.Application
import com.linkchat.bridge.PythonBridge
import com.linkchat.model.BleStatus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

class LinkChatApplication : Application() {

    lateinit var pythonBridge: PythonBridge
        private set

    private val _bleStatus = MutableStateFlow(BleStatus())
    val bleStatus: StateFlow<BleStatus> = _bleStatus.asStateFlow()

    val blockedTags = MutableStateFlow<Set<String>>(emptySet())

    override fun onCreate() {
        super.onCreate()
        pythonBridge = PythonBridge(this)
    }

    fun updateBleStatus(transform: (BleStatus) -> BleStatus) {
        _bleStatus.value = transform(_bleStatus.value)
    }
}
