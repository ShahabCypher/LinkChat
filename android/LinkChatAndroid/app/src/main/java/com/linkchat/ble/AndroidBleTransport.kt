package com.linkchat.ble

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothGattServer
import android.bluetooth.BluetoothGattServerCallback
import android.bluetooth.BluetoothGattService
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.BluetoothStatusCodes
import android.bluetooth.le.AdvertiseCallback
import android.bluetooth.le.AdvertiseData
import android.bluetooth.le.AdvertiseSettings
import android.bluetooth.le.BluetoothLeAdvertiser
import android.bluetooth.le.BluetoothLeScanner
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.ParcelUuid
import android.util.Log
import com.linkchat.bridge.PythonBridge
import com.linkchat.model.BleStatus
import com.linkchat.model.PermissionHelper
import java.util.ArrayDeque
import java.util.UUID

object LinkChatGattProfile {
    val SERVICE_UUID: UUID = UUID.fromString("7b4e1000-8f2a-4c3b-9d1e-4c696e6b4368")
    val RX_CHAR_UUID: UUID = UUID.fromString("7b4e1001-8f2a-4c3b-9d1e-4c696e6b4368")
    val TX_CHAR_UUID: UUID = UUID.fromString("7b4e1002-8f2a-4c3b-9d1e-4c696e6b4368")
    val CCCD_UUID: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
}

object BleTieBreaker {
    fun parseLinkChatTag(localNameOrData: String?): String? {
        if (localNameOrData == null || !localNameOrData.startsWith("LC-") || localNameOrData.length < 7) {
            return null
        }
        val tag = localNameOrData.substring(3, 7).lowercase()
        val isHex = tag.all { ch -> ch in '0'..'9' || ch in 'a'..'f' }
        return if (isHex) tag else null
    }

    fun shouldInitiateCentral(localTag: String, remoteLocalNameOrData: String?): Boolean {
        val remoteTag = parseLinkChatTag(remoteLocalNameOrData) ?: return true
        return localTag.lowercase() <= remoteTag
    }
}

/**
 * Dual-role Android BLE transport (GATT Server + Advertiser + Scanner + GATT Client).
 *
 * All BLE state mutations and GATT write/notify queues are serialized onto a single
 * HandlerThread ("linkchat-ble-ops") so Android Binder callbacks never race.
 */
