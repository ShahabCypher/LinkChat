"""High-level LinkChatNode async facade consumed by Windows, Android, and Simulator."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .identity import (
    SafetyFingerprint,
    compute_safety_fingerprint,
    normalize_node_id,
)
from .router import MeshRouter
from .storage import Storage
from .transport import LogEntry, MessageRecord, PeerInfo, TransportAdapter


class LinkChatNode:
    """Single async facade for LinkChat mesh identity, routing, and persistence."""

    def __init__(
        self,
        data_dir: str | Path,
        transport: TransportAdapter,
        nickname: str | None = None,
        stale_timeout_sec: float = 16.0,
        jitter_range: tuple[float, float] = (0.015, 0.060),
        hello_interval_sec: float = 5.0,
    ) -> None:
        self.storage = Storage(data_dir)
        self.identity, self._nickname = self.storage.load_or_create_identity(nickname)
        self.transport = transport
        self.router = MeshRouter(
            identity=self.identity,
            nickname=self._nickname,
            storage=self.storage,
            transport=transport,
            stale_timeout_sec=stale_timeout_sec,
            jitter_range=jitter_range,
            hello_interval_sec=hello_interval_sec,
        )

    @property
    def node_id(self) -> bytes:
        return self.identity.node_id

    @property
    def node_id_hex(self) -> str:
        return self.identity.node_id_hex

    @property
    def short_tag(self) -> str:
        return self.identity.short_tag

    @property
    def nickname(self) -> str:
        return self._nickname

    @property
    def on_peer_updated(self) -> Callable[[PeerInfo], Any] | None:
        return self.router.on_peer_updated

    @on_peer_updated.setter
    def on_peer_updated(self, cb: Callable[[PeerInfo], Any] | None) -> None:
        self.router.on_peer_updated = cb

    @property
    def on_public_message(self) -> Callable[[MessageRecord], Any] | None:
        return self.router.on_public_message

    @on_public_message.setter
    def on_public_message(self, cb: Callable[[MessageRecord], Any] | None) -> None:
        self.router.on_public_message = cb

    @property
    def on_dm_received(self) -> Callable[[MessageRecord], Any] | None:
        return self.router.on_dm_received

    @on_dm_received.setter
    def on_dm_received(self, cb: Callable[[MessageRecord], Any] | None) -> None:
        self.router.on_dm_received = cb

    @property
    def on_dm_status_changed(self) -> Callable[[str, str], Any] | None:
        return self.router.on_dm_status_changed

    @on_dm_status_changed.setter
    def on_dm_status_changed(self, cb: Callable[[str, str], Any] | None) -> None:
        self.router.on_dm_status_changed = cb

    @property
    def on_mesh_log(self) -> Callable[[LogEntry], Any] | None:
        return self.router.on_mesh_log

    @on_mesh_log.setter
    def on_mesh_log(self, cb: Callable[[LogEntry], Any] | None) -> None:
        self.router.on_mesh_log = cb

    async def start(self) -> None:
        await self.router.start()

    async def stop(self) -> None:
        await self.router.stop()
        self.storage.close()

    async def reset_all(self) -> None:
        """Wipe all persisted and in-memory state, rotate identity, and restart."""
        await self.router.stop()
        self.storage.wipe_and_reinit()
        self.identity, self._nickname = self.storage.load_or_create_identity(nickname=None)
        self.router.reset_state(self.identity, self._nickname)
        if hasattr(self.transport, "set_node_id"):
            self.transport.set_node_id(self.identity.node_id_hex)
        await self.router.start()

    async def set_nickname(self, name: str) -> None:
        self._nickname = name
        self.router.nickname = name
        self.storage.save_nickname(name)
        await self.router.broadcast_hello()

    async def send_public(self, text: str) -> MessageRecord:
        return await self.router.send_public(text)

    async def send_dm(self, target_id: bytes | str, text: str) -> MessageRecord:
        return await self.router.send_dm(normalize_node_id(target_id), text)

    def verify_peer(self, node_id: bytes | str, verified: bool = True) -> None:
        raw_id = normalize_node_id(node_id)
        self.storage.set_peer_verified(raw_id.hex(), verified)
        peer = self.router.peers.get(raw_id)
        if peer is not None:
            peer.verified = verified
            if verified:
                peer.key_changed = False

    def get_peers(self) -> list[PeerInfo]:
        return list(self.router.peers.values())

    def get_safety_fingerprint(self, node_id: bytes | str) -> SafetyFingerprint:
        raw_id = normalize_node_id(node_id)
        peer = self.router.peers.get(raw_id)
        if peer is None:
            raise KeyError(f"Unknown peer: {raw_id.hex()}")
        return compute_safety_fingerprint(self.identity.ed25519_pub, peer.ed25519_pub)

    def get_history(self, channel_or_peer: bytes | str, limit: int = 200) -> list[MessageRecord]:
        if channel_or_peer == "#public":
            channel = "#public"
        else:
            channel = normalize_node_id(channel_or_peer).hex()
        return self.storage.get_history(channel, limit=limit)
