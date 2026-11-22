"""Abstract TransportAdapter protocol and shared link/message data models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Protocol


class DMStatus(str, Enum):
    SENDING = "sending"
    RELAYED = "relayed"
    DELIVERED = "delivered"


@dataclass(slots=True)
class PeerInfo:
    node_id: bytes
    node_id_hex: str
    nickname: str
    ed25519_pub: bytes
    x25519_pub: bytes
    hop_count: int
    rssi: int
    direct: bool
    connected: bool
    verified: bool
    key_changed: bool
    last_seen: float
    link_handle: str | None = None
    blocked: bool = False


@dataclass(frozen=True, slots=True)
class MessageRecord:
    msg_id: str
    channel: str  # "#public" or peer node_id_hex
    origin_id: str
    target_id: str
    sender_nick: str
    text: str
    timestamp_ms: int
    is_outgoing: bool
    status: str
    hop_count: int


@dataclass(frozen=True, slots=True)
class LogEntry:
    timestamp_ms: int
    event_type: str
    message: str
    pkt_type: str = ""
    msg_id: str = ""
    origin_id: str = ""
    target_id: str = ""
    hop: int = 0
    ttl: int = 0


class TransportAdapter(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send_chunk(self, peer_handle: str, chunk: bytes) -> None: ...
    def set_callbacks(
        self,
        on_link_up: Callable[[str, int, int], Awaitable[None]],  # handle, mtu, rssi
        on_link_down: Callable[[str], Awaitable[None]],
        on_chunk: Callable[[str, bytes], Awaitable[None]],
    ) -> None: ...
