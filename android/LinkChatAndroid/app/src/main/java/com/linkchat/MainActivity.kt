package com.linkchat

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.linkchat.ble.LinkChatService
import com.linkchat.model.PermissionHelper
import com.linkchat.ui.LinkChatApp
import com.linkchat.ui.LinkChatTheme
import com.linkchat.ui.LinkChatViewModel

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

        // Start core node immediately so local identity & history load regardless of BLE state.
        (application as LinkChatApplication).pythonBridge.start()
        refreshPermissionsAndStartMesh()

        val missing = PermissionHelper.missingStartupPermissions(this)
        if (missing.isNotEmpty()) {
            permissionLauncher.launch(missing.toTypedArray())
        }

        setContent {
            LinkChatTheme {
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
