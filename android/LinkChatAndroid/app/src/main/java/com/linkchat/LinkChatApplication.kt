package com.linkchat

import android.app.Application
import android.content.Context
import com.linkchat.bridge.PythonBridge
import com.linkchat.model.BleStatus
import com.linkchat.ui.AppLanguage
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

    private val _language = MutableStateFlow(AppLanguage.DEFAULT)
    val language: StateFlow<AppLanguage> = _language.asStateFlow()

    @Volatile
    var bleResetHandler: BleResetHandler? = null

    override fun onCreate() {
        super.onCreate()
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        _language.value = AppLanguage.fromCode(prefs.getString(KEY_LANGUAGE, null))
        pythonBridge = PythonBridge(this)
    }

    fun setLanguage(lang: AppLanguage) {
        _language.value = lang
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_LANGUAGE, lang.code)
            .apply()
    }

    fun toggleLanguage() {
        setLanguage(if (_language.value == AppLanguage.FA) AppLanguage.EN else AppLanguage.FA)
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

    companion object {
        private const val PREFS_NAME = "linkchat_ui_prefs"
        private const val KEY_LANGUAGE = "language"
    }
}
