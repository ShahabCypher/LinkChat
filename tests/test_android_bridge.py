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
