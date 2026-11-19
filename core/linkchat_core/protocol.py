"""Binary wire protocol codec and MTU ChunkAssembler."""

from __future__ import annotations

import os
import struct
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Union

SERVICE_UUID = "7b4e1000-8f2a-4c3b-9d1e-4c696e6b4368"
RX_CHAR_UUID = "7b4e1001-8f2a-4c3b-9d1e-4c696e6b4368"
TX_CHAR_UUID = "7b4e1002-8f2a-4c3b-9d1e-4c696e6b4368"

PROTOCOL_VERSION = 0x01
HEADER_SIZE = 28
HEADER_STRUCT = struct.Struct("!BB8s8s8sBB")
DEFAULT_TTL = 5
MAX_TTL = 7
BROADCAST_TARGET = b"\x00" * 8
MAX_PACKET_SIZE = 4096

CHUNK_HEADER_STRUCT = struct.Struct("!BHBB")
CHUNK_HEADER_SIZE = CHUNK_HEADER_STRUCT.size  # 5 bytes
CHUNK_FLAG_SINGLE = 0x01
CHUNK_TIMEOUT_SEC = 5.0


class ProtocolError(ValueError):
    """Raised when a binary packet or chunk is malformed or violates bounds."""


class PacketType(IntEnum):
    HELLO = 0x01
    CHAT_PUBLIC = 0x02
    CHAT_DM = 0x03
    DM_ACK = 0x04
    SYNC_DIGEST = 0x05
    SYNC_REQ = 0x06


@dataclass(frozen=True, slots=True)
class PacketHeader:
    pkt_type: PacketType
    origin_id: bytes
    target_id: bytes = BROADCAST_TARGET
    ttl: int = DEFAULT_TTL
    hop: int = 0
    msg_id: bytes = field(default_factory=lambda: os.urandom(8))
    version: int = PROTOCOL_VERSION

    def encode(self) -> bytes:
        if self.version != PROTOCOL_VERSION:
            raise ProtocolError(f"unsupported version: {self.version}")
        if len(self.msg_id) != 8 or len(self.origin_id) != 8 or len(self.target_id) != 8:
            raise ProtocolError("msg_id, origin_id, and target_id must be 8 bytes")
        if not (0 <= self.ttl <= MAX_TTL):
            raise ProtocolError(f"ttl out of range: {self.ttl}")
        if not (0 <= self.hop <= 255):
            raise ProtocolError(f"hop out of range: {self.hop}")
        return HEADER_STRUCT.pack(
            self.version,
            int(self.pkt_type),
            self.msg_id,
            self.origin_id,
            self.target_id,
            self.ttl,
            self.hop,
        )

    @classmethod
    def decode(cls, data: bytes) -> PacketHeader:
        if len(data) < HEADER_SIZE:
            raise ProtocolError("packet shorter than 28-byte header")
        version, raw_type, msg_id, origin_id, target_id, ttl, hop = HEADER_STRUCT.unpack_from(
            data, 0
        )
        if version != PROTOCOL_VERSION:
            raise ProtocolError(f"unsupported protocol version: {version}")
        try:
            pkt_type = PacketType(raw_type)
        except ValueError as exc:
            raise ProtocolError(f"unknown packet type: {raw_type}") from exc
        if ttl > MAX_TTL:
            raise ProtocolError(f"ttl exceeds max ({MAX_TTL}): {ttl}")
        return cls(
            version=version,
            pkt_type=pkt_type,
            msg_id=msg_id,
            origin_id=origin_id,
            target_id=target_id,
            ttl=ttl,
            hop=hop,
        )


@dataclass(frozen=True, slots=True)
class HelloPayload:
    caps: int
    nickname: str
    ed25519_pub: bytes
    x25519_pub: bytes


@dataclass(frozen=True, slots=True)
class ChatPublicPayload:
    timestamp_ms: int
    text: str
    ed25519_sig: bytes


@dataclass(frozen=True, slots=True)
class ChatDmPayload:
    timestamp_ms: int
    nonce: bytes
    ciphertext: bytes


