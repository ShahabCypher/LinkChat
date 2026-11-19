"""Tests for the Android Chaquopy bridge (bridge.py) talking to linkchat_core."""

from __future__ import annotations

import asyncio
import json
import queue
import sys
import time
from pathlib import Path
from typing import Any

from linkchat_core import DMStatus, LinkChatNode
from linkchat_sim.virtual_transport import NetworkHub, VirtualTransport
from linkchat_win.app import BackendBridge, HistoryLoadedEvent, MeshLogEvent

BRIDGE_DIR = Path(__file__).resolve().parent.parent / "android" / "LinkChatAndroid" / "app" / "src" / "main" / "python"
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))

import bridge as android_bridge  # noqa: E402


class _EventCollector:
    def __init__(self) -> None:
        self.queue: queue.Queue[dict[str, Any]] = queue.Queue()

    def onEvent(self, event_json: str) -> None:
        self.queue.put(json.loads(event_json))


async def _wait_event(collector: _EventCollector, pred: Any, timeout: float = 4.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            ev = collector.queue.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.02)
            continue
        if pred(ev):
            return ev
    raise AssertionError("Expected bridge event not received within timeout")


class _PipeTransport:
    """Routes raw BLE chunks between a LinkChatNode and AndroidBridge."""

    def __init__(self, bridge_inst: android_bridge.AndroidBridge, peer_handle: str) -> None:
        self.bridge = bridge_inst
        self.peer_handle = peer_handle
        self._loop: asyncio.AbstractEventLoop | None = None
        self._on_link_up: Any = None
        self._on_link_down: Any = None
        self._on_chunk: Any = None

    def set_callbacks(self, on_link_up: Any, on_link_down: Any, on_chunk: Any) -> None:
        self._on_link_up = on_link_up
        self._on_link_down = on_link_down
        self._on_chunk = on_chunk

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()

    async def stop(self) -> None:
        return None

    async def send_chunk(self, peer_handle: str, chunk: bytes) -> None:
        self.bridge.on_chunk(self.peer_handle, chunk)

    def sendChunk(self, _peer_handle: str, chunk: bytes) -> None:
        if self._loop is not None and self._on_chunk is not None and not self._loop.is_closed():
            raw = bytes(chunk)
            self._loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._on_chunk(self.peer_handle, raw))
            )

    async def bring_up(self, mtu: int = 247, rssi: int = -55) -> None:
        self.bridge.on_link_up(self.peer_handle, mtu, rssi)
        await asyncio.sleep(0.05)
        if self._on_link_up is not None:
            await self._on_link_up(self.peer_handle, mtu, rssi)


def test_android_bridge_end_to_end_chunk_exchange(tmp_path: Path) -> None:
    bridge_inst = android_bridge.AndroidBridge()
    collector = _EventCollector()
    pipe = _PipeTransport(bridge_inst, "ble-c:AA:BB:CC:DD:EE:FF")

    ready_json = bridge_inst.start(
        data_dir=str(tmp_path / "android"),
        transport_sink=pipe,
        event_listener=collector,
        nickname="PixelPhone",
    )
    ready = json.loads(ready_json)
    assert ready["type"] == "node_ready"
    assert ready["nickname"] == "PixelPhone"
    assert len(ready["node_id_hex"]) == 16
    assert ready["short_tag"] == ready["node_id_hex"][:4]

    async def _run_peer_side() -> None:
        peer_node = LinkChatNode(tmp_path / "peer", pipe, nickname="WinLaptop")
        await peer_node.start()
        try:
            await pipe.bring_up(mtu=247, rssi=-52)

            peer_ev = await _wait_event(
                collector,
                lambda e: e.get("type") == "peer_updated"
                and e["peer"]["nickname"] == "WinLaptop",
            )
            win_id = peer_ev["peer"]["node_id_hex"]
            assert peer_ev["peer"]["direct"] is True
            assert peer_ev["peer"]["hop_count"] == 1

            # Public message Android -> peer
            bridge_inst.send_public("hello from android")
            pub_ev = await _wait_event(collector, lambda e: e.get("type") == "public_message")
            assert pub_ev["record"]["text"] == "hello from android"

            # Wait until peer node records the public message
            for _ in range(40):
                if any(m.text == "hello from android" for m in peer_node.get_history("#public")):
                    break
                await asyncio.sleep(0.05)
            assert any(m.text == "hello from android" for m in peer_node.get_history("#public"))

            # Encrypted DM Android -> peer + DM_ACK back
            bridge_inst.send_dm(win_id, "secret android dm")
            dm_ev = await _wait_event(collector, lambda e: e.get("type") == "dm_received")
            msg_id = dm_ev["record"]["msg_id"]

            ack_ev = await _wait_event(
                collector,
                lambda e: e.get("type") == "dm_status_changed"
                and e.get("msg_id") == msg_id
                and e.get("status") == DMStatus.DELIVERED.value,
            )
            assert ack_ev["status"] == DMStatus.DELIVERED.value

            # Safety fingerprint matches peer node symmetrically
            fp_android = json.loads(bridge_inst.get_safety_fingerprint(win_id))
            fp_peer = peer_node.get_safety_fingerprint(ready["node_id_hex"])
            assert fp_android["safety_number"] == fp_peer.safety_number
            assert fp_android["emojis"] == list(fp_peer.emojis)

            # Verify peer & check persisted history
            bridge_inst.verify_peer(win_id, True)
            verified_ev = await _wait_event(
                collector,
                lambda e: e.get("type") == "peer_updated" and e["peer"]["verified"] is True,
            )
            assert verified_ev["peer"]["verified"] is True

            hist = json.loads(bridge_inst.get_history(win_id))
            assert any(m["text"] == "secret android dm" for m in hist)

            peers_list = json.loads(bridge_inst.get_peers())
            assert len(peers_list) == 1 and peers_list[0]["node_id_hex"] == win_id

            bridge_inst.set_nickname("PixelRenamed")
            nick_ev = await _wait_event(collector, lambda e: e.get("type") == "nickname_changed")
            assert nick_ev["nickname"] == "PixelRenamed"
        finally:
            await peer_node.stop()

    try:
        asyncio.run(_run_peer_side())
    finally:
        bridge_inst.stop()


