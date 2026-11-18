"""Pure-Python shared core for LinkChat."""

from .identity import (
    Identity,
    SafetyFingerprint,
    compute_node_id,
    compute_safety_fingerprint,
    normalize_node_id,
)
from .node import LinkChatNode
from .protocol import (
    BROADCAST_TARGET,
    DEFAULT_TTL,
    HEADER_SIZE,
    MAX_PACKET_SIZE,
    MAX_TTL,
    PROTOCOL_VERSION,
    RX_CHAR_UUID,
    SERVICE_UUID,
    TX_CHAR_UUID,
    ChunkAssembler,
    PacketHeader,
    PacketType,
    ProtocolError,
)
from .transport import (
    DMStatus,
    LogEntry,
    MessageRecord,
    PeerInfo,
    TransportAdapter,
)

__all__ = [
    "BROADCAST_TARGET",
    "ChunkAssembler",
    "DEFAULT_TTL",
    "DMStatus",
    "HEADER_SIZE",
    "Identity",
    "LinkChatNode",
    "LogEntry",
    "MAX_PACKET_SIZE",
    "MAX_TTL",
    "MessageRecord",
    "PROTOCOL_VERSION",
    "PacketHeader",
    "PacketType",
    "PeerInfo",
    "ProtocolError",
    "RX_CHAR_UUID",
    "SERVICE_UUID",
    "SafetyFingerprint",
    "TX_CHAR_UUID",
    "TransportAdapter",
    "compute_node_id",
    "compute_safety_fingerprint",
    "normalize_node_id",
]