@dataclass(frozen=True, slots=True)
class DmAckPayload:
    acked_msg_id: bytes
    nonce: bytes
    ciphertext: bytes


@dataclass(frozen=True, slots=True)
class SyncDigestPayload:
    msg_ids: list[bytes]


@dataclass(frozen=True, slots=True)
class SyncReqPayload:
    msg_ids: list[bytes]


Payload = Union[
    HelloPayload,
    ChatPublicPayload,
    ChatDmPayload,
    DmAckPayload,
    SyncDigestPayload,
    SyncReqPayload,
]


@dataclass(frozen=True, slots=True)
class Packet:
    header: PacketHeader
    payload: Payload
    raw_header: bytes = b""


def _encode_sync_ids(msg_ids: list[bytes]) -> bytes:
    for mid in msg_ids:
        if len(mid) != 8:
            raise ProtocolError("sync msg_id must be 8 bytes")
    return struct.pack("!H", len(msg_ids)) + b"".join(msg_ids)


def _decode_sync_ids(body: bytes) -> list[bytes]:
    if len(body) < 2:
        raise ProtocolError("sync payload too short")
    (count,) = struct.unpack_from("!H", body, 0)
    expected = 2 + count * 8
    if len(body) != expected:
        raise ProtocolError("sync payload length mismatch")
    return [body[2 + i * 8 : 2 + (i + 1) * 8] for i in range(count)]


def encode_payload(pkt_type: PacketType, payload: Payload) -> bytes:
    if pkt_type == PacketType.HELLO and isinstance(payload, HelloPayload):
        nick_bytes = payload.nickname.encode("utf-8")
        if len(nick_bytes) > 255:
            raise ProtocolError("nickname exceeds 255 UTF-8 bytes")
        if len(payload.ed25519_pub) != 32 or len(payload.x25519_pub) != 32:
            raise ProtocolError("public keys must be 32 bytes")
        return (
            struct.pack("!BB", payload.caps & 0xFF, len(nick_bytes))
            + nick_bytes
            + payload.ed25519_pub
            + payload.x25519_pub
        )

    if pkt_type == PacketType.CHAT_PUBLIC and isinstance(payload, ChatPublicPayload):
        text_bytes = payload.text.encode("utf-8")
        if len(payload.ed25519_sig) != 64:
            raise ProtocolError("ed25519_sig must be 64 bytes")
        return (
            struct.pack("!QH", payload.timestamp_ms, len(text_bytes))
            + text_bytes
            + payload.ed25519_sig
        )

    if pkt_type == PacketType.CHAT_DM and isinstance(payload, ChatDmPayload):
        if len(payload.nonce) != 12 or len(payload.ciphertext) < 16:
            raise ProtocolError("invalid CHAT_DM nonce or ciphertext")
        return struct.pack("!Q", payload.timestamp_ms) + payload.nonce + payload.ciphertext

    if pkt_type == PacketType.DM_ACK and isinstance(payload, DmAckPayload):
        if len(payload.acked_msg_id) != 8 or len(payload.nonce) != 12 or len(payload.ciphertext) < 16:
            raise ProtocolError("invalid DM_ACK fields")
        return payload.acked_msg_id + payload.nonce + payload.ciphertext

    if pkt_type == PacketType.SYNC_DIGEST and isinstance(payload, SyncDigestPayload):
        return _encode_sync_ids(payload.msg_ids)

    if pkt_type == PacketType.SYNC_REQ and isinstance(payload, SyncReqPayload):
        return _encode_sync_ids(payload.msg_ids)

    raise ProtocolError(f"payload type mismatch for {pkt_type.name}")


def encode_packet(header: PacketHeader, payload: Payload) -> bytes:
    raw = header.encode() + encode_payload(header.pkt_type, payload)
    if len(raw) > MAX_PACKET_SIZE:
        raise ProtocolError(f"packet exceeds {MAX_PACKET_SIZE} bytes ({len(raw)})")
    return raw