class _BridgeHubSink:
    """Bridges an AndroidBridge instance onto a VirtualTransport inside NetworkHub."""

    def __init__(self, bridge_inst: android_bridge.AndroidBridge, vtrans: VirtualTransport) -> None:
        self.bridge = bridge_inst
        self.vtrans = vtrans
        self.loop: asyncio.AbstractEventLoop | None = None

        async def _on_up(handle: str, mtu: int, rssi: int) -> None:
            self.bridge.on_link_up(handle, mtu, rssi)

        async def _on_down(handle: str) -> None:
            self.bridge.on_link_down(handle)

        async def _on_chunk(handle: str, data: bytes) -> None:
            self.bridge.on_chunk(handle, data)

        self.vtrans.set_callbacks(_on_up, _on_down, _on_chunk)

    def sendChunk(self, peer_handle: str, chunk: bytes) -> None:
        if self.loop is not None and not self.loop.is_closed():
            raw = bytes(chunk)
            asyncio.run_coroutine_threadsafe(
                self.vtrans.send_chunk(peer_handle, raw),
                self.loop,
            )


def test_cross_platform_three_node_android_windows_android_multihop(tmp_path: Path) -> None:
    """Verify PhoneA (AndroidBridge) <-> WinLaptop (BackendBridge) <-> PhoneB (AndroidBridge)."""
    hub = NetworkHub()
    win_bridge = BackendBridge(
        data_dir=tmp_path / "win",
        nickname="WinLaptop",
        transport_factory=lambda: VirtualTransport("WinLaptop", hub),
    )
    phone_a = android_bridge.AndroidBridge()
    phone_b = android_bridge.AndroidBridge()
    col_a = _EventCollector()
    col_b = _EventCollector()

    vt_a = VirtualTransport("PhoneA", hub)
    vt_b = VirtualTransport("PhoneB", hub)
    sink_a = _BridgeHubSink(phone_a, vt_a)
    sink_b = _BridgeHubSink(phone_b, vt_b)

    win_bridge.start()
    try:
        assert win_bridge.wait_ready(timeout=4.0)
        assert win_bridge._loop is not None
        sink_a.loop = win_bridge._loop
        sink_b.loop = win_bridge._loop

        ready_a = json.loads(
            phone_a.start(str(tmp_path / "phone_a"), sink_a, col_a, nickname="PhoneA")
        )
        ready_b = json.loads(
            phone_b.start(str(tmp_path / "phone_b"), sink_b, col_b, nickname="PhoneB")
        )

        async def _connect_chain() -> None:
            await vt_a.start()
            await vt_b.start()
            await hub.connect("PhoneA", "WinLaptop", latency_ms=2.0, mtu=247, rssi=-54)
            await hub.connect("WinLaptop", "PhoneB", latency_ms=2.0, mtu=247, rssi=-56)

        asyncio.run_coroutine_threadsafe(_connect_chain(), win_bridge._loop).result(timeout=4.0)

        async def _verify() -> None:
            b_ev = await _wait_event(
                col_a,
                lambda e: e.get("type") == "peer_updated"
                and e["peer"]["node_id_hex"] == ready_b["node_id_hex"]
                and e["peer"]["connected"] is True,
            )
            assert b_ev["peer"]["direct"] is False
            assert b_ev["peer"]["hop_count"] == 2

            await _wait_event(
                col_b,
                lambda e: e.get("type") == "peer_updated"
                and e["peer"]["node_id_hex"] == ready_a["node_id_hex"]
                and e["peer"]["connected"] is True,
            )

            # Symmetric safety fingerprints across PhoneA and PhoneB
            fp_a = json.loads(phone_a.get_safety_fingerprint(ready_b["node_id_hex"]))
            fp_b = json.loads(phone_b.get_safety_fingerprint(ready_a["node_id_hex"]))
            assert fp_a["safety_number"] == fp_b["safety_number"]
            assert fp_a["emojis"] == fp_b["emojis"]

            # Public chat PhoneA -> WinLaptop -> PhoneB
            phone_a.send_public("hello across windows")
            pub_b = await _wait_event(
                col_b,
                lambda e: e.get("type") == "public_message"
                and e["record"]["text"] == "hello across windows",
            )
            assert pub_b["record"]["hop_count"] == 2

            # E2EE DM PhoneA -> WinLaptop -> PhoneB + DM_ACK back
            phone_a.send_dm(ready_b["node_id_hex"], "secret via laptop")
            dm_a = await _wait_event(
                col_a,
                lambda e: e.get("type") == "dm_received"
                and e["record"]["text"] == "secret via laptop",
            )
            dm_b = await _wait_event(
                col_b,
                lambda e: e.get("type") == "dm_received"
                and e["record"]["text"] == "secret via laptop",
            )
            assert dm_b["record"]["hop_count"] == 2

            ack_a = await _wait_event(
                col_a,
                lambda e: e.get("type") == "dm_status_changed"
                and e.get("msg_id") == dm_a["record"]["msg_id"]
                and e.get("status") == DMStatus.DELIVERED.value,
            )
            assert ack_a["status"] == DMStatus.DELIVERED.value

            # Confirm WinLaptop relayed encrypted DM without decrypting it
            win_bridge.request_history(ready_b["node_id_hex"])
            relayed = False
            history_checked = False
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and not (relayed and history_checked):
                try:
                    ev = win_bridge.events.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.02)
                    continue
                if isinstance(ev, MeshLogEvent) and ev.entry.event_type == "RELAY_DM":
                    relayed = True
                elif isinstance(ev, HistoryLoadedEvent) and ev.channel == ready_b["node_id_hex"]:
                    assert len(ev.messages) == 0
                    history_checked = True
            assert relayed is True
            assert history_checked is True

        asyncio.run(_verify())
    finally:
        phone_a.stop()
        phone_b.stop()
        win_bridge.stop()


