package com.linkchat.model

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.content.ContextCompat

object PermissionHelper {

    fun requiredBleServicePermissions(sdkInt: Int = Build.VERSION.SDK_INT): List<String> {
        return if (sdkInt >= Build.VERSION_CODES.S) {
            listOf(
                Manifest.permission.BLUETOOTH_SCAN,
                Manifest.permission.BLUETOOTH_ADVERTISE,
                Manifest.permission.BLUETOOTH_CONNECT,
            )
        } else {
            listOf(
                Manifest.permission.ACCESS_FINE_LOCATION,
            )
        }
    }

    fun allStartupPermissions(sdkInt: Int = Build.VERSION.SDK_INT): List<String> {
        val perms = requiredBleServicePermissions(sdkInt).toMutableList()
        if (sdkInt >= Build.VERSION_CODES.TIRAMISU) {
            perms.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        return perms
    }

    fun hasBlePermissions(context: Context): Boolean {
        return requiredBleServicePermissions().all { perm ->
            ContextCompat.checkSelfPermission(context, perm) == PackageManager.PERMISSION_GRANTED
        }
    }

    fun missingStartupPermissions(context: Context): List<String> {
        return allStartupPermissions().filter { perm ->
            ContextCompat.checkSelfPermission(context, perm) != PackageManager.PERMISSION_GRANTED
        }
    }
}