def decode_packet(data: bytes) -> Packet:
    if len(data) > MAX_PACKET_SIZE:
        raise ProtocolError(f"packet exceeds {MAX_PACKET_SIZE} bytes")
    header = PacketHeader.decode(data)
    raw_header = data[:HEADER_SIZE]
    body = data[HEADER_SIZE:]

    if header.pkt_type == PacketType.HELLO:
        if len(body) < 2 + 64:
            raise ProtocolError("HELLO payload too short")
        caps, nick_len = struct.unpack_from("!BB", body, 0)
        if len(body) != 2 + nick_len + 64:
            raise ProtocolError("HELLO payload length mismatch")
        try:
            nickname = body[2 : 2 + nick_len].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("invalid UTF-8 nickname in HELLO") from exc
        ed_pub = body[2 + nick_len : 2 + nick_len + 32]
        x_pub = body[2 + nick_len + 32 :]
        payload: Payload = HelloPayload(caps=caps, nickname=nickname, ed25519_pub=ed_pub, x25519_pub=x_pub)

    elif header.pkt_type == PacketType.CHAT_PUBLIC:
        if len(body) < 10 + 64:
            raise ProtocolError("CHAT_PUBLIC payload too short")
        timestamp_ms, text_len = struct.unpack_from("!QH", body, 0)
        if len(body) != 10 + text_len + 64:
            raise ProtocolError("CHAT_PUBLIC payload length mismatch")
        try:
            text = body[10 : 10 + text_len].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("invalid UTF-8 text in CHAT_PUBLIC") from exc
        sig = body[10 + text_len :]
        payload = ChatPublicPayload(timestamp_ms=timestamp_ms, text=text, ed25519_sig=sig)

    elif header.pkt_type == PacketType.CHAT_DM:
        if len(body) < 8 + 12 + 16:
            raise ProtocolError("CHAT_DM payload too short")
        (timestamp_ms,) = struct.unpack_from("!Q", body, 0)
        payload = ChatDmPayload(
            timestamp_ms=timestamp_ms,
            nonce=body[8:20],
            ciphertext=body[20:],
        )

    elif header.pkt_type == PacketType.DM_ACK:
        if len(body) < 8 + 12 + 16:
            raise ProtocolError("DM_ACK payload too short")
        payload = DmAckPayload(
            acked_msg_id=body[:8],
            nonce=body[8:20],
            ciphertext=body[20:],
        )

    elif header.pkt_type == PacketType.SYNC_DIGEST:
        payload = SyncDigestPayload(msg_ids=_decode_sync_ids(body))

    elif header.pkt_type == PacketType.SYNC_REQ:
        payload = SyncReqPayload(msg_ids=_decode_sync_ids(body))

    else:  # pragma: no cover
        raise ProtocolError(f"unhandled packet type: {header.pkt_type}")

    return Packet(header=header, payload=payload, raw_header=raw_header)


def packet_with_hop(raw_packet: bytes, ttl: int, hop: int) -> bytes:
    """Return a copy of raw_packet with updated ttl (offset 26) and hop (offset 27)."""
    if len(raw_packet) < HEADER_SIZE:
        raise ProtocolError("packet shorter than header")
    if not (0 <= ttl <= MAX_TTL) or not (0 <= hop <= 255):
        raise ProtocolError("ttl or hop out of range")
    buf = bytearray(raw_packet)
    buf[26] = ttl
    buf[27] = hop
    return bytes(buf)


@dataclass(slots=True)
class _ReassemblyBuffer:
    total: int
    expected_seq: int
    created_at: float
    total_bytes: int
    parts: list[bytes]


