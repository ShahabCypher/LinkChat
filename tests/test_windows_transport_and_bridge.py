"""Tests for WindowsBleTransport (tie-breaker, Central-only fallback, bleak flow) and BackendBridge."""

from __future__ import annotations

import asyncio
import queue
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from linkchat_core import DMStatus
from linkchat_core.protocol import RX_CHAR_UUID, SERVICE_UUID, TX_CHAR_UUID
from linkchat_sim.virtual_transport import NetworkHub, VirtualTransport
from linkchat_win.app import (
    BackendBridge,
    DmReceivedEvent,
    DmStatusChangedEvent,
    FingerprintReadyEvent,
    HistoryLoadedEvent,
    NodeReadyEvent,
    NodeResetEvent,
    PeerUpdatedEvent,
    PublicMessageEvent,
)
from linkchat_win.ble_transport import (
    WindowsBleTransport,
    is_peer_blocked,
    parse_linkchat_tag,
)


@dataclass
class _FakeDevice:
    address: str
    name: str | None = None


@dataclass
class _FakeAdv:
    local_name: str | None = None
    service_uuids: list[str] | None = None
    service_data: dict[str, bytes] | None = None
    rssi: int | None = -62


class _FakeScanner:
    def __init__(self, detection_callback: Any, service_uuids: list[str] | None = None) -> None:
        self.detection_callback = detection_callback
        self.service_uuids = service_uuids
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class _FakeClient:
    def __init__(self, device: _FakeDevice, disconnected_callback: Any = None) -> None:
        self.device = device
        self.disconnected_callback = disconnected_callback
        self.mtu_size = 247
        self.connected = False
        self.notify_cb: Any = None
        self.writes: list[tuple[str, bytes, bool]] = []
        self.fail_wo_response = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def start_notify(self, uuid: str, cb: Any) -> None:
        assert uuid == TX_CHAR_UUID
        self.notify_cb = cb

    async def write_gatt_char(self, uuid: str, data: bytes, response: bool = False) -> None:
        assert uuid == RX_CHAR_UUID
        if self.fail_wo_response and not response:
            raise RuntimeError("WriteWithoutResponse unsupported")
        self.writes.append((uuid, bytes(data), response))

    def simulate_notify(self, data: bytes) -> None:
        assert self.notify_cb is not None
        self.notify_cb(TX_CHAR_UUID, bytearray(data))

    def simulate_disconnect(self) -> None:
        self.connected = False
        if self.disconnected_callback is not None:
            self.disconnected_callback(self)


def test_parse_linkchat_tag_and_tie_breaker() -> None:
    assert parse_linkchat_tag("LC-1a2b") == "1a2b"
    assert parse_linkchat_tag("LC-FFFF") == "ffff"
    assert parse_linkchat_tag("LC-xyz1") is None
    assert parse_linkchat_tag("MyLaptop") is None

    dual = WindowsBleTransport("5000deadbeef0000")
    assert dual.local_tag == "5000"
    assert dual.should_initiate_central("LC-9000") is True
    assert dual.should_initiate_central("LC-1000") is False
    assert dual.should_initiate_central("Windows-PC") is True

    central_only = WindowsBleTransport("5000deadbeef0000", force_central_only=True)
    assert central_only.should_initiate_central("LC-1000") is True


