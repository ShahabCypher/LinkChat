"""Windows BLE TransportAdapter using bleak (Central) and bless/WinRT (Peripheral)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from linkchat_core.protocol import RX_CHAR_UUID, SERVICE_UUID, TX_CHAR_UUID

logger = logging.getLogger(__name__)

DEFAULT_MTU = 23
MAX_WIN_MTU = 512
DEFAULT_RSSI = -70
CONNECT_COOLDOWN_SEC = 5.0
SCAN_RETRY_SEC = 5.0


def parse_linkchat_tag(local_name: str | None) -> str | None:
    """Extract the 4-hex-char node tag from an ``LC-<4hex>`` advertisement name."""
    if not local_name or not local_name.startswith("LC-") or len(local_name) < 7:
        return None
    tag = local_name[3:7].lower()
    if all(ch in "0123456789abcdef" for ch in tag):
        return tag
    return None


def is_peer_blocked(known_tag: str | None, blocked_tags: set[str]) -> bool:
    """Return True when ``known_tag`` matches an active 4-hex blocked tag."""
    if not known_tag or not blocked_tags:
        return False
    return known_tag.strip().lower() in blocked_tags


def _extract_service_data_label(adv: AdvertisementData) -> str | None:
    service_data = getattr(adv, "service_data", None) or {}
    for uuid_str, raw in service_data.items():
        if str(uuid_str).lower() == SERVICE_UUID.lower():
            try:
                return bytes(raw).decode("utf-8", errors="ignore")
            except TypeError:
                return None
    return None


def _is_linkchat_adv(device: BLEDevice, adv: AdvertisementData) -> bool:
    service_match = any(
        s.lower() == SERVICE_UUID.lower() for s in (adv.service_uuids or [])
    )
    if service_match:
        return True
    label = _extract_service_data_label(adv) or adv.local_name or device.name
    return parse_linkchat_tag(label) is not None


@dataclass(slots=True)
class _CentralLink:
    handle: str
    address: str
    client: BleakClient
    mtu: int
    rssi: int


@dataclass(slots=True)
class _PeripheralLink:
    handle: str
    device_id: str
    mtu: int
    subscribed_client: Any = None


class WindowsBleTransport:
    """Dual-role Windows BLE transport with automatic Central-only fallback."""

    def __init__(
        self,
        node_id_hex: str = "",
        *,
        force_central_only: bool = False,
        on_mode_changed: Callable[[bool], None] | None = None,
        scan_retry_sec: float = SCAN_RETRY_SEC,
        connect_cooldown_sec: float = CONNECT_COOLDOWN_SEC,
        scanner_factory: Callable[..., Any] | None = None,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._node_id_hex = node_id_hex.lower()
        self._force_central_only = force_central_only
        self.central_only = force_central_only
        self.on_mode_changed = on_mode_changed
        self._scan_retry_sec = scan_retry_sec
        self._connect_cooldown_sec = connect_cooldown_sec
        self._scanner_factory = scanner_factory or BleakScanner
        self._client_factory = client_factory or BleakClient

        self._on_link_up: Callable[[str, int, int], Awaitable[None]] | None = None
        self._on_link_down: Callable[[str], Awaitable[None]] | None = None
        self._on_chunk: Callable[[str, bytes], Awaitable[None]] | None = None

        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = False
        self._scanner: Any = None
        self._scan_task: asyncio.Task[None] | None = None
        self._connect_tasks: dict[str, asyncio.Task[None]] = {}
        self._last_attempt: dict[str, float] = {}
        self._central_links: dict[str, _CentralLink] = {}
        self._central_by_addr: dict[str, str] = {}
        self._blocked_tags: set[str] = set()
        self._tag_by_addr: dict[str, str] = {}
        self._tag_by_handle: dict[str, str] = {}

        self._bless_server: Any = None
        self._winrt_provider: Any = None
        self._winrt_rx_char: Any = None
        self._winrt_tx_char: Any = None
        self._winrt_tokens: list[tuple[Any, str, Any]] = []
        self._peripheral_links: dict[str, _PeripheralLink] = {}

    @property
    def local_tag(self) -> str:
        return self._node_id_hex[:4].lower() if self._node_id_hex else "0000"

    @property
    def local_name(self) -> str:
        return f"LC-{self.local_tag}"

    @property
    def mode_label(self) -> str:
        return "Central-Only" if self.central_only else "Dual-Role"

    def set_node_id(self, node_id_hex: str) -> None:
        self._node_id_hex = node_id_hex.lower()

    async def set_blocked_tags(self, tags: Iterable[str]) -> None:
        self._blocked_tags = {
            t.strip().lower() for t in tags if t and t.strip()
        }
        if self._blocked_tags:
            await self._drop_blocked_links()

    async def register_peer_link_tag(self, link_handle: str, short_tag: str) -> None:
        clean = short_tag.strip().lower()
        if not clean:
            return
        self._tag_by_handle[link_handle] = clean
        if link_handle.startswith("ble-c:"):
            self._tag_by_addr[link_handle[6:]] = clean
        if clean in self._blocked_tags:
            await self._drop_blocked_links()

    def _is_blocked_peer(self, handle: str, addr: str | None = None) -> bool:
        tag = self._tag_by_handle.get(handle)
        if tag is None and addr is not None:
            tag = self._tag_by_addr.get(addr)
        return is_peer_blocked(tag, self._blocked_tags)

    async def _drop_blocked_links(self) -> None:
        for handle, c_link in list(self._central_links.items()):
            if self._is_blocked_peer(handle, c_link.address):
                await self._drop_central_link(handle, c_link)
        for handle in list(self._peripheral_links):
            if self._is_blocked_peer(handle):
                await self.disconnect_link(handle)

    def set_callbacks(
        self,
        on_link_up: Callable[[str, int, int], Awaitable[None]],
        on_link_down: Callable[[str], Awaitable[None]],
        on_chunk: Callable[[str, bytes], Awaitable[None]],
    ) -> None:
        self._on_link_up = on_link_up
        self._on_link_down = on_link_down
        self._on_chunk = on_chunk

    def should_initiate_central(self, remote_local_name: str | None) -> bool:
        """Apply deterministic node_id tie-breaker unless running Central-only."""
        if self.central_only:
            return True
        remote_tag = parse_linkchat_tag(remote_local_name)
        if remote_tag is None:
            # Windows peripherals may advertise host name instead of LC-<4hex>.
            return True
        return self.local_tag <= remote_tag

    def _set_central_only(self, value: bool) -> None:
        if self.central_only != value:
            self.central_only = value
            if self.on_mode_changed is not None:
                self.on_mode_changed(value)

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._loop = asyncio.get_running_loop()
        self._set_central_only(self._force_central_only)

        if not self.central_only:
            ok = await self._start_peripheral()
            if not ok:
                self._set_central_only(True)

        self._scan_task = asyncio.create_task(self._scanner_supervisor())

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        self._last_attempt.clear()

        if self._scan_task is not None:
            self._scan_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scan_task
            self._scan_task = None

        for task in list(self._connect_tasks.values()):
            task.cancel()
        if self._connect_tasks:
            await asyncio.gather(*self._connect_tasks.values(), return_exceptions=True)
        self._connect_tasks.clear()

        if self._scanner is not None:
            with contextlib.suppress(Exception):
                await self._scanner.stop()
            self._scanner = None

        for handle in list(self._central_links):
            link = self._central_links.pop(handle, None)
            if link is not None:
                self._central_by_addr.pop(link.address, None)
                with contextlib.suppress(Exception):
                    await link.client.disconnect()
                if self._on_link_down is not None:
                    await self._on_link_down(handle)

        await self._stop_peripheral()

    def _schedule_bg(
        self, coro_factory: Callable[[], Awaitable[None]], label: str
    ) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return

        async def _run() -> None:
            try:
                await coro_factory()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unhandled error in %s", label)

        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(lambda: asyncio.create_task(_run()))

    async def _drop_central_link(self, handle: str, link: _CentralLink) -> None:
        logger.warning("Dropping closed/disconnected central link %s", handle)
        await self._handle_central_disconnect(handle)
        with contextlib.suppress(Exception):
            await link.client.disconnect()

    async def disconnect_link(self, handle: str) -> None:
        """Tear down a stale central or peripheral link requested by the router."""
        c_link = self._central_links.get(handle)
        if c_link is not None:
            await self._drop_central_link(handle, c_link)
            return
        p_link = self._peripheral_links.get(handle)
        if p_link is not None:
            if p_link.subscribed_client is not None:
                with contextlib.suppress(Exception):
                    p_link.subscribed_client.session.close()
            await self._handle_peripheral_disconnect(handle)

    async def _prune_dead_links(self) -> None:
        for handle, link in list(self._central_links.items()):
            if not getattr(link.client, "is_connected", True):
                await self._drop_central_link(handle, link)

        if self._winrt_tx_char is not None and self._peripheral_links:
            try:
                clients = list(self._winrt_tx_char.subscribed_clients)
            except Exception:
                return
            active_handles = {
                f"ble-p:{sub.session.device_id.id}" for sub in clients
            }
            for handle, p_link in list(self._peripheral_links.items()):
                if p_link.subscribed_client is not None and handle not in active_handles:
                    await self._handle_peripheral_disconnect(handle)

    async def _handle_peripheral_disconnect(self, handle: str) -> None:
        link = self._peripheral_links.pop(handle, None)
        if link is None:
            return
        if self._on_link_down is not None:
            await self._on_link_down(handle)

    async def send_chunk(self, peer_handle: str, chunk: bytes) -> None:
        if not self._started:
            return

        c_link = self._central_links.get(peer_handle)
        if c_link is not None:
            if not getattr(c_link.client, "is_connected", True):
                await self._drop_central_link(peer_handle, c_link)
                raise ConnectionError(f"Central link {peer_handle} is disconnected")
            try:
                await c_link.client.write_gatt_char(RX_CHAR_UUID, chunk, response=False)
                return
            except OSError:
                # WinRT handle closed/cancelled: drop link instead of retrying.
                await self._drop_central_link(peer_handle, c_link)
                raise
            except Exception:
                if not getattr(c_link.client, "is_connected", True):
                    await self._drop_central_link(peer_handle, c_link)
                    raise
                # Some peripherals only accept Write With Response.
                try:
                    await c_link.client.write_gatt_char(
                        RX_CHAR_UUID, chunk, response=True
                    )
                    return
                except Exception:
                    await self._drop_central_link(peer_handle, c_link)
                    raise

        p_link = self._peripheral_links.get(peer_handle)
        if p_link is not None:
            try:
                await self._send_peripheral_notification(p_link, chunk)
            except Exception:
                await self._handle_peripheral_disconnect(peer_handle)
                raise

    # ------------------------------------------------------------------
    # Central role (bleak)
    # ------------------------------------------------------------------

    async def _scanner_supervisor(self) -> None:
        while self._started:
            try:
                scanner = self._scanner_factory(
                    detection_callback=self._on_advertisement,
                    service_uuids=[SERVICE_UUID],
                )
                await scanner.start()
                self._scanner = scanner
                logger.info("BLE Central scanner started (%s)", self.mode_label)
                while self._started:
                    await asyncio.sleep(1.0)
                    await self._prune_dead_links()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "BLE scanner unavailable (%s); retrying in %.1fs",
                    exc,
                    self._scan_retry_sec,
                )
                if self._scanner is not None:
                    with contextlib.suppress(Exception):
                        await self._scanner.stop()
                    self._scanner = None
                await asyncio.sleep(self._scan_retry_sec)

    def _on_advertisement(self, device: BLEDevice, adv: AdvertisementData) -> None:
        if not self._started or not _is_linkchat_adv(device, adv):
            return
        addr = device.address
        if addr in self._central_by_addr or addr in self._connect_tasks:
            return

        now = time.monotonic()
        if now - self._last_attempt.get(addr, 0.0) < self._connect_cooldown_sec:
            return

        remote_label = _extract_service_data_label(adv) or adv.local_name or device.name
        remote_tag = parse_linkchat_tag(remote_label)
        if remote_tag is not None:
            self._tag_by_addr[addr] = remote_tag
            self._tag_by_handle[f"ble-c:{addr}"] = remote_tag
            self._tag_by_handle[f"ble-p:{addr}"] = remote_tag
        if self._is_blocked_peer(f"ble-c:{addr}", addr):
            return
        if not self.should_initiate_central(remote_label):
            return

        self._last_attempt[addr] = now
        rssi = adv.rssi if adv.rssi is not None else DEFAULT_RSSI
        task = asyncio.create_task(self._connect_central(device, rssi))
        self._connect_tasks[addr] = task
        task.add_done_callback(lambda _t, a=addr: self._connect_tasks.pop(a, None))

    async def _connect_central(self, device: BLEDevice, rssi: int) -> None:
        addr = device.address
        handle = f"ble-c:{addr}"

        def _on_disconnect(_client: Any) -> None:
            self._schedule_bg(
                lambda: self._handle_central_disconnect(handle),
                f"central disconnect ({handle})",
            )

        client = self._client_factory(device, disconnected_callback=_on_disconnect)
        try:
            await client.connect()
            if (
                not self._started
                or not getattr(client, "is_connected", True)
                or self._is_blocked_peer(handle, addr)
            ):
                with contextlib.suppress(Exception):
                    await client.disconnect()
                return

            def _on_notify(_char: Any, data: bytearray) -> None:
                if self._on_chunk is None:
                    return
                payload = bytes(data)
                on_chunk = self._on_chunk
                self._schedule_bg(
                    lambda: on_chunk(handle, payload),
                    f"central notify ({handle})",
                )

            await client.start_notify(TX_CHAR_UUID, _on_notify)
            if not self._started or not getattr(client, "is_connected", True):
                with contextlib.suppress(Exception):
                    await client.disconnect()
                return
            raw_mtu = getattr(client, "mtu_size", DEFAULT_MTU) or DEFAULT_MTU
            mtu = max(DEFAULT_MTU, min(int(raw_mtu), MAX_WIN_MTU))
            self._central_links[handle] = _CentralLink(
                handle=handle,
                address=addr,
                client=client,
                mtu=mtu,
                rssi=rssi,
            )
            self._central_by_addr[addr] = handle
            if self._on_link_up is not None:
                await self._on_link_up(handle, mtu, rssi)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await client.disconnect()
            raise
        except Exception as exc:
            logger.debug("Central connection to %s failed: %s", addr, exc)
            with contextlib.suppress(Exception):
                await client.disconnect()

    async def _handle_central_disconnect(self, handle: str) -> None:
        link = self._central_links.pop(handle, None)
        if link is None:
            return
        self._central_by_addr.pop(link.address, None)
        if self._on_link_down is not None:
            await self._on_link_down(handle)

    # ------------------------------------------------------------------
    # Peripheral role (bless with WinRT fallback, else Central-only)
    # ------------------------------------------------------------------

    async def _start_peripheral(self) -> bool:
        try:
            return await self._start_bless_peripheral()
        except ImportError as exc:
            logger.info("bless unavailable (%s); trying WinRT GattServiceProvider", exc)
            return await self._start_winrt_peripheral()
        except Exception as exc:
            logger.warning(
                "BLE Peripheral startup failed (%s); falling back to Central-only mode",
                exc,
            )
            await self._stop_peripheral()
            return False

    async def _start_bless_peripheral(self) -> bool:
        from bless import (
            BlessServer,
            GATTAttributePermissions,
            GATTCharacteristicProperties,
        )

        server = BlessServer(name=self.local_name, loop=self._loop)

        def _on_write(characteristic: Any, value: Any, **kwargs: Any) -> None:
            if str(characteristic.uuid).lower() != RX_CHAR_UUID.lower():
                return
            peer_id = str(kwargs.get("device") or "bless-central")
            handle = f"ble-p:{peer_id}"
            data = bytes(value)
            self._schedule_bg(
                lambda: self._handle_bless_write(handle, peer_id, data),
                f"bless write ({handle})",
            )

        server.read_request_func = lambda _char, **_kw: bytearray()
        server.write_request_func = _on_write

        await server.add_new_service(SERVICE_UUID)
        await server.add_new_characteristic(
            SERVICE_UUID,
            RX_CHAR_UUID,
            GATTCharacteristicProperties.write
            | GATTCharacteristicProperties.write_without_response,
            None,
            GATTAttributePermissions.writeable,
        )
        await server.add_new_characteristic(
            SERVICE_UUID,
            TX_CHAR_UUID,
            GATTCharacteristicProperties.notify,
            None,
            GATTAttributePermissions.readable,
        )
        await server.start()
        self._bless_server = server
        logger.info("BLE Peripheral started via bless (%s)", self.local_name)
        return True

    async def _handle_bless_write(self, handle: str, peer_id: str, data: bytes) -> None:
        if self._is_blocked_peer(handle):
            return
        if handle not in self._peripheral_links:
            self._peripheral_links[handle] = _PeripheralLink(
                handle=handle, device_id=peer_id, mtu=DEFAULT_MTU
            )
            if self._on_link_up is not None:
                await self._on_link_up(handle, DEFAULT_MTU, DEFAULT_RSSI)
        if self._on_chunk is not None:
            await self._on_chunk(handle, data)

    async def _start_winrt_peripheral(self) -> bool:
        try:
            from winrt.windows.devices.bluetooth import BluetoothError
            from winrt.windows.devices.bluetooth.genericattributeprofile import (
                GattCharacteristicProperties,
                GattLocalCharacteristicParameters,
                GattProtectionLevel,
                GattServiceProvider,
                GattServiceProviderAdvertisementStatus,
                GattServiceProviderAdvertisingParameters,
                GattWriteOption,
            )
        except Exception as exc:
            logger.warning(
                "WinRT GATT peripheral API unavailable (%s); falling back to Central-only",
                exc,
            )
            return False

        try:
            res = await GattServiceProvider.create_async(uuid.UUID(SERVICE_UUID))
            if res.error != BluetoothError.SUCCESS or res.service_provider is None:
                logger.warning(
                    "GattServiceProvider rejected (%s); falling back to Central-only mode",
                    res.error,
                )
                return False

            provider = res.service_provider
            self._winrt_provider = provider

            rx_params = GattLocalCharacteristicParameters()
            rx_params.characteristic_properties = (
                GattCharacteristicProperties.WRITE
                | GattCharacteristicProperties.WRITE_WITHOUT_RESPONSE
            )
            rx_params.write_protection_level = GattProtectionLevel.PLAIN
            rx_res = await provider.service.create_characteristic_async(
                uuid.UUID(RX_CHAR_UUID), rx_params
            )
            if rx_res.error != BluetoothError.SUCCESS or rx_res.characteristic is None:
                raise RuntimeError(f"RX characteristic creation failed: {rx_res.error}")
            self._winrt_rx_char = rx_res.characteristic

            tx_params = GattLocalCharacteristicParameters()
            tx_params.characteristic_properties = GattCharacteristicProperties.NOTIFY
            tx_params.read_protection_level = GattProtectionLevel.PLAIN
            tx_res = await provider.service.create_characteristic_async(
                uuid.UUID(TX_CHAR_UUID), tx_params
            )
            if tx_res.error != BluetoothError.SUCCESS or tx_res.characteristic is None:
                raise RuntimeError(f"TX characteristic creation failed: {tx_res.error}")
            self._winrt_tx_char = tx_res.characteristic

            def _on_write_requested(_sender: Any, args: Any) -> None:
                loop = self._loop
                if loop is None or not loop.is_running():
                    return
                deferral = args.get_deferral()
                session_id = str(args.session.device_id.id)
                max_pdu = int(getattr(args.session, "max_pdu_size", DEFAULT_MTU) or DEFAULT_MTU)

                async def _process() -> None:
                    try:
                        req = await args.get_request_async()
                        if req is None:
                            return
                        data = bytes(req.value)
                        if req.option == GattWriteOption.WRITE_WITH_RESPONSE:
                            req.respond()
                        handle = f"ble-p:{session_id}"
                        if self._is_blocked_peer(handle):
                            with contextlib.suppress(Exception):
                                args.session.close()
                            return
                        if handle not in self._peripheral_links:
                            mtu = max(DEFAULT_MTU, min(max_pdu, MAX_WIN_MTU))
                            self._peripheral_links[handle] = _PeripheralLink(
                                handle=handle, device_id=session_id, mtu=mtu
                            )
                            if self._on_link_up is not None:
                                await self._on_link_up(handle, mtu, DEFAULT_RSSI)
                        if self._on_chunk is not None:
                            await self._on_chunk(handle, data)
                    except Exception:
                        logger.exception("Unhandled error in WinRT write handler")
                    finally:
                        deferral.complete()

                try:
                    loop.call_soon_threadsafe(
                        lambda: asyncio.create_task(_process())
                    )
                except RuntimeError:
                    deferral.complete()

            def _on_subscribed_changed(sender: Any, _args: Any) -> None:
                clients = list(sender.subscribed_clients)
                self._schedule_bg(
                    lambda: self._sync_winrt_subscribers(clients),
                    "WinRT subscribers sync",
                )

            w_tok = self._winrt_rx_char.add_write_requested(_on_write_requested)
            s_tok = self._winrt_tx_char.add_subscribed_clients_changed(
                _on_subscribed_changed
            )
            self._winrt_tokens.append((self._winrt_rx_char, "remove_write_requested", w_tok))
            self._winrt_tokens.append(
                (self._winrt_tx_char, "remove_subscribed_clients_changed", s_tok)
            )

            adv_params = GattServiceProviderAdvertisingParameters()
            adv_params.is_discoverable = True
            adv_params.is_connectable = True
            provider.start_advertising(adv_params)
            await asyncio.sleep(0.25)
            if provider.advertisement_status not in (
                GattServiceProviderAdvertisementStatus.STARTED,
                GattServiceProviderAdvertisementStatus.STARTED_WITHOUT_ALL_ADVERTISEMENT_DATA,
            ):
                logger.warning(
                    "WinRT BLE Peripheral advertising rejected (status=%s); falling back to Central-only",
                    provider.advertisement_status,
                )
                await self._stop_peripheral()
                return False
            logger.info("BLE Peripheral started via WinRT GattServiceProvider")
            return True
        except Exception as exc:
            logger.warning(
                "WinRT GattServiceProvider startup failed (%s); falling back to Central-only",
                exc,
            )
            await self._stop_peripheral()
            return False

    async def _sync_winrt_subscribers(self, clients: list[Any]) -> None:
        current: dict[str, Any] = {}
        for sub in clients:
            dev_id = str(sub.session.device_id.id)
            current[f"ble-p:{dev_id}"] = sub

        # Handle disconnects
        for handle in list(self._peripheral_links):
            if handle not in current:
                await self._handle_peripheral_disconnect(handle)

        # Handle new subscriptions
        for handle, sub in current.items():
            if self._is_blocked_peer(handle):
                with contextlib.suppress(Exception):
                    sub.session.close()
                if handle in self._peripheral_links:
                    await self._handle_peripheral_disconnect(handle)
                continue
            if handle not in self._peripheral_links:
                max_pdu = int(
                    getattr(sub.session, "max_pdu_size", 0)
                    or (int(getattr(sub, "max_notification_size", 20)) + 3)
                )
                mtu = max(DEFAULT_MTU, min(max_pdu, MAX_WIN_MTU))
                self._peripheral_links[handle] = _PeripheralLink(
                    handle=handle,
                    device_id=str(sub.session.device_id.id),
                    mtu=mtu,
                    subscribed_client=sub,
                )
                if self._on_link_up is not None:
                    await self._on_link_up(handle, mtu, DEFAULT_RSSI)
            else:
                self._peripheral_links[handle].subscribed_client = sub

    async def _send_peripheral_notification(
        self, link: _PeripheralLink, chunk: bytes
    ) -> None:
        if self._bless_server is not None:
            char = self._bless_server.get_characteristic(TX_CHAR_UUID)
            if char is not None:
                char.value = bytearray(chunk)
                self._bless_server.update_value(SERVICE_UUID, TX_CHAR_UUID)
            return

        if self._winrt_tx_char is not None:
            from winrt.windows.devices.bluetooth.genericattributeprofile import (
                GattCommunicationStatus,
            )
            from winrt.windows.storage.streams import DataWriter

            writer = DataWriter()
            writer.write_bytes(chunk)
            buf = writer.detach_buffer()
            if link.subscribed_client is not None:
                res = await self._winrt_tx_char.notify_value_async(
                    buf, link.subscribed_client
                )
                if res.status != GattCommunicationStatus.SUCCESS:
                    raise ConnectionError(f"WinRT notify failed: {res.status}")
            else:
                await self._winrt_tx_char.notify_value_async(buf)

    async def _stop_peripheral(self) -> None:
        for handle in list(self._peripheral_links):
            link = self._peripheral_links.get(handle)
            if link is not None and link.subscribed_client is not None:
                with contextlib.suppress(Exception):
                    link.subscribed_client.session.close()
            await self._handle_peripheral_disconnect(handle)

        for obj, remover_name, token in self._winrt_tokens:
            with contextlib.suppress(Exception):
                getattr(obj, remover_name)(token)
        self._winrt_tokens.clear()

        if self._winrt_provider is not None:
            with contextlib.suppress(Exception):
                self._winrt_provider.stop_advertising()
            self._winrt_provider = None
        self._winrt_rx_char = None
        self._winrt_tx_char = None

        if self._bless_server is not None:
            with contextlib.suppress(Exception):
                await self._bless_server.stop()
            self._bless_server = None