class ChunkAssembler:
    """Fragments logical packets into ATT-sized chunks and reassembles inbound frames."""

    def __init__(self, timeout_sec: float = CHUNK_TIMEOUT_SEC) -> None:
        self.timeout_sec = timeout_sec
        self._next_frame_id: dict[str, int] = {}
        self._buffers: dict[tuple[str, int], _ReassemblyBuffer] = {}

    def _alloc_frame_id(self, peer_handle: str) -> int:
        fid = self._next_frame_id.get(peer_handle, 0)
        self._next_frame_id[peer_handle] = (fid + 1) & 0xFFFF
        return fid

    def chunk_packet(
        self, packet_bytes: bytes, mtu: int = 23, peer_handle: str = "__default__"
    ) -> list[bytes]:
        """Split packet_bytes into chunks sized to max(20, mtu - 3)."""
        if len(packet_bytes) > MAX_PACKET_SIZE:
            raise ProtocolError(f"packet exceeds {MAX_PACKET_SIZE} bytes")

        max_att_payload = max(20, mtu - 3)
        max_chunk_payload = max(1, max_att_payload - CHUNK_HEADER_SIZE)

        if len(packet_bytes) == 0:
            slices = [b""]
        else:
            slices = [
                packet_bytes[i : i + max_chunk_payload]
                for i in range(0, len(packet_bytes), max_chunk_payload)
            ]

        total = len(slices)
        if total > 255:
            raise ProtocolError(f"packet requires {total} chunks (max 255)")

        frame_id = self._alloc_frame_id(peer_handle)
        flags = CHUNK_FLAG_SINGLE if total == 1 else 0
        return [
            CHUNK_HEADER_STRUCT.pack(flags, frame_id, seq, total) + part
            for seq, part in enumerate(slices)
        ]

    def feed_chunk(
        self, peer_handle: str, chunk: bytes, now: float | None = None
    ) -> bytes | None:
        """Feed one raw chunk from peer_handle; return full packet bytes when complete."""
        ts = time.monotonic() if now is None else now
        self.purge_expired(ts)

        if len(chunk) < CHUNK_HEADER_SIZE:
            return None

        flags, frame_id, seq, total = CHUNK_HEADER_STRUCT.unpack_from(chunk, 0)
        payload = chunk[CHUNK_HEADER_SIZE:]

        if total == 0 or seq >= total:
            self._buffers.pop((peer_handle, frame_id), None)
            return None

        if (flags & CHUNK_FLAG_SINGLE) and total == 1 and seq == 0:
            self._buffers.pop((peer_handle, frame_id), None)
            return payload if len(payload) <= MAX_PACKET_SIZE else None

        key = (peer_handle, frame_id)
        buf = self._buffers.get(key)

        if buf is None:
            if seq != 0 or len(payload) > MAX_PACKET_SIZE:
                return None
            if total == 1:
                return payload
            self._buffers[key] = _ReassemblyBuffer(
                total=total,
                expected_seq=1,
                created_at=ts,
                total_bytes=len(payload),
                parts=[payload],
            )
            return None

        if total != buf.total or seq != buf.expected_seq:
            # Out-of-order or mismatched chunk: reject the incomplete frame immediately.
            del self._buffers[key]
            return None

        new_size = buf.total_bytes + len(payload)
        if new_size > MAX_PACKET_SIZE:
            del self._buffers[key]
            return None

        buf.parts.append(payload)
        buf.total_bytes = new_size
        buf.expected_seq += 1

        if buf.expected_seq == buf.total:
            del self._buffers[key]
            return b"".join(buf.parts)

        return None

    def purge_expired(self, now: float | None = None) -> int:
        """Drop incomplete frames older than timeout_sec; return number removed."""
        ts = time.monotonic() if now is None else now
        expired = [
            key
            for key, buf in self._buffers.items()
            if (ts - buf.created_at) > self.timeout_sec
        ]
        for key in expired:
            del self._buffers[key]
        return len(expired)

    def clear_peer(self, peer_handle: str) -> None:
        """Remove all buffered incomplete frames and frame counter for a disconnected link."""
        self._next_frame_id.pop(peer_handle, None)
        for key in [k for k in self._buffers if k[0] == peer_handle]:
            del self._buffers[key]

    def clear_all(self) -> None:
        """Reset all buffered incomplete frames and per-link frame counters."""
        self._next_frame_id.clear()
        self._buffers.clear()

    @property
    def pending_count(self) -> int:
        return len(self._buffers)
