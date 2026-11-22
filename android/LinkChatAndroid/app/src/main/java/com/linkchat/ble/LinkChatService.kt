package com.linkchat.ble

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.bluetooth.BluetoothAdapter
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.linkchat.LinkChatApplication
import com.linkchat.MainActivity
import com.linkchat.R
import com.linkchat.model.BleStatus
import com.linkchat.model.BleStatusKind
import com.linkchat.model.PermissionHelper
import com.linkchat.ui.stringsFor
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

class LinkChatService : Service() {

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var bleTransport: AndroidBleTransport? = null
    private var languageJob: Job? = null
    private var bluetoothReceiverRegistered = false

    private val bluetoothStateReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == BluetoothAdapter.ACTION_STATE_CHANGED) {
                bleTransport?.restartAfterBluetoothChange()
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopMesh()
            stopSelf()
            return START_NOT_STICKY
        }

        if (!PermissionHelper.hasBlePermissions(this)) {
            stopSelf()
            return START_NOT_STICKY
        }

        val app = application as LinkChatApplication
        val currentStrings = stringsFor(app.language.value)
        startForegroundCompat(buildNotification(currentStrings.notifStarting))

        val transport = bleTransport ?: AndroidBleTransport(
            context = this,
            pythonBridge = app.pythonBridge,
            onStatusChanged = { status ->
                app.updateBleStatus { status }
                updateNotification(formatNotificationText(status))
            },
        ).also { bleTransport = it }

        app.bleResetHandler = object : LinkChatApplication.BleResetHandler {
            override fun stopAndClearForReset() {
                transport.stopAndClearForReset()
            }

            override fun restartAfterReset(newShortTag: String) {
                transport.restartWithNewTag(newShortTag)
            }
        }

        if (!bluetoothReceiverRegistered) {
            registerReceiver(
                bluetoothStateReceiver,
                IntentFilter(BluetoothAdapter.ACTION_STATE_CHANGED),
            )
            bluetoothReceiverRegistered = true
        }

        languageJob?.cancel()
        languageJob = serviceScope.launch {
            app.language.collect {
                updateNotification(formatNotificationText(app.bleStatus.value))
            }
        }

        app.pythonBridge.start(onReady = { shortTag ->
            transport.start(shortTag)
        })

        return START_STICKY
    }

    override fun onDestroy() {
        stopMesh()
        serviceScope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun stopMesh() {
        languageJob?.cancel()
        languageJob = null
        if (bluetoothReceiverRegistered) {
            runCatching { unregisterReceiver(bluetoothStateReceiver) }
            bluetoothReceiverRegistered = false
        }
        val app = application as? LinkChatApplication
        app?.bleResetHandler = null
        bleTransport?.release()
        bleTransport = null
        app?.updateBleStatus {
            it.copy(
                serviceRunning = false,
                advertising = false,
                scanning = false,
                centralLinks = 0,
                peripheralLinks = 0,
                statusNote = "Stopped",
                statusKind = BleStatusKind.STOPPED,
                errorCode = null,
            )
        }
    }

    private fun startForegroundCompat(notification: Notification) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE,
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                getString(R.string.notification_channel_name),
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = getString(R.string.notification_channel_desc)
            }
            val nm = getSystemService(NotificationManager::class.java)
            nm?.createNotificationChannel(channel)
        }
    }

    private fun updateNotification(text: String) {
        val nm = getSystemService(NotificationManager::class.java) ?: return
        nm.notify(NOTIFICATION_ID, buildNotification(text))
    }

    private fun formatNotificationText(status: BleStatus): String {
        val strings = stringsFor((application as LinkChatApplication).language.value)
        val links = status.totalLinks
        return "${strings.notifStatus(status)} • ${strings.notifDirectLinks(links)}"
    }

    private fun buildNotification(text: String): Notification {
        val strings = stringsFor((application as LinkChatApplication).language.value)
        val openIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_SINGLE_TOP
            },
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val stopIntent = PendingIntent.getService(
            this,
            1,
            Intent(this, LinkChatService::class.java).apply { action = ACTION_STOP },
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
            .setContentTitle(strings.notifTitle)
            .setContentText(text)
            .setOngoing(true)
            .setContentIntent(openIntent)
            .addAction(0, strings.notifStop, stopIntent)
            .build()
    }

    companion object {
        const val CHANNEL_ID = "linkchat_ble_mesh"
        const val NOTIFICATION_ID = 1001
        const val ACTION_STOP = "com.linkchat.action.STOP_MESH"

        fun start(context: Context) {
            val intent = Intent(context, LinkChatService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, LinkChatService::class.java))
        }
    }
}
