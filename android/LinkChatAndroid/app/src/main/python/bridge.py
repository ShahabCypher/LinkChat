"""Thin Chaquopy bridge connecting Kotlin AndroidBleTransport/UI to LinkChatNode."""

from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import Future
from typing import Any, Awaitable, Callable

from linkchat_core import (
    LinkChatNode,
    LogEntry,
    MessageRecord,
    PeerInfo,
    SafetyFingerprint,
)


def _peer_to_dict(peer: PeerInfo) -> dict[str, Any]:
    return {
        "node_id_hex": peer.node_id_hex,
        "short_tag": peer.node_id_hex[:4],
        "nickname": peer.nickname,
        "hop_count": peer.hop_count,
        "rssi": peer.rssi,
        "direct": peer.direct,
        "connected": peer.connected,
        "verified": peer.verified,
        "key_changed": peer.key_changed,
        "last_seen": peer.last_seen,
        "link_handle": peer.link_handle,
        "blocked": peer.blocked,
    }


def _msg_to_dict(rec: MessageRecord) -> dict[str, Any]:
    return {
        "msg_id": rec.msg_id,
        "channel": rec.channel,
        "origin_id": rec.origin_id,
        "target_id": rec.target_id,
        "sender_nick": rec.sender_nick,
        "text": rec.text,
        "timestamp_ms": rec.timestamp_ms,
        "is_outgoing": rec.is_outgoing,
        "status": rec.status,
        "hop_count": rec.hop_count,
    }


def _log_to_dict(entry: LogEntry) -> dict[str, Any]:
    return {
        "timestamp_ms": entry.timestamp_ms,
        "event_type": entry.event_type,
        "message": entry.message,
        "pkt_type": entry.pkt_type,
        "msg_id": entry.msg_id,
        "origin_id": entry.origin_id,
        "target_id": entry.target_id,
        "hop": entry.hop,
        "ttl": entry.ttl,
    }


def _fp_to_dict(node_id_hex: str, fp: SafetyFingerprint) -> dict[str, Any]:
    return {
        "node_id_hex": node_id_hex,
        "safety_number": fp.safety_number,
        "emoji_hash": fp.emoji_hash,
        "groups": list(fp.groups),
        "emojis": list(fp.emojis),
    }


def _invoke_sink(obj: Any, camel_name: str, snake_name: str, *args: Any) -> Any:
    if obj is None:
        return None
    fn = getattr(obj, camel_name, None)
    if fn is None:
        fn = getattr(obj, snake_name, None)
    if fn is None:
        raise AttributeError(f"Bridge target missing {camel_name}/{snake_name}")
    return fn(*args)


class _BridgeTransport:
    """TransportAdapter delegating outbound chunks to Kotlin AndroidBleTransport."""

    def __init__(self, transport_sink: Any) -> None:
        self._sink = transport_sink
        self._on_link_up: Callable[[str, int, int], Awaitable[None]] | None = None
        self._on_link_down: Callable[[str], Awaitable[None]] | None = None
        self._on_chunk: Callable[[str, bytes], Awaitable[None]] | None = None

    def set_callbacks(
        self,
        on_link_up: Callable[[str, int, int], Awaitable[None]],
        on_link_down: Callable[[str], Awaitable[None]],
        on_chunk: Callable[[str, bytes], Awaitable[None]],
    ) -> None:
        self._on_link_up = on_link_up
        self._on_link_down = on_link_down
        self._on_chunk = on_chunk

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send_chunk(self, peer_handle: str, chunk: bytes) -> None:
        _invoke_sink(self._sink, "sendChunk", "send_chunk", peer_handle, bytes(chunk))

    async def disconnect_link(self, peer_handle: str) -> None:
        if hasattr(self._sink, "disconnectLink") or hasattr(self._sink, "disconnect_link"):
            _invoke_sink(self._sink, "disconnectLink", "disconnect_link", peer_handle)

    async def dispatch_link_up(self, handle: str, mtu: int, rssi: int) -> None:
        if self._on_link_up is not None:
            await self._on_link_up(handle, mtu, rssi)

    async def dispatch_link_down(self, handle: str) -> None:
        if self._on_link_down is not None:
            await self._on_link_down(handle)

    async def dispatch_chunk(self, handle: str, data: bytes) -> None:
        if self._on_chunk is not None:
            await self._on_chunk(handle, data)