async def test_peripheral_failure_falls_back_to_central_only_and_connects() -> None:
    scanners: list[_FakeScanner] = []
    clients: list[_FakeClient] = []
    mode_events: list[bool] = []

    def make_scanner(**kwargs: Any) -> _FakeScanner:
        s = _FakeScanner(**kwargs)
        scanners.append(s)
        return s

    def make_client(device: _FakeDevice, **kwargs: Any) -> _FakeClient:
        c = _FakeClient(device, **kwargs)
        clients.append(c)
        return c

    transport = WindowsBleTransport(
        "abcd111122223333",
        on_mode_changed=mode_events.append,
        scanner_factory=make_scanner,
        client_factory=make_client,
    )

    # Simulate peripheral startup rejection regardless of host Bluetooth hardware.
    async def fail_peripheral() -> bool:
        return False

    transport._start_peripheral = fail_peripheral  # type: ignore[method-assign]

    events: list[tuple[str, Any]] = []

    async def on_up(handle: str, mtu: int, rssi: int) -> None:
        events.append(("up", (handle, mtu, rssi)))

    async def on_down(handle: str) -> None:
        events.append(("down", handle))

    async def on_chunk(handle: str, data: bytes) -> None:
        events.append(("chunk", (handle, data)))

    transport.set_callbacks(on_up, on_down, on_chunk)
    await transport.start()

    try:
        assert transport.central_only is True
        assert transport.mode_label == "Central-Only"
        assert mode_events == [True]

        await asyncio.sleep(0.05)
        assert len(scanners) == 1
        assert scanners[0].started is True

        # Even though peer tag 0001 < abcd, Central-only mode still connects!
        dev = _FakeDevice(address="AA:BB:CC:DD:EE:FF", name="LC-0001")
        adv = _FakeAdv(local_name="LC-0001", service_uuids=[SERVICE_UUID], rssi=-58)
        scanners[0].detection_callback(dev, adv)
        await asyncio.sleep(0.05)

        assert len(clients) == 1
        handle = "ble-c:AA:BB:CC:DD:EE:FF"
        assert ("up", (handle, 247, -58)) in events

        # Outbound write (with fallback to response=True if unacked write fails)
        clients[0].fail_wo_response = True
        await transport.send_chunk(handle, b"hello-chunk")
        assert clients[0].writes == [(RX_CHAR_UUID, b"hello-chunk", True)]

        # Inbound notification
        clients[0].simulate_notify(b"reply-chunk")
        await asyncio.sleep(0.05)
        assert ("chunk", (handle, b"reply-chunk")) in events

        # Disconnect callback
        clients[0].simulate_disconnect()
        await asyncio.sleep(0.05)
        assert ("down", handle) in events
    finally:
        await transport.stop()