def test_android_bridge_reset_all_rotates_identity_and_clears_history(
    tmp_path: Path,
) -> None:
    bridge_inst = android_bridge.AndroidBridge()
    collector = _EventCollector()
    pipe = _PipeTransport(bridge_inst, "ble-c:AA:BB:CC:DD:EE:FF")

    ready = json.loads(
        bridge_inst.start(
            data_dir=str(tmp_path / "android"),
            transport_sink=pipe,
            event_listener=collector,
            nickname="PixelPhone",
        )
    )
    try:
        bridge_inst.send_public("before android reset")
        asyncio.run(
            _wait_event(collector, lambda e: e.get("type") == "public_message")
        )
        assert len(json.loads(bridge_inst.get_history("#public"))) == 1

        reset_payload = json.loads(bridge_inst.reset_all())
        assert reset_payload["type"] == "node_reset"
        assert reset_payload["node_id_hex"] != ready["node_id_hex"]
        assert reset_payload["short_tag"] == reset_payload["node_id_hex"][:4]
        assert reset_payload["nickname"] == f"Node-{reset_payload['short_tag']}"
        assert reset_payload["peers"] == []
        assert reset_payload["public_history"] == []

        own_info = json.loads(bridge_inst.get_own_info())
        assert own_info["node_id_hex"] == reset_payload["node_id_hex"]
        assert json.loads(bridge_inst.get_peers()) == []
        assert json.loads(bridge_inst.get_history("#public")) == []
    finally:
        bridge_inst.stop()
