"""Tests for binary protocol encoding/decoding and MTU ChunkAssembler."""

from __future__ import annotations

import os
import pytest

from linkchat_core.protocol import (
    BROADCAST_TARGET,
    CHUNK_FLAG_SINGLE,
    HEADER_SIZE,
    MAX_PACKET_SIZE,
    ChunkAssembler,
    ChatDmPayload,
    ChatPublicPayload,
    DmAckPayload,
    HelloPayload,
    PacketHeader,
    PacketType,
    ProtocolError,
    SyncDigestPayload,
    SyncReqPayload,
    decode_packet,
    encode_packet,
    packet_with_hop,
)


def test_round_trip_all_packet_types() -> None:
    origin = os.urandom(8)
    target = os.urandom(8)
    ed_pub = os.urandom(32)
    x_pub = os.urandom(32)
    sig = os.urandom(64)
    nonce = os.urandom(12)
    ct = os.urandom(32)
    ids = [os.urandom(8), os.urandom(8), os.urandom(8)]

    cases = [
        (
            PacketHeader(PacketType.HELLO, origin, BROADCAST_TARGET, ttl=1, hop=0),
            HelloPayload(caps=0x01, nickname="Alice 🚀", ed25519_pub=ed_pub, x25519_pub=x_pub),
        ),
        (
            PacketHeader(PacketType.CHAT_PUBLIC, origin, BROADCAST_TARGET, ttl=5, hop=1),
            ChatPublicPayload(timestamp_ms=1730000000123, text="Hello Mesh!", ed25519_sig=sig),
        ),
        (
            PacketHeader(PacketType.CHAT_DM, origin, target, ttl=5, hop=2),
            ChatDmPayload(timestamp_ms=1730000000456, nonce=nonce, ciphertext=ct),
        ),
        (
            PacketHeader(PacketType.DM_ACK, origin, target, ttl=5, hop=0),
            DmAckPayload(acked_msg_id=ids[0], nonce=nonce, ciphertext=os.urandom(19)),
        ),
        (
            PacketHeader(PacketType.SYNC_DIGEST, origin, BROADCAST_TARGET, ttl=1, hop=0),
            SyncDigestPayload(msg_ids=ids),
        ),
        (
            PacketHeader(PacketType.SYNC_REQ, origin, BROADCAST_TARGET, ttl=1, hop=0),
            SyncReqPayload(msg_ids=ids[:2]),
        ),
    ]

    for hdr, payload in cases:
        raw = encode_packet(hdr, payload)
        assert len(raw) >= HEADER_SIZE
        decoded = decode_packet(raw)
        assert decoded.header == hdr
        assert decoded.payload == payload


def test_decode_rejects_malformed_packets() -> None:
    with pytest.raises(ProtocolError):
        decode_packet(b"\x01" * 10)  # too short

    hdr = PacketHeader(PacketType.SYNC_DIGEST, os.urandom(8), BROADCAST_TARGET, ttl=1)
    raw = bytearray(encode_packet(hdr, SyncDigestPayload(msg_ids=[os.urandom(8)])))

    bad_ver = bytearray(raw)
    bad_ver[0] = 0x02
    with pytest.raises(ProtocolError):
        decode_packet(bytes(bad_ver))

    bad_type = bytearray(raw)
    bad_type[1] = 0x7F
    with pytest.raises(ProtocolError):
        decode_packet(bytes(bad_type))

    bad_ttl = bytearray(raw)
    bad_ttl[26] = 99
    with pytest.raises(ProtocolError):
        decode_packet(bytes(bad_ttl))

    # Truncated sync payload
    with pytest.raises(ProtocolError):
        decode_packet(bytes(raw[:-2]))


def test_packet_with_hop_preserves_rest_of_packet() -> None:
    hdr = PacketHeader(PacketType.CHAT_PUBLIC, os.urandom(8), BROADCAST_TARGET, ttl=5, hop=0)
    raw = encode_packet(hdr, ChatPublicPayload(123456, "hi", os.urandom(64)))
    fwd = packet_with_hop(raw, ttl=4, hop=1)
    assert raw[:26] == fwd[:26]
    assert raw[28:] == fwd[28:]
    decoded = decode_packet(fwd)
    assert decoded.header.ttl == 4
    assert decoded.header.hop == 1


@pytest.mark.parametrize("mtu", [23, 247])
def test_chunk_assembler_round_trip(mtu: int) -> None:
    tx = ChunkAssembler()
    rx = ChunkAssembler()
    payload = os.urandom(650)

    chunks = tx.chunk_packet(payload, mtu=mtu, peer_handle="peer1")
    max_att = max(20, mtu - 3)
    assert all(len(c) <= max_att for c in chunks)
    if mtu == 23:
        assert len(chunks) > 1
        assert (chunks[0][0] & CHUNK_FLAG_SINGLE) == 0
    else:
        assert len(chunks) > 1

    assembled = None
    for ch in chunks:
        res = rx.feed_chunk("peer1", ch, now=100.0)
        if res is not None:
            assembled = res
    assert assembled == payload


def test_chunk_assembler_single_frame_shortcut() -> None:
    tx = ChunkAssembler()
    rx = ChunkAssembler()
    small = b"A" * 40
    chunks = tx.chunk_packet(small, mtu=247, peer_handle="p1")
    assert len(chunks) == 1
    assert (chunks[0][0] & CHUNK_FLAG_SINGLE) == CHUNK_FLAG_SINGLE
    assert rx.feed_chunk("p1", chunks[0], now=1.0) == small


def test_chunk_assembler_rejects_out_of_order() -> None:
    tx = ChunkAssembler()
    rx = ChunkAssembler()
    chunks = tx.chunk_packet(b"Z" * 100, mtu=23, peer_handle="p1")
    assert len(chunks) >= 3

    # Start with chunk 0, then skip chunk 1 -> chunk 2 causes immediate rejection
    assert rx.feed_chunk("p1", chunks[0], now=10.0) is None
    assert rx.pending_count == 1
    assert rx.feed_chunk("p1", chunks[2], now=10.1) is None
    assert rx.pending_count == 0

    # Non-zero first chunk is also rejected immediately
    assert rx.feed_chunk("p1", chunks[1], now=10.2) is None
    assert rx.pending_count == 0


def test_chunk_assembler_expires_incomplete_frames() -> None:
    tx = ChunkAssembler()
    rx = ChunkAssembler(timeout_sec=5.0)
    chunks = tx.chunk_packet(b"B" * 100, mtu=23, peer_handle="p1")
    assert rx.feed_chunk("p1", chunks[0], now=10.0) is None
    assert rx.pending_count == 1

    # Before timeout
    assert rx.purge_expired(now=14.5) == 0
    assert rx.pending_count == 1

    # After 5s timeout
    assert rx.purge_expired(now=15.1) == 1
    assert rx.pending_count == 0


def test_chunk_assembler_rejects_oversized_packet() -> None:
    tx = ChunkAssembler()
    with pytest.raises(ProtocolError):
        tx.chunk_packet(b"X" * (MAX_PACKET_SIZE + 1), mtu=247)