def _drain_matching(q: queue.Queue[Any], pred: Any, timeout: float = 4.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            ev = q.get(timeout=0.05)
        except queue.Empty:
            continue
        if pred(ev):
            return ev
    raise AssertionError("Expected event not received within timeout")


def test_backend_bridge_full_lifecycle(tmp_path: Path) -> None:
    hub = NetworkHub()
    from linkchat_core import LinkChatNode

    bridge = BackendBridge(
        data_dir=tmp_path / "win",
        nickname="WinLaptop",
        transport_factory=lambda: VirtualTransport("Win", hub),
    )
    bridge.start()
    phone: LinkChatNode | None = None
    try:
        assert bridge.wait_ready(timeout=4.0)
        ready = _drain_matching(bridge.events, lambda e: isinstance(e, NodeReadyEvent))
        assert ready.nickname == "WinLaptop"
        assert bridge._loop is not None

        async def _setup_phone_and_connect() -> LinkChatNode:
            p_transport = VirtualTransport("Phone", hub)
            p_node = LinkChatNode(tmp_path / "phone", p_transport, nickname="Phone")
            await p_node.start()
            await hub.connect("Win", "Phone", latency_ms=2.0)
            return p_node

        phone = asyncio.run_coroutine_threadsafe(
            _setup_phone_and_connect(), bridge._loop
        ).result(timeout=4.0)

        peer_ev = _drain_matching(
            bridge.events,
            lambda e: isinstance(e, PeerUpdatedEvent) and e.peer.nickname == "Phone",
        )
        phone_id = peer_ev.peer.node_id_hex

        # Public chat from Windows bridge -> Phone
        bridge.send_public("hello from windows")
        pub_ev = _drain_matching(
            bridge.events, lambda e: isinstance(e, PublicMessageEvent)
        )
        assert pub_ev.record.text == "hello from windows"

        # Encrypted DM + ACK delivery status update
        bridge.send_dm(phone_id, "secret dm")
        dm_ev = _drain_matching(bridge.events, lambda e: isinstance(e, DmReceivedEvent))
        assert dm_ev.record.text == "secret dm"

        ack_ev = _drain_matching(
            bridge.events,
            lambda e: isinstance(e, DmStatusChangedEvent)
            and e.msg_id == dm_ev.record.msg_id
            and e.status == DMStatus.DELIVERED.value,
        )
        assert ack_ev.status == DMStatus.DELIVERED.value

        # Fingerprint + verify + history queries
        bridge.request_fingerprint(phone_id)
        fp_ev = _drain_matching(
            bridge.events, lambda e: isinstance(e, FingerprintReadyEvent)
        )
        assert len(fp_ev.fingerprint.groups) == 6
        assert len(fp_ev.fingerprint.emojis) == 6

        bridge.verify_peer(phone_id, True)
        verified_ev = _drain_matching(
            bridge.events,
            lambda e: isinstance(e, PeerUpdatedEvent) and e.peer.verified is True,
        )
        assert verified_ev.peer.verified is True

        bridge.request_history(phone_id)
        hist_ev = _drain_matching(
            bridge.events,
            lambda e: isinstance(e, HistoryLoadedEvent) and e.channel == phone_id,
        )
        assert any(m.text == "secret dm" for m in hist_ev.messages)
    finally:
        if phone is not None and bridge._loop is not None and not bridge._loop.is_closed():
            asyncio.run_coroutine_threadsafe(phone.stop(), bridge._loop).result(
                timeout=4.0
            )
        bridge.stop()


async def test_closed_central_link_drops_cleanly_on_send_chunk() -> None:
    scanners: list[_FakeScanner] = []
    clients: list[_FakeClient] = []

    class _ClosingClient(_FakeClient):
        def __init__(self, device: _FakeDevice, disconnected_callback: Any = None) -> None:
            super().__init__(device, disconnected_callback=disconnected_callback)
            self.is_connected = True
            self.write_attempts = 0

        async def disconnect(self) -> None:
            self.is_connected = False
            await super().disconnect()

        async def write_gatt_char(
            self, uuid: str, data: bytes, response: bool = False
        ) -> None:
            self.write_attempts += 1
            raise OSError(22, "The object has been closed.", None, -2147483629)

    def make_scanner(**kwargs: Any) -> _FakeScanner:
        s = _FakeScanner(**kwargs)
        scanners.append(s)
        return s

    def make_client(device: _FakeDevice, **kwargs: Any) -> _ClosingClient:
        c = _ClosingClient(device, **kwargs)
        clients.append(c)
        return c

    transport = WindowsBleTransport(
        "abcd111122223333",
        force_central_only=True,
        scanner_factory=make_scanner,
        client_factory=make_client,
    )

    down_events: list[str] = []

    async def on_up(_handle: str, _mtu: int, _rssi: int) -> None:
        pass

    async def on_down(handle: str) -> None:
        down_events.append(handle)

    async def on_chunk(_handle: str, _data: bytes) -> None:
        pass

    transport.set_callbacks(on_up, on_down, on_chunk)
    await transport.start()
    try:
        await asyncio.sleep(0.05)
        dev = _FakeDevice(address="11:22:33:44:55:66", name="LC-0001")
        adv = _FakeAdv(local_name="LC-0001", service_uuids=[SERVICE_UUID], rssi=-55)
        scanners[0].detection_callback(dev, adv)
        await asyncio.sleep(0.05)

        handle = "ble-c:11:22:33:44:55:66"
        assert handle in transport._central_links

        with pytest.raises(OSError, match="The object has been closed"):
            await transport.send_chunk(handle, b"hello")

        # Should NOT retry write_gatt_char(response=True) on OSError.
        assert clients[0].write_attempts == 1
        assert down_events == [handle]
        assert handle not in transport._central_links
        assert "11:22:33:44:55:66" not in transport._central_by_addr
        assert clients[0].is_connected is False
    finally:
        await transport.stop()


async def test_disconnected_central_and_failing_peripheral_drop_on_send() -> None:
    scanners: list[_FakeScanner] = []
    clients: list[_FakeClient] = []

    class _FlagClient(_FakeClient):
        def __init__(self, device: _FakeDevice, disconnected_callback: Any = None) -> None:
            super().__init__(device, disconnected_callback=disconnected_callback)
            self.is_connected = True

    transport = WindowsBleTransport(
        "abcd111122223333",
        force_central_only=True,
        scanner_factory=lambda **kw: scanners.append(_FakeScanner(**kw)) or scanners[-1],
        client_factory=lambda dev, **kw: clients.append(_FlagClient(dev, **kw)) or clients[-1],
    )
    down_events: list[str] = []

    async def noop_up(_h: str, _m: int, _r: int) -> None:
        pass

    async def on_down(h: str) -> None:
        down_events.append(h)

    async def noop_chunk(_h: str, _d: bytes) -> None:
        pass

    transport.set_callbacks(noop_up, on_down, noop_chunk)
    await transport.start()
    try:
        await asyncio.sleep(0.05)
        dev = _FakeDevice(address="AA:11:22:33:44:55", name="LC-0002")
        adv = _FakeAdv(local_name="LC-0002", service_uuids=[SERVICE_UUID], rssi=-60)
        scanners[0].detection_callback(dev, adv)
        await asyncio.sleep(0.05)

        c_handle = "ble-c:AA:11:22:33:44:55"
        clients[0].is_connected = False
        with pytest.raises(ConnectionError):
            await transport.send_chunk(c_handle, b"ping")
        assert c_handle in down_events
        assert c_handle not in transport._central_links

        # Simulate a failing peripheral link
        from linkchat_win.ble_transport import _PeripheralLink

        p_handle = "ble-p:dev-1"
        transport._peripheral_links[p_handle] = _PeripheralLink(
            handle=p_handle, device_id="dev-1", mtu=247
        )

        async def fail_notify(_link: Any, _chunk: bytes) -> None:
            raise OSError("peripheral closed")

        transport._send_peripheral_notification = fail_notify  # type: ignore[method-assign]
        with pytest.raises(OSError, match="peripheral closed"):
            await transport.send_chunk(p_handle, b"pong")
        assert p_handle in down_events
        assert p_handle not in transport._peripheral_links
    finally:
        await transport.stop()


async def test_android_service_data_tag_respected_by_windows_tie_breaker() -> None:
    scanners: list[_FakeScanner] = []
    clients: list[_FakeClient] = []

    transport = WindowsBleTransport(
        "5000deadbeef0000",
        scanner_factory=lambda **kw: scanners.append(_FakeScanner(**kw)) or scanners[-1],
        client_factory=lambda dev, **kw: clients.append(_FakeClient(dev, **kw)) or clients[-1],
    )

    async def ok_peripheral() -> bool:
        return True

    transport._start_peripheral = ok_peripheral  # type: ignore[method-assign]

    async def noop_up(_h: str, _m: int, _r: int) -> None:
        pass

    async def noop_down(_h: str) -> None:
        pass

    async def noop_chunk(_h: str, _d: bytes) -> None:
        pass

    transport.set_callbacks(noop_up, noop_down, noop_chunk)
    await transport.start()
    try:
        await asyncio.sleep(0.02)

        # Android advertises LC-<4hex> in ScanResponse service_data with no local_name.
        smaller_android = _FakeDevice(address="11:11:11:11:11:11", name="Pixel 8")
        smaller_adv = _FakeAdv(
            local_name=None,
            service_uuids=[SERVICE_UUID],
            service_data={SERVICE_UUID.upper(): b"LC-1000"},
            rssi=-55,
        )
        scanners[0].detection_callback(smaller_android, smaller_adv)
        await asyncio.sleep(0.05)
        # 5000 > 1000 -> Windows backs off and lets Android initiate Central.
        assert len(clients) == 0

        larger_android = _FakeDevice(address="22:22:22:22:22:22", name="Pixel 9")
        larger_adv = _FakeAdv(
            local_name=None,
            service_uuids=[SERVICE_UUID],
            service_data={SERVICE_UUID: b"LC-9000"},
            rssi=-58,
        )
        scanners[0].detection_callback(larger_android, larger_adv)
        await asyncio.sleep(0.05)
        # 5000 <= 9000 -> Windows initiates Central connection.
        assert len(clients) == 1
        assert clients[0].device.address == "22:22:22:22:22:22"
    finally:
        await transport.stop()


def test_backend_bridge_reset_all_clears_state_and_emits_new_identity(
    tmp_path: Path,
) -> None:
    hub = NetworkHub()
    bridge = BackendBridge(
        data_dir=tmp_path / "win",
        nickname="WinLaptop",
        transport_factory=lambda: VirtualTransport("Win", hub),
    )
    bridge.start()
    try:
        assert bridge.wait_ready(timeout=5.0)
        ready = None
        while True:
            ev = bridge.events.get(timeout=2.0)
            if isinstance(ev, NodeReadyEvent):
                ready = ev
                break
        assert ready is not None
        assert ready.nickname == "WinLaptop"

        bridge.send_public("hello before reset")
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            try:
                ev = bridge.events.get(timeout=0.1)
                if isinstance(ev, PublicMessageEvent):
                    break
            except queue.Empty:
                continue

        bridge.reset_all()
        reset_ev = None
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                ev = bridge.events.get(timeout=0.1)
                if isinstance(ev, NodeResetEvent):
                    reset_ev = ev
                    break
            except queue.Empty:
                continue

        assert reset_ev is not None
        assert reset_ev.node_id_hex != ready.node_id_hex
        assert reset_ev.short_tag == reset_ev.node_id_hex[:4]
        assert reset_ev.nickname == f"Node-{reset_ev.short_tag}"
        assert bridge.nickname is None

        # Persisted history is also cleared when requesting #public again.
        bridge.request_history("#public")
        hist_ev = None
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            try:
                ev = bridge.events.get(timeout=0.1)
                if isinstance(ev, HistoryLoadedEvent) and ev.channel == "#public":
                    hist_ev = ev
                    break
            except queue.Empty:
                continue
        assert hist_ev is not None
        assert hist_ev.messages == []
    finally:
        bridge.stop()


async def test_windows_ble_transport_clears_attempt_cooldown_on_stop() -> None:
    transport = WindowsBleTransport("abcd111122223333")

    async def ok_peripheral() -> bool:
        return True

    async def noop_up(_h: str, _m: int, _r: int) -> None:
        pass

    async def noop_down(_h: str) -> None:
        pass

    async def noop_chunk(_h: str, _d: bytes) -> None:
        pass

    transport._start_peripheral = ok_peripheral  # type: ignore[method-assign]
    transport._scanner_factory = lambda **kw: _FakeScanner(**kw)
    transport.set_callbacks(noop_up, noop_down, noop_chunk)

    await transport.start()
    transport._last_attempt["11:22:33:44:55:66"] = time.monotonic()
    await transport.stop()
    assert transport._last_attempt == {}


def test_apply_window_icon_uses_bundled_ico() -> None:
    from linkchat_win.ui.theme import apply_window_icon

    class _FakeWin:
        def __init__(self) -> None:
            self.called_with: str | None = None

        def iconbitmap(self, bitmap: str) -> None:
            self.called_with = bitmap

    win = _FakeWin()
    apply_window_icon(win)
    assert win.called_with is not None
    ico_path = Path(win.called_with)
    assert ico_path.is_file()
    assert ico_path.read_bytes()[:4] == b"\x00\x00\x01\x00"


async def test_windows_ble_transport_prunes_dead_links_and_disconnect_link() -> None:
    scanners: list[_FakeScanner] = []
    clients: list[_FakeClient] = []

    class _FlagClient(_FakeClient):
        def __init__(self, device: _FakeDevice, disconnected_callback: Any = None) -> None:
            super().__init__(device, disconnected_callback=disconnected_callback)
            self.is_connected = True

        async def disconnect(self) -> None:
            self.is_connected = False
            await super().disconnect()

    transport = WindowsBleTransport(
        "abcd111122223333",
        force_central_only=True,
        scanner_factory=lambda **kw: scanners.append(_FakeScanner(**kw)) or scanners[-1],
        client_factory=lambda dev, **kw: clients.append(_FlagClient(dev, **kw)) or clients[-1],
    )
    down_events: list[str] = []

    async def noop_up(_h: str, _m: int, _r: int) -> None:
        pass

    async def on_down(h: str) -> None:
        down_events.append(h)

    async def noop_chunk(_h: str, _d: bytes) -> None:
        pass

    transport.set_callbacks(noop_up, on_down, noop_chunk)
    await transport.start()
    try:
        await asyncio.sleep(0.05)
        dev = _FakeDevice(address="AA:11:22:33:44:99", name="LC-0009")
        adv = _FakeAdv(local_name="LC-0009", service_uuids=[SERVICE_UUID], rssi=-60)
        scanners[0].detection_callback(dev, adv)
        await asyncio.sleep(0.05)

        c_handle = "ble-c:AA:11:22:33:44:99"
        assert c_handle in transport._central_links

        # Drop central link via _prune_dead_links without disconnected_callback firing
        clients[0].is_connected = False
        await transport._prune_dead_links()
        assert c_handle in down_events
        assert c_handle not in transport._central_links

        # Drop WinRT peripheral link when no longer in subscribed_clients, and close session via disconnect_link
        from linkchat_win.ble_transport import _PeripheralLink

        class _FakeSession:
            def __init__(self, dev_id: str) -> None:
                self.device_id = type("DevId", (), {"id": dev_id})()
                self.closed = False

            def close(self) -> None:
                self.closed = True

        class _FakeSub:
            def __init__(self, dev_id: str) -> None:
                self.session = _FakeSession(dev_id)

        class _FakeTxChar:
            def __init__(self) -> None:
                self.subscribed_clients: list[Any] = []

        sub1 = _FakeSub("dev-1")
        sub2 = _FakeSub("dev-2")
        tx_char = _FakeTxChar()
        tx_char.subscribed_clients = [sub2]
        transport._winrt_tx_char = tx_char
        transport._peripheral_links["ble-p:dev-1"] = _PeripheralLink(
            handle="ble-p:dev-1", device_id="dev-1", mtu=247, subscribed_client=sub1
        )
        transport._peripheral_links["ble-p:dev-2"] = _PeripheralLink(
            handle="ble-p:dev-2", device_id="dev-2", mtu=247, subscribed_client=sub2
        )

        await transport._prune_dead_links()
        assert "ble-p:dev-1" in down_events
        assert "ble-p:dev-1" not in transport._peripheral_links
        assert "ble-p:dev-2" in transport._peripheral_links

        await transport.disconnect_link("ble-p:dev-2")
        assert sub2.session.closed is True
        assert "ble-p:dev-2" in down_events
        assert "ble-p:dev-2" not in transport._peripheral_links
    finally:
        await transport.stop()


def test_windows_peer_radar_skips_redraw_on_heartbeat_and_updates_in_place() -> None:
    from dataclasses import replace
    from linkchat_core import PeerInfo
    from linkchat_win.ui.main_window import MainWindow

    class _FakeWidget:
        def __init__(self) -> None:
            self.configured: dict[str, Any] = {}
            self.destroyed = False
            self.grid_visible = True

        def configure(self, **kwargs: Any) -> None:
            self.configured.update(kwargs)

        def winfo_exists(self) -> bool:
            return not self.destroyed

        def destroy(self) -> None:
            self.destroyed = True

        def grid(self, **_kwargs: Any) -> None:
            self.grid_visible = True

        def grid_remove(self) -> None:
            self.grid_visible = False

    class _FakeContainer:
        def __init__(self) -> None:
            self.children: list[_FakeWidget] = []

        def winfo_children(self) -> list[_FakeWidget]:
            return [c for c in self.children if not c.destroyed]

    win = MainWindow.__new__(MainWindow)
    win._lang = "en"
    win._own_node_id = "0000111122223333"
    win._active_channel = "#public"
    win._peers = {}
    win._peer_cards = {}
    win._rendered_peer_order = []
    win._empty_radar_label = None
    win._unread_counts = {}
    win._radar_title = _FakeWidget()  # type: ignore[assignment]
    win._connecting_badge = _FakeWidget()  # type: ignore[assignment]
    win._public_btn = _FakeWidget()  # type: ignore[assignment]
    win._peer_list_frame = _FakeContainer()  # type: ignore[assignment]

    render_calls = 0
    clear_calls = 0

    def _fake_render(_idx: int, peer: PeerInfo) -> dict[str, Any]:
        nonlocal render_calls
        render_calls += 1
        card = _FakeWidget()
        win._peer_list_frame.children.append(card)  # type: ignore[attr-defined]
        widgets = {
            "card": card,
            "name_lbl": _FakeWidget(),
            "trust_lbl": _FakeWidget(),
            "hop_lbl": _FakeWidget(),
            "rssi_lbl": _FakeWidget(),
        }
        win._update_peer_card(widgets, peer)
        return widgets

    orig_clear = MainWindow._clear_peer_radar_widgets.__get__(win, MainWindow)

    def _tracked_clear() -> None:
        nonlocal clear_calls
        clear_calls += 1
        orig_clear()

    win._render_peer_card = _fake_render  # type: ignore[method-assign]
    win._clear_peer_radar_widgets = _tracked_clear  # type: ignore[method-assign]

    peer1 = PeerInfo(
        node_id=b"\xaa" * 8,
        node_id_hex="aa" * 8,
        nickname="Phone",
        ed25519_pub=b"\x01" * 32,
        x25519_pub=b"\x02" * 32,
        hop_count=1,
        rssi=-55,
        direct=True,
        connected=True,
        verified=False,
        key_changed=False,
        last_seen=100.0,
        link_handle="ble-c:11",
    )

    # First discovery creates the card once.
    win._on_peer_updated(peer1)
    assert render_calls == 1
    assert clear_calls == 1
    card_obj = win._peer_cards[peer1.node_id_hex]["card"]

    # Heartbeat refresh only bumps last_seen -> no redraw, no card destruction.
    win._on_peer_updated(replace(peer1, last_seen=105.0))
    win._on_peer_updated(replace(peer1, last_seen=110.0))
    assert render_calls == 1
    assert clear_calls == 1
    assert card_obj.destroyed is False

    # RSSI change updates the existing card in place without destroying/rebuilding it.
    win._on_peer_updated(replace(peer1, last_seen=115.0, rssi=-64))
    assert render_calls == 1
    assert clear_calls == 1
    assert card_obj.destroyed is False
    assert "-64" in win._peer_cards[peer1.node_id_hex]["rssi_lbl"].configured["text"]

    # Going offline updates in place when order doesn't change, keeping card intact.
    win._on_peer_updated(replace(peer1, connected=False, direct=False, link_handle=None))
    assert render_calls == 1
    assert clear_calls == 1
    assert card_obj.destroyed is False
    assert win._peer_cards[peer1.node_id_hex]["hop_lbl"].configured["text"] == "Offline"


async def test_windows_ble_transport_blocks_and_drops_lc_tags() -> None:
    assert is_peer_blocked("ABCD", {"abcd", "1234"}) is True
    assert is_peer_blocked("9999", {"abcd"}) is False
    assert is_peer_blocked(None, {"abcd"}) is False

    scanners: list[_FakeScanner] = []
    clients: list[_FakeClient] = []

    class _FlagClient(_FakeClient):
        def __init__(self, device: _FakeDevice, disconnected_callback: Any = None) -> None:
            super().__init__(device, disconnected_callback=disconnected_callback)
            self.is_connected = True

        async def disconnect(self) -> None:
            self.is_connected = False
            await super().disconnect()

    transport = WindowsBleTransport(
        "abcd111122223333",
        force_central_only=True,
        connect_cooldown_sec=0.0,
        scanner_factory=lambda **kw: scanners.append(_FakeScanner(**kw)) or scanners[-1],
        client_factory=lambda dev, **kw: clients.append(_FlagClient(dev, **kw)) or clients[-1],
    )
    down_events: list[str] = []

    async def noop_up(_h: str, _m: int, _r: int) -> None:
        pass

    async def on_down(h: str) -> None:
        down_events.append(h)

    async def noop_chunk(_h: str, _d: bytes) -> None:
        pass

    transport.set_callbacks(noop_up, on_down, noop_chunk)
    await transport.start()
    try:
        await asyncio.sleep(0.05)

        # Blocked advertisement before connect is ignored.
        await transport.set_blocked_tags({"1111"})
        blocked_dev = _FakeDevice(address="AA:00:00:00:11:11", name="LC-1111")
        blocked_adv = _FakeAdv(local_name="LC-1111", service_uuids=[SERVICE_UUID], rssi=-50)
        scanners[0].detection_callback(blocked_dev, blocked_adv)
        await asyncio.sleep(0.05)
        assert len(clients) == 0

        # Allowed peer connects, then blocking its tag drops the active link.
        allowed_dev = _FakeDevice(address="AA:00:00:00:22:22", name="LC-2222")
        allowed_adv = _FakeAdv(local_name="LC-2222", service_uuids=[SERVICE_UUID], rssi=-52)
        scanners[0].detection_callback(allowed_dev, allowed_adv)
        await asyncio.sleep(0.05)
        assert len(clients) == 1
        c_handle = "ble-c:AA:00:00:00:22:22"
        assert c_handle in transport._central_links

        await transport.set_blocked_tags({"2222"})
        assert c_handle not in transport._central_links
        assert c_handle in down_events
        assert clients[0].is_connected is False

        # Peripheral link registered by tag is also dropped when blocked.
        from linkchat_win.ble_transport import _PeripheralLink

        class _FakeSession:
            def __init__(self) -> None:
                self.closed = False

            def close(self) -> None:
                self.closed = True

        class _FakeSub:
            def __init__(self) -> None:
                self.session = _FakeSession()

        sub = _FakeSub()
        p_handle = "ble-p:dev-99"
        transport._peripheral_links[p_handle] = _PeripheralLink(
            handle=p_handle, device_id="dev-99", mtu=247, subscribed_client=sub
        )
        await transport.register_peer_link_tag(p_handle, "9999")
        await transport.set_blocked_tags({"9999"})
        assert sub.session.closed is True
        assert p_handle not in transport._peripheral_links
        assert p_handle in down_events

        # Unblocking allows scan reconnect.
        await transport.set_blocked_tags(set())
        scanners[0].detection_callback(allowed_dev, allowed_adv)
        await asyncio.sleep(0.05)
        assert len(clients) == 2
        assert c_handle in transport._central_links
    finally:
        await transport.stop()


def test_windows_peer_radar_block_button_toggles_tag_and_notifies_bridge() -> None:
    from linkchat_core import PeerInfo
    from linkchat_win.ui.main_window import MainWindow

    class _FakeWidget:
        def __init__(self) -> None:
            self.configured: dict[str, Any] = {}
            self.destroyed = False
            self.grid_visible = True

        def configure(self, **kwargs: Any) -> None:
            self.configured.update(kwargs)

        def winfo_exists(self) -> bool:
            return not self.destroyed

        def destroy(self) -> None:
            self.destroyed = True

        def grid(self, **_kwargs: Any) -> None:
            self.grid_visible = True

        def grid_remove(self) -> None:
            self.grid_visible = False

    class _FakeBridge:
        def __init__(self) -> None:
            self.blocked_calls: list[set[str]] = []

        def set_blocked_tags(self, tags: set[str]) -> None:
            self.blocked_calls.append(set(tags))

    class _FakeContainer:
        def __init__(self) -> None:
            self.children: list[_FakeWidget] = []

        def winfo_children(self) -> list[_FakeWidget]:
            return [c for c in self.children if not c.destroyed]

    win = MainWindow.__new__(MainWindow)
    win.bridge = _FakeBridge()  # type: ignore[assignment]
    win._lang = "en"
    win._own_node_id = "0000111122223333"
    win._active_channel = "#public"
    win._peers = {}
    win._blocked_tags = set()
    win._peer_cards = {}
    win._rendered_peer_order = []
    win._empty_radar_label = None
    win._unread_counts = {}
    win._radar_title = _FakeWidget()  # type: ignore[assignment]
    win._connecting_badge = _FakeWidget()  # type: ignore[assignment]
    win._public_btn = _FakeWidget()  # type: ignore[assignment]
    win._peer_list_frame = _FakeContainer()  # type: ignore[assignment]

    def _fake_render(_idx: int, peer: PeerInfo) -> dict[str, Any]:
        card = _FakeWidget()
        win._peer_list_frame.children.append(card)  # type: ignore[attr-defined]
        widgets = {
            "card": card,
            "name_lbl": _FakeWidget(),
            "trust_lbl": _FakeWidget(),
            "hop_lbl": _FakeWidget(),
            "rssi_lbl": _FakeWidget(),
            "block_btn": _FakeWidget(),
        }
        win._update_peer_card(widgets, peer)
        return widgets

    win._render_peer_card = _fake_render  # type: ignore[method-assign]

    peer = PeerInfo(
        node_id=bytes.fromhex("a1b2c3d4e5f60708"),
        node_id_hex="a1b2c3d4e5f60708",
        nickname="AndroidPhone",
        ed25519_pub=b"\x01" * 32,
        x25519_pub=b"\x02" * 32,
        hop_count=1,
        rssi=-55,
        direct=True,
        connected=True,
        verified=False,
        key_changed=False,
        last_seen=100.0,
        link_handle="ble-c:11",
    )
    win._on_peer_updated(peer)
    btn = win._peer_cards[peer.node_id_hex]["block_btn"]
    assert btn.configured["text"] == "Block"

    win._toggle_block_tag("A1B2")
    assert win._blocked_tags == {"a1b2"}
    assert win.bridge.blocked_calls[-1] == {"a1b2"}
    assert btn.configured["text"] == "Blocked"

    win._toggle_block_tag("a1b2")
    assert win._blocked_tags == set()
    assert win.bridge.blocked_calls[-1] == set()
    assert btn.configured["text"] == "Block"
