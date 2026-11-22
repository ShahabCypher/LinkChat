package com.linkchat

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.unit.LayoutDirection
import com.linkchat.ble.LinkChatService
import com.linkchat.model.PermissionHelper
import com.linkchat.ui.AppLanguage
import com.linkchat.ui.LinkChatApp
import com.linkchat.ui.LinkChatTheme
import com.linkchat.ui.LinkChatViewModel
import com.linkchat.ui.LocalStrings
import com.linkchat.ui.stringsFor

class MainActivity : ComponentActivity() {

    private val viewModel: LinkChatViewModel by viewModels()
    private var hasBlePermissions by mutableStateOf(false)

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) {
        refreshPermissionsAndStartMesh()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        val app = application as LinkChatApplication
        // Start core node immediately so local identity & history load regardless of BLE state.
        app.pythonBridge.start()
        refreshPermissionsAndStartMesh()

        val missing = PermissionHelper.missingStartupPermissions(this)
        if (missing.isNotEmpty()) {
            permissionLauncher.launch(missing.toTypedArray())
        }

        setContent {
            val language by app.language.collectAsState()
            val layoutDirection = if (language.isRtl) LayoutDirection.Rtl else LayoutDirection.Ltr
            LinkChatTheme(isPersian = language == AppLanguage.FA) {
                CompositionLocalProvider(
                    LocalLayoutDirection provides layoutDirection,
                    LocalStrings provides stringsFor(language),
                ) {
                    LinkChatApp(
                        viewModel = viewModel,
                        hasBlePermissions = hasBlePermissions,
                        onRequestPermissions = {
                            val req = PermissionHelper.missingStartupPermissions(this)
                            if (req.isNotEmpty()) {
                                permissionLauncher.launch(req.toTypedArray())
                            } else {
                                refreshPermissionsAndStartMesh()
                            }
                        },
                        onStartMeshService = {
                            if (PermissionHelper.hasBlePermissions(this)) {
                                LinkChatService.start(this)
                            }
                        },
                    )
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        refreshPermissionsAndStartMesh()
    }

    private fun refreshPermissionsAndStartMesh() {
        val granted = PermissionHelper.hasBlePermissions(this)
        hasBlePermissions = granted
        if (granted) {
            LinkChatService.start(this)
        }
    }
}