@SuppressLint("MissingPermission")
class AndroidBleTransport(
    private val context: Context,
    private val pythonBridge: PythonBridge,
    private val onStatusChanged: (BleStatus) -> Unit,
) : PythonBridge.ChunkSender {

    private data class CentralLink(
        val handle: String,
        val address: String,
        val gatt: BluetoothGatt,
        var rxChar: BluetoothGattCharacteristic? = null,
        var txChar: BluetoothGattCharacteristic? = null,
        var mtu: Int = DEFAULT_MTU,
        var rssi: Int = DEFAULT_RSSI,
        var linkUpNotified: Boolean = false,
        val sendQueue: ArrayDeque<ByteArray> = ArrayDeque(),
        var writeInFlight: Boolean = false,
        var watchdogRunnable: Runnable? = null,
    )

    private data class PeripheralLink(
        val handle: String,
        val device: BluetoothDevice,
        var mtu: Int = DEFAULT_MTU,
        var linkUpNotified: Boolean = false,
        val notifyQueue: ArrayDeque<ByteArray> = ArrayDeque(),
        var notifyInFlight: Boolean = false,
        var watchdogRunnable: Runnable? = null,
    )

    private val bluetoothManager =
        context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
    private val bluetoothAdapter: BluetoothAdapter?
        get() = bluetoothManager?.adapter

    private val opsThread = HandlerThread("linkchat-ble-ops").apply { start() }
    private val opsHandler = Handler(opsThread.looper)

    private var started = false
    private var localTag = "0000"
    private var blockedTags: Set<String> = emptySet()

    private var gattServer: BluetoothGattServer? = null
    private var txCharacteristic: BluetoothGattCharacteristic? = null
    private var advertiser: BluetoothLeAdvertiser? = null
    private var scanner: BluetoothLeScanner? = null

    private var advertisingActive = false
    private var scanningActive = false
    private var statusNote = "Idle"

    private val centralLinks = LinkedHashMap<String, CentralLink>() // key = handle
    private val centralByAddress = LinkedHashMap<String, CentralLink>() // key = MAC
    private val peripheralLinks = LinkedHashMap<String, PeripheralLink>() // key = handle
    private val lastConnectAttemptMs = HashMap<String, Long>()
    private val knownMtuByAddress = HashMap<String, Int>()

    private var scanRetryRunnable: Runnable? = null

    fun setBlockedTags(tags: Set<String>) {
        opsHandler.post {
            blockedTags = tags.map { it.lowercase() }.toSet()
        }
    }

    fun start(shortTag: String) {
        opsHandler.post {
            localTag = shortTag.lowercase().ifBlank { "0000" }
            if (started) return@post
            started = true
            pythonBridge.setChunkSender(this)

            if (!PermissionHelper.hasBlePermissions(context)) {
                statusNote = "Missing BLE permissions"
                emitStatus()
                return@post
            }
            val adapter = bluetoothAdapter
            if (adapter == null || !adapter.isEnabled) {
                statusNote = "Bluetooth is off"
                emitStatus()
                return@post
            }

            startPeripheral()
            startScanning()
            statusNote = if (advertisingActive) "Dual-Role active" else "Central-Only active"
            emitStatus()
        }
    }

    fun restartAfterBluetoothChange() {
        opsHandler.post {
            if (!started) return@post
            stopRadioOnly()
            val adapter = bluetoothAdapter
            if (adapter == null || !adapter.isEnabled || !PermissionHelper.hasBlePermissions(context)) {
                statusNote = if (adapter?.isEnabled == true) "Missing BLE permissions" else "Bluetooth is off"
                emitStatus()
                return@post
            }
            startPeripheral()
            startScanning()
            statusNote = if (advertisingActive) "Dual-Role active" else "Central-Only active"
            emitStatus()
        }
    }

    fun stop() {
        opsHandler.post {
            if (!started) return@post
            started = false
            pythonBridge.setChunkSender(null)
            stopRadioOnly()
            statusNote = "Stopped"
            emitStatus()
        }
    }

    fun release() {
        stop()
        opsThread.quitSafely()
    }

    override fun sendChunk(peerHandle: String, chunk: ByteArray) {
        val copy = chunk.copyOf()
        opsHandler.post {
            if (!started) return@post
            centralLinks[peerHandle]?.let { cLink ->
                cLink.sendQueue.addLast(copy)
                pumpCentralWrite(cLink)
                return@post
            }
            peripheralLinks[peerHandle]?.let { pLink ->
                pLink.notifyQueue.addLast(copy)
                pumpPeripheralNotify(pLink)
            }
        }
    }

    private fun stopRadioOnly() {
        scanRetryRunnable?.let { opsHandler.removeCallbacks(it) }
        scanRetryRunnable = null

        if (PermissionHelper.hasBlePermissions(context)) {
            runCatching {
                if (scanningActive) {
                    scanner?.stopScan(scanCallback)
                }
            }
            runCatching {
                if (advertisingActive) {
                    advertiser?.stopAdvertising(advertiseCallback)
                }
            }
        }
        scanningActive = false
        advertisingActive = false
        scanner = null
        advertiser = null

        for (cLink in centralLinks.values.toList()) {
            cLink.watchdogRunnable?.let { opsHandler.removeCallbacks(it) }
            runCatching { cLink.gatt.disconnect() }
            runCatching { cLink.gatt.close() }
            if (cLink.linkUpNotified) {
                pythonBridge.onLinkDown(cLink.handle)
            }
        }
        centralLinks.clear()
        centralByAddress.clear()

        for (pLink in peripheralLinks.values.toList()) {
            pLink.watchdogRunnable?.let { opsHandler.removeCallbacks(it) }
            if (pLink.linkUpNotified) {
                pythonBridge.onLinkDown(pLink.handle)
            }
        }
        peripheralLinks.clear()

        runCatching { gattServer?.close() }
        gattServer = null
        txCharacteristic = null
    }

    // -------------------------------------------------------------------------
    // Peripheral Role (GATT Server + Advertiser)
    // -------------------------------------------------------------------------

    private fun startPeripheral() {
        val mgr = bluetoothManager ?: return
        val adapter = bluetoothAdapter ?: return
        try {
            val server = mgr.openGattServer(context, gattServerCallback)
            if (server == null) {
                Log.w(TAG, "openGattServer returned null")
                return
            }
            gattServer = server

            val service = BluetoothGattService(
                LinkChatGattProfile.SERVICE_UUID,
                BluetoothGattService.SERVICE_TYPE_PRIMARY,
            )
            val rxChar = BluetoothGattCharacteristic(
                LinkChatGattProfile.RX_CHAR_UUID,
                BluetoothGattCharacteristic.PROPERTY_WRITE or
                    BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE,
                BluetoothGattCharacteristic.PERMISSION_WRITE,
            )
            val txChar = BluetoothGattCharacteristic(
                LinkChatGattProfile.TX_CHAR_UUID,
                BluetoothGattCharacteristic.PROPERTY_NOTIFY,
                BluetoothGattCharacteristic.PERMISSION_READ,
            )
            val cccd = BluetoothGattDescriptor(
                LinkChatGattProfile.CCCD_UUID,
                BluetoothGattDescriptor.PERMISSION_READ or
                    BluetoothGattDescriptor.PERMISSION_WRITE,
            )
            txChar.addDescriptor(cccd)
            txCharacteristic = txChar

            service.addCharacteristic(rxChar)
            service.addCharacteristic(txChar)
            server.addService(service)

            val bleAdv = adapter.bluetoothLeAdvertiser
            if (bleAdv == null) {
                Log.w(TAG, "BluetoothLeAdvertiser unavailable; Central-Only mode")
                return
            }
            advertiser = bleAdv

            val settings = AdvertiseSettings.Builder()
                .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_BALANCED)
                .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_MEDIUM)
                .setConnectable(true)
                .setTimeout(0)
                .build()

            // Keep primary ADV packet <= 21B (Flags 3B + 128-bit UUID 18B) and put LC-<4hex> in ScanResponse.
            val advData = AdvertiseData.Builder()
                .setIncludeDeviceName(false)
                .setIncludeTxPowerLevel(false)
                .addServiceUuid(ParcelUuid(LinkChatGattProfile.SERVICE_UUID))
                .build()

            val tagBytes = "LC-$localTag".toByteArray(Charsets.UTF_8)
            val scanResp = AdvertiseData.Builder()
                .setIncludeDeviceName(false)
                .setIncludeTxPowerLevel(false)
                .addServiceData(ParcelUuid(LinkChatGattProfile.SERVICE_UUID), tagBytes)
                .build()

            bleAdv.startAdvertising(settings, advData, scanResp, advertiseCallback)
        } catch (t: Throwable) {
            Log.w(TAG, "Failed to start BLE Peripheral", t)
        }
    }

    private val advertiseCallback = object : AdvertiseCallback() {
        override fun onStartSuccess(settingsInEffect: AdvertiseSettings?) {
            opsHandler.post {
                advertisingActive = true
                statusNote = "Dual-Role active"
                emitStatus()
            }
        }

        override fun onStartFailure(errorCode: Int) {
            Log.w(TAG, "BLE advertising failed with code=$errorCode")
            opsHandler.post {
                advertisingActive = false
                statusNote = "Central-Only (adv err $errorCode)"
                emitStatus()
            }
        }
    }

    private val gattServerCallback = object : BluetoothGattServerCallback() {
        override fun onConnectionStateChange(device: BluetoothDevice, status: Int, newState: Int) {
            opsHandler.post {
                val handle = peripheralHandle(device.address)
                if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                    val pLink = peripheralLinks.remove(handle)
                    knownMtuByAddress.remove(device.address)
                    if (pLink != null) {
                        pLink.watchdogRunnable?.let { opsHandler.removeCallbacks(it) }
                        if (pLink.linkUpNotified) {
                            pythonBridge.onLinkDown(handle)
                        }
                    }
                    emitStatus()
                }
            }
        }

        override fun onMtuChanged(device: BluetoothDevice, mtu: Int) {
            opsHandler.post {
                val clamped = mtu.coerceIn(DEFAULT_MTU, MAX_ATT_MTU)
                knownMtuByAddress[device.address] = clamped
                peripheralLinks[peripheralHandle(device.address)]?.mtu = clamped
            }
        }

        override fun onDescriptorReadRequest(
            device: BluetoothDevice,
            requestId: Int,
            offset: Int,
            descriptor: BluetoothGattDescriptor,
        ) {
            opsHandler.post {
                val status = if (descriptor.uuid == LinkChatGattProfile.CCCD_UUID) {
                    BluetoothGatt.GATT_SUCCESS
                } else {
                    BluetoothGatt.GATT_FAILURE
                }
                gattServer?.sendResponse(device, requestId, status, offset, byteArrayOf(0, 0))
            }
        }

        override fun onDescriptorWriteRequest(
            device: BluetoothDevice,
            requestId: Int,
            descriptor: BluetoothGattDescriptor,
            preparedWrite: Boolean,
            responseNeeded: Boolean,
            offset: Int,
            value: ByteArray?,
        ) {
            val copy = value?.copyOf()
            opsHandler.post {
                if (responseNeeded) {
                    gattServer?.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, offset, copy)
                }
                if (descriptor.uuid == LinkChatGattProfile.CCCD_UUID && copy != null) {
                    val enabled = copy.contentEquals(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE) ||
                        copy.contentEquals(BluetoothGattDescriptor.ENABLE_INDICATION_VALUE)
                    val handle = peripheralHandle(device.address)
                    if (enabled) {
                        ensurePeripheralLinkUp(device)
                    } else {
                        val pLink = peripheralLinks.remove(handle)
                        if (pLink != null && pLink.linkUpNotified) {
                            pythonBridge.onLinkDown(handle)
                        }
                        emitStatus()
                    }
                }
            }
        }

        override fun onCharacteristicWriteRequest(
            device: BluetoothDevice,
            requestId: Int,
            characteristic: BluetoothGattCharacteristic,
            preparedWrite: Boolean,
            responseNeeded: Boolean,
            offset: Int,
            value: ByteArray?,
        ) {
            val copy = value?.copyOf() ?: ByteArray(0)
            opsHandler.post {
                if (responseNeeded) {
                    gattServer?.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, offset, null)
                }
                if (characteristic.uuid == LinkChatGattProfile.RX_CHAR_UUID && copy.isNotEmpty()) {
                    val pLink = ensurePeripheralLinkUp(device)
                    pythonBridge.onChunk(pLink.handle, copy)
                }
            }
        }

        override fun onNotificationSent(device: BluetoothDevice, status: Int) {
            opsHandler.post {
                val pLink = peripheralLinks[peripheralHandle(device.address)] ?: return@post
                pLink.watchdogRunnable?.let { opsHandler.removeCallbacks(it) }
                pLink.watchdogRunnable = null
                pLink.notifyInFlight = false
                pumpPeripheralNotify(pLink)
            }
        }
    }

    private fun ensurePeripheralLinkUp(device: BluetoothDevice): PeripheralLink {
        val handle = peripheralHandle(device.address)
        val existing = peripheralLinks[handle]
        if (existing != null) {
            if (!existing.linkUpNotified) {
                existing.linkUpNotified = true
                pythonBridge.onLinkUp(handle, existing.mtu, DEFAULT_RSSI)
                emitStatus()
            }
            return existing
        }
        val mtu = knownMtuByAddress[device.address] ?: DEFAULT_MTU
        val created = PeripheralLink(
            handle = handle,
            device = device,
            mtu = mtu,
            linkUpNotified = true,
        )
        peripheralLinks[handle] = created
        pythonBridge.onLinkUp(handle, mtu, DEFAULT_RSSI)
        emitStatus()
        return created
    }

    @Suppress("DEPRECATION")
    private fun pumpPeripheralNotify(pLink: PeripheralLink) {
        if (!started || pLink.notifyInFlight) return
        val server = gattServer ?: return
        val txChar = txCharacteristic ?: return
        val next = pLink.notifyQueue.pollFirst() ?: return

        pLink.notifyInFlight = true
        val ok = try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                server.notifyCharacteristicChanged(pLink.device, txChar, false, next) ==
                    BluetoothStatusCodes.SUCCESS
            } else {
                txChar.value = next
                server.notifyCharacteristicChanged(pLink.device, txChar, false)
            }
        } catch (t: Throwable) {
            Log.w(TAG, "notifyCharacteristicChanged failed", t)
            false
        }

        if (!ok) {
            pLink.notifyInFlight = false
            return
        }

        val watchdog = Runnable {
            if (pLink.notifyInFlight) {
                pLink.notifyInFlight = false
                pumpPeripheralNotify(pLink)
            }
        }
        pLink.watchdogRunnable = watchdog
        opsHandler.postDelayed(watchdog, GATT_OP_TIMEOUT_MS)
    }

    // -------------------------------------------------------------------------
    // Central Role (Scanner + GATT Client)
    // -------------------------------------------------------------------------

    private fun startScanning() {
        val adapter = bluetoothAdapter ?: return
        val bleScanner = adapter.bluetoothLeScanner
        if (bleScanner == null) {
            scheduleScanRetry()
            return
        }
        scanner = bleScanner

        val filter = ScanFilter.Builder()
            .setServiceUuid(ParcelUuid(LinkChatGattProfile.SERVICE_UUID))
            .build()
        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_BALANCED)
            .build()

        try {
            bleScanner.startScan(listOf(filter), settings, scanCallback)
            scanningActive = true
            emitStatus()
        } catch (t: Throwable) {
            Log.w(TAG, "BLE startScan failed", t)
            scanningActive = false
            scheduleScanRetry()
        }
    }

    private fun scheduleScanRetry() {
        scanRetryRunnable?.let { opsHandler.removeCallbacks(it) }
        val retry = Runnable {
            if (started && !scanningActive) {
                startScanning()
            }
        }
        scanRetryRunnable = retry
        opsHandler.postDelayed(retry, SCAN_RETRY_MS)
    }

    private val scanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            opsHandler.post { handleScanResult(result) }
        }

        override fun onBatchScanResults(results: List<ScanResult>) {
            opsHandler.post { results.forEach(::handleScanResult) }
        }

        override fun onScanFailed(errorCode: Int) {
            Log.w(TAG, "BLE scan failed code=$errorCode")
            opsHandler.post {
                scanningActive = false
                emitStatus()
                scheduleScanRetry()
            }
        }
    }

    private fun handleScanResult(result: ScanResult) {
        if (!started) return
        val device = result.device
        val address = device.address ?: return

        if (centralByAddress.containsKey(address)) return
        if (peripheralLinks.containsKey(peripheralHandle(address))) return

        val now = System.currentTimeMillis()
        val lastAttempt = lastConnectAttemptMs[address] ?: 0L
        if (now - lastAttempt < CONNECT_COOLDOWN_MS) return

        val serviceDataBytes = result.scanRecord
            ?.getServiceData(ParcelUuid(LinkChatGattProfile.SERVICE_UUID))
        val serviceLabel = serviceDataBytes?.toString(Charsets.UTF_8)
        val remoteLabel = serviceLabel ?: result.scanRecord?.deviceName ?: device.name

        val remoteTag = BleTieBreaker.parseLinkChatTag(remoteLabel)
        if (remoteTag != null && blockedTags.contains(remoteTag)) {
            return
        }
        if (!BleTieBreaker.shouldInitiateCentral(localTag, remoteLabel)) {
            return
        }

        lastConnectAttemptMs[address] = now
        connectToPeripheral(device, result.rssi)
    }

    private fun connectToPeripheral(device: BluetoothDevice, rssi: Int) {
        val address = device.address
        val handle = centralHandle(address)
        val gatt = try {
            device.connectGatt(context, false, centralGattCallback, BluetoothDevice.TRANSPORT_LE)
        } catch (t: Throwable) {
            Log.w(TAG, "connectGatt failed for $address", t)
            return
        } ?: return

        val link = CentralLink(
            handle = handle,
            address = address,
            gatt = gatt,
            rssi = rssi,
        )
        centralLinks[handle] = link
        centralByAddress[address] = link
    }

    private val centralGattCallback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            opsHandler.post {
                val address = gatt.device.address
                val cLink = centralByAddress[address] ?: return@post

                if (status != BluetoothGatt.GATT_SUCCESS && newState != BluetoothProfile.STATE_CONNECTED) {
                    teardownCentralLink(cLink)
                    return@post
                }

                when (newState) {
                    BluetoothProfile.STATE_CONNECTED -> {
                        val requested = runCatching { gatt.requestMtu(MAX_ATT_MTU) }.getOrDefault(false)
                        if (!requested) {
                            gatt.discoverServices()
                        }
                    }

                    BluetoothProfile.STATE_DISCONNECTED -> {
                        teardownCentralLink(cLink)
                    }
                }
            }
        }

        override fun onMtuChanged(gatt: BluetoothGatt, mtu: Int, status: Int) {
            opsHandler.post {
                val cLink = centralByAddress[gatt.device.address] ?: return@post
                if (status == BluetoothGatt.GATT_SUCCESS) {
                    cLink.mtu = mtu.coerceIn(DEFAULT_MTU, MAX_ATT_MTU)
                }
                gatt.discoverServices()
            }
        }

        @Suppress("DEPRECATION")
        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            opsHandler.post {
                val cLink = centralByAddress[gatt.device.address] ?: return@post
                if (status != BluetoothGatt.GATT_SUCCESS) {
                    teardownCentralLink(cLink)
                    return@post
                }
                val service = gatt.getService(LinkChatGattProfile.SERVICE_UUID)
                val rxChar = service?.getCharacteristic(LinkChatGattProfile.RX_CHAR_UUID)
                val txChar = service?.getCharacteristic(LinkChatGattProfile.TX_CHAR_UUID)
                if (rxChar == null || txChar == null) {
                    teardownCentralLink(cLink)
                    return@post
                }
                cLink.rxChar = rxChar
                cLink.txChar = txChar

                gatt.setCharacteristicNotification(txChar, true)
                val cccd = txChar.getDescriptor(LinkChatGattProfile.CCCD_UUID)
                if (cccd == null) {
                    markCentralLinkUp(cLink)
                    return@post
                }

                val ok = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    gatt.writeDescriptor(cccd, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE) ==
                        BluetoothStatusCodes.SUCCESS
                } else {
                    cccd.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                    gatt.writeDescriptor(cccd)
                }
                if (!ok) {
                    markCentralLinkUp(cLink)
                }
            }
        }

        override fun onDescriptorWrite(
            gatt: BluetoothGatt,
            descriptor: BluetoothGattDescriptor,
            status: Int,
        ) {
            opsHandler.post {
                val cLink = centralByAddress[gatt.device.address] ?: return@post
                if (status == BluetoothGatt.GATT_SUCCESS) {
                    markCentralLinkUp(cLink)
                } else {
                    teardownCentralLink(cLink)
                }
            }
        }

        override fun onCharacteristicWrite(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            status: Int,
        ) {
            opsHandler.post {
                val cLink = centralByAddress[gatt.device.address] ?: return@post
                cLink.watchdogRunnable?.let { opsHandler.removeCallbacks(it) }
                cLink.watchdogRunnable = null
                cLink.writeInFlight = false
                pumpCentralWrite(cLink)
            }
        }

        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray,
        ) {
            val copy = value.copyOf()
            opsHandler.post {
                val cLink = centralByAddress[gatt.device.address] ?: return@post
                if (characteristic.uuid == LinkChatGattProfile.TX_CHAR_UUID) {
                    pythonBridge.onChunk(cLink.handle, copy)
                }
            }
        }

        @Deprecated("Deprecated in API 33")
        @Suppress("DEPRECATION")
        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
        ) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) return
            val copy = characteristic.value?.copyOf() ?: return
            opsHandler.post {
                val cLink = centralByAddress[gatt.device.address] ?: return@post
                if (characteristic.uuid == LinkChatGattProfile.TX_CHAR_UUID) {
                    pythonBridge.onChunk(cLink.handle, copy)
                }
            }
        }
    }

    private fun markCentralLinkUp(cLink: CentralLink) {
        if (cLink.linkUpNotified) return
        cLink.linkUpNotified = true
        pythonBridge.onLinkUp(cLink.handle, cLink.mtu, cLink.rssi)
        emitStatus()
    }

    private fun teardownCentralLink(cLink: CentralLink) {
        cLink.watchdogRunnable?.let { opsHandler.removeCallbacks(it) }
        centralLinks.remove(cLink.handle)
        centralByAddress.remove(cLink.address)
        runCatching { cLink.gatt.disconnect() }
        runCatching { cLink.gatt.close() }
        if (cLink.linkUpNotified) {
            pythonBridge.onLinkDown(cLink.handle)
        }
        emitStatus()
    }

    @Suppress("DEPRECATION")
    private fun pumpCentralWrite(cLink: CentralLink) {
        if (!started || cLink.writeInFlight) return
        val rxChar = cLink.rxChar ?: return
        val next = cLink.sendQueue.pollFirst() ?: return

        val writeType = if (
            (rxChar.properties and BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE) != 0
        ) {
            BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
        } else {
            BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
        }

        cLink.writeInFlight = true
        val ok = try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                cLink.gatt.writeCharacteristic(rxChar, next, writeType) ==
                    BluetoothStatusCodes.SUCCESS
            } else {
                rxChar.writeType = writeType
                rxChar.value = next
                cLink.gatt.writeCharacteristic(rxChar)
            }
        } catch (t: Throwable) {
            Log.w(TAG, "writeCharacteristic failed", t)
            false
        }

        if (!ok) {
            cLink.writeInFlight = false
            return
        }

        val watchdog = Runnable {
            if (cLink.writeInFlight) {
                cLink.writeInFlight = false
                pumpCentralWrite(cLink)
            }
        }
        cLink.watchdogRunnable = watchdog
        opsHandler.postDelayed(watchdog, GATT_OP_TIMEOUT_MS)
    }

    private fun emitStatus() {
        val adapterEnabled = bluetoothAdapter?.isEnabled == true
        onStatusChanged(
            BleStatus(
                serviceRunning = started,
                advertising = advertisingActive,
                scanning = scanningActive,
                centralLinks = centralLinks.count { it.value.linkUpNotified },
                peripheralLinks = peripheralLinks.size,
                bluetoothEnabled = adapterEnabled,
                statusNote = statusNote,
            )
        )
    }

    private fun centralHandle(address: String) = "ble-c:$address"
    private fun peripheralHandle(address: String) = "ble-p:$address"

    companion object {
        private const val TAG = "LinkChatBleTransport"
        private const val DEFAULT_MTU = 23
        private const val MAX_ATT_MTU = 512
        private const val DEFAULT_RSSI = -70
        private const val CONNECT_COOLDOWN_MS = 5_000L
        private const val SCAN_RETRY_MS = 5_000L
        private const val GATT_OP_TIMEOUT_MS = 1_500L
    }
}