class AndroidBridge:
    """Thread-safe asyncio host for LinkChatNode consumed by Kotlin via Chaquopy."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._ready_event = threading.Event()
        self._node: LinkChatNode | None = None
        self._transport: _BridgeTransport | None = None
        self._event_listener: Any = None
        self._startup_error: BaseException | None = None
        self._ready_json: str = ""

    def start(
        self,
        data_dir: str,
        transport_sink: Any,
        event_listener: Any,
        nickname: str | None = None,
        *,
        stale_timeout_sec: float = 16.0,
        jitter_range: tuple[float, float] = (0.015, 0.060),
    ) -> str:
        with self._lock:
            self._event_listener = event_listener
            if self._thread is not None and self._thread.is_alive() and self._node is not None:
                return self._ready_json

            self._ready_event.clear()
            self._startup_error = None
            self._ready_json = ""

            self._thread = threading.Thread(
                target=self._thread_main,
                args=(data_dir, transport_sink, nickname, stale_timeout_sec, jitter_range),
                name="linkchat-android-core",
                daemon=True,
            )
            self._thread.start()

        if not self._ready_event.wait(timeout=10.0):
            raise TimeoutError("Timed out starting LinkChatNode")
        if self._startup_error is not None:
            raise RuntimeError(f"LinkChatNode startup failed: {self._startup_error}") from self._startup_error
        return self._ready_json

    def set_event_listener(self, event_listener: Any) -> None:
        with self._lock:
            self._event_listener = event_listener

    def stop(self, timeout: float = 3.0) -> None:
        with self._lock:
            loop = self._loop
            stop_event = self._stop_event
            thread = self._thread
        if loop is not None and stop_event is not None and not loop.is_closed():
            loop.call_soon_threadsafe(stop_event.set)
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        with self._lock:
            self._thread = None
            self._node = None
            self._transport = None

    def _emit(self, payload: dict[str, Any]) -> None:
        listener = self._event_listener
        if listener is None:
            return
        encoded = json.dumps(payload, ensure_ascii=False)
        try:
            _invoke_sink(listener, "onEvent", "on_event", encoded)
        except Exception:
            pass

    def _thread_main(
        self,
        data_dir: str,
        transport_sink: Any,
        nickname: str | None,
        stale_timeout_sec: float,
        jitter_range: tuple[float, float],
    ) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(
                self._async_main(data_dir, transport_sink, nickname, stale_timeout_sec, jitter_range)
            )
        except BaseException as exc:
            self._startup_error = exc
            self._emit({"type": "error", "message": str(exc)})
            self._ready_event.set()
        finally:
            loop.close()
            self._loop = None

    async def _async_main(
        self,
        data_dir: str,
        transport_sink: Any,
        nickname: str | None,
        stale_timeout_sec: float,
        jitter_range: tuple[float, float],
    ) -> None:
        self._stop_event = asyncio.Event()
        transport = _BridgeTransport(transport_sink)
        self._transport = transport

        node = LinkChatNode(
            data_dir=data_dir,
            transport=transport,
            nickname=nickname,
            stale_timeout_sec=stale_timeout_sec,
            jitter_range=jitter_range,
        )
        node.on_peer_updated = lambda peer: self._emit(
            {"type": "peer_updated", "peer": _peer_to_dict(peer)}
        )
        node.on_public_message = lambda rec: self._emit(
            {"type": "public_message", "record": _msg_to_dict(rec)}
        )
        node.on_dm_received = lambda rec: self._emit(
            {"type": "dm_received", "record": _msg_to_dict(rec)}
        )
        node.on_dm_status_changed = lambda mid, st: self._emit(
            {"type": "dm_status_changed", "msg_id": mid, "status": st}
        )
        node.on_mesh_log = lambda entry: self._emit(
            {"type": "mesh_log", "entry": _log_to_dict(entry)}
        )
        self._node = node

        await node.start()

        ready_payload = {
            "type": "node_ready",
            "node_id_hex": node.node_id_hex,
            "short_tag": node.short_tag,
            "nickname": node.nickname,
            "peers": [_peer_to_dict(p) for p in node.get_peers()],
            "public_history": [_msg_to_dict(m) for m in node.get_history("#public")],
        }
        self._ready_json = json.dumps(ready_payload, ensure_ascii=False)
        self._emit(ready_payload)
        self._ready_event.set()

        await self._stop_event.wait()
        await node.stop()
        self._node = None
        self._transport = None

    def _submit(self, coro_factory: Callable[[], Awaitable[Any]]) -> Future[Any] | None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return None

        async def _runner() -> Any:
            try:
                return await coro_factory()
            except Exception as exc:
                self._emit({"type": "error", "message": str(exc)})
                return None

        return asyncio.run_coroutine_threadsafe(_runner(), loop)

    def _call_sync(self, fn: Callable[[LinkChatNode], Any], timeout: float = 5.0) -> Any:
        loop = self._loop
        if loop is None or loop.is_closed():
            raise RuntimeError("LinkChatNode is not running")

        async def _runner() -> Any:
            if self._node is None:
                raise RuntimeError("LinkChatNode is not initialized")
            res = fn(self._node)
            if asyncio.iscoroutine(res):
                return await res
            return res

        return asyncio.run_coroutine_threadsafe(_runner(), loop).result(timeout=timeout)

    def on_link_up(self, handle: str, mtu: int, rssi: int) -> None:
        transport = self._transport
        if transport is None:
            return
        self._submit(lambda: transport.dispatch_link_up(str(handle), int(mtu), int(rssi)))

    def on_link_down(self, handle: str) -> None:
        transport = self._transport
        if transport is None:
            return
        self._submit(lambda: transport.dispatch_link_down(str(handle)))

    def on_chunk(self, handle: str, data: bytes | bytearray) -> None:
        transport = self._transport
        if transport is None:
            return
        raw = bytes(data)
        self._submit(lambda: transport.dispatch_chunk(str(handle), raw))

    def send_public(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return

        async def _op() -> None:
            if self._node is None:
                return
            rec = await self._node.send_public(cleaned)
            self._emit({"type": "public_message", "record": _msg_to_dict(rec)})

        self._submit(_op)

    def send_dm(self, target_id_hex: str, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return

        async def _op() -> None:
            if self._node is None:
                return
            rec = await self._node.send_dm(target_id_hex, cleaned)
            self._emit({"type": "dm_received", "record": _msg_to_dict(rec)})

        self._submit(_op)

    def set_nickname(self, nickname: str) -> None:
        cleaned = nickname.strip()
        if not cleaned:
            return

        async def _op() -> None:
            if self._node is None:
                return
            await self._node.set_nickname(cleaned)
            self._emit({"type": "nickname_changed", "nickname": self._node.nickname})

        self._submit(_op)

    def verify_peer(self, node_id_hex: str, verified: bool = True) -> None:
        async def _op() -> None:
            if self._node is None:
                return
            self._node.verify_peer(node_id_hex, verified=bool(verified))
            peer = self._node.router.peers.get(bytes.fromhex(node_id_hex))
            if peer is not None:
                self._emit({"type": "peer_updated", "peer": _peer_to_dict(peer)})

        self._submit(_op)

    def set_peer_blocked(self, node_id_hex: str, blocked: bool = True) -> None:
        async def _op() -> None:
            if self._node is None:
                return
            self._node.set_peer_blocked(node_id_hex, blocked=bool(blocked))
            peer = self._node.router.peers.get(bytes.fromhex(node_id_hex))
            if peer is not None:
                self._emit({"type": "peer_updated", "peer": _peer_to_dict(peer)})

        self._submit(_op)

    def get_peers(self) -> str:
        peers = self._call_sync(lambda node: [_peer_to_dict(p) for p in node.get_peers()])
        return json.dumps(peers, ensure_ascii=False)

    def get_history(self, channel_or_peer: str, limit: int = 200) -> str:
        msgs = self._call_sync(
            lambda node: [_msg_to_dict(m) for m in node.get_history(channel_or_peer, limit=int(limit))]
        )
        return json.dumps(msgs, ensure_ascii=False)

    def get_safety_fingerprint(self, node_id_hex: str) -> str:
        fp = self._call_sync(lambda node: node.get_safety_fingerprint(node_id_hex))
        return json.dumps(_fp_to_dict(node_id_hex, fp), ensure_ascii=False)

    def get_own_info(self) -> str:
        info = self._call_sync(
            lambda node: {
                "node_id_hex": node.node_id_hex,
                "short_tag": node.short_tag,
                "nickname": node.nickname,
            }
        )
        return json.dumps(info, ensure_ascii=False)

    def reset_all(self) -> str:
        async def _do_reset(node: LinkChatNode) -> dict[str, Any]:
            await node.reset_all()
            ready_payload = {
                "type": "node_ready",
                "node_id_hex": node.node_id_hex,
                "short_tag": node.short_tag,
                "nickname": node.nickname,
                "peers": [],
                "public_history": [],
            }
            self._ready_json = json.dumps(ready_payload, ensure_ascii=False)
            reset_payload = {
                "type": "node_reset",
                "node_id_hex": node.node_id_hex,
                "short_tag": node.short_tag,
                "nickname": node.nickname,
                "peers": [],
                "public_history": [],
            }
            self._emit(reset_payload)
            return reset_payload

        payload = self._call_sync(_do_reset, timeout=10.0)
        return json.dumps(payload, ensure_ascii=False)


_default_bridge = AndroidBridge()


def start(
    data_dir: str,
    transport_sink: Any,
    event_listener: Any,
    nickname: str | None = None,
) -> str:
    return _default_bridge.start(data_dir, transport_sink, event_listener, nickname)


def set_event_listener(event_listener: Any) -> None:
    _default_bridge.set_event_listener(event_listener)


def stop() -> None:
    _default_bridge.stop()


def on_link_up(handle: str, mtu: int, rssi: int) -> None:
    _default_bridge.on_link_up(handle, mtu, rssi)


def on_link_down(handle: str) -> None:
    _default_bridge.on_link_down(handle)


def on_chunk(handle: str, data: bytes | bytearray) -> None:
    _default_bridge.on_chunk(handle, data)


def send_public(text: str) -> None:
    _default_bridge.send_public(text)


def send_dm(target_id_hex: str, text: str) -> None:
    _default_bridge.send_dm(target_id_hex, text)


def set_nickname(nickname: str) -> None:
    _default_bridge.set_nickname(nickname)


def verify_peer(node_id_hex: str, verified: bool = True) -> None:
    _default_bridge.verify_peer(node_id_hex, verified)


def set_peer_blocked(node_id_hex: str, blocked: bool = True) -> None:
    _default_bridge.set_peer_blocked(node_id_hex, blocked)


def get_peers() -> str:
    return _default_bridge.get_peers()


def get_history(channel_or_peer: str, limit: int = 200) -> str:
    return _default_bridge.get_history(channel_or_peer, limit)


def get_safety_fingerprint(node_id_hex: str) -> str:
    return _default_bridge.get_safety_fingerprint(node_id_hex)


def get_own_info() -> str:
    return _default_bridge.get_own_info()


def reset_all() -> str:
    return _default_bridge.reset_all()
