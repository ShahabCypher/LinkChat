"""Tests for multi-hop relay, cycle deduplication, TTL expiration, and E2EE DMs."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from linkchat_core import LinkChatNode, MessageRecord
from linkchat_core.crypto import sign_public_message
from linkchat_core.identity import Identity
from linkchat_core.protocol import (
    BROADCAST_TARGET,
    ChatPublicPayload,
    PacketHeader,
    PacketType,
    encode_packet,
)
from linkchat_sim.virtual_transport import NetworkHub, VirtualTransport


async def _wait_until(predicate, timeout: float = 4.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.015)
    raise AssertionError("Condition not met within timeout")


async def test_cyclic_graph_deduplication(tmp_path: Path) -> None:
    hub = NetworkHub()
    names = ["A", "B", "C"]
    nodes: dict[str, LinkChatNode] = {}
    received: dict[str, list[MessageRecord]] = {n: [] for n in names}

    for n in names:
        node = LinkChatNode(
            tmp_path / n,
            VirtualTransport(n, hub),
            nickname=n,
            jitter_range=(0.002, 0.005),
        )
        node.on_public_message = lambda rec, name=n: received[name].append(rec)
        await node.start()
        nodes[n] = node

    try:
        # Triangle A - B - C - A
        await hub.connect("A", "B", latency_ms=2.0)
        await hub.connect("B", "C", latency_ms=2.0)
        await hub.connect("C", "A", latency_ms=2.0)
        await _wait_until(lambda: all(len(n.get_peers()) == 2 for n in nodes.values()))

        await nodes["A"].send_public("cycle test")
        await _wait_until(
            lambda: len(received["B"]) == 1 and len(received["C"]) == 1
        )
        await asyncio.sleep(0.1)
        assert len(received["A"]) == 0
        assert len(received["B"]) == 1
        assert len(received["C"]) == 1
    finally:
        for node in nodes.values():
            await node.stop()


async def test_ttl_one_not_forwarded(tmp_path: Path) -> None:
    hub = NetworkHub()
    names = ["A", "B", "C"]
    nodes: dict[str, LinkChatNode] = {}
    received: dict[str, list[MessageRecord]] = {n: [] for n in names}

    for n in names:
        node = LinkChatNode(
            tmp_path / n,
            VirtualTransport(n, hub),
            nickname=n,
            jitter_range=(0.002, 0.005),
        )
        node.on_public_message = lambda rec, name=n: received[name].append(rec)
        await node.start()
        nodes[n] = node

    try:
        await hub.connect("A", "B", latency_ms=2.0)
        await hub.connect("B", "C", latency_ms=2.0)
        await _wait_until(lambda: all(len(n.get_peers()) == 2 for n in nodes.values()))

        # Send a valid signed CHAT_PUBLIC with ttl=1 directly from A's transport
        alice = nodes["A"]
        hdr = PacketHeader(
            pkt_type=PacketType.CHAT_PUBLIC,
            origin_id=alice.node_id,
            target_id=BROADCAST_TARGET,
            ttl=1,
            hop=0,
        )
        ts = int(time.time() * 1000)
        sig = sign_public_message(alice.identity, hdr.encode(), ts, b"ttl1-only")
        raw = encode_packet(hdr, ChatPublicPayload(ts, "ttl1-only", sig))
        await alice.router._send_to_all_links(raw)

        await _wait_until(lambda: len(received["B"]) == 1)
        await asyncio.sleep(0.1)
        assert len(received["C"]) == 0  # B must not forward ttl == 1
    finally:
        for node in nodes.values():
            await node.stop()


async def test_forged_public_message_is_dropped_not_relayed(tmp_path: Path) -> None:
    hub = NetworkHub()
    names = ["A", "B", "C"]
    nodes: dict[str, LinkChatNode] = {}
    received: dict[str, list[MessageRecord]] = {n: [] for n in names}

    for n in names:
        node = LinkChatNode(
            tmp_path / n,
            VirtualTransport(n, hub),
            nickname=n,
            jitter_range=(0.002, 0.005),
        )
        node.on_public_message = lambda rec, name=n: received[name].append(rec)
        await node.start()
        nodes[n] = node

    try:
        await hub.connect("A", "B", latency_ms=2.0)
        await hub.connect("B", "C", latency_ms=2.0)
        await _wait_until(lambda: all(len(n.get_peers()) == 2 for n in nodes.values()))

        spoof = Identity.generate()
        hdr = PacketHeader(
            pkt_type=PacketType.CHAT_PUBLIC,
            origin_id=nodes["A"].node_id,
            target_id=BROADCAST_TARGET,
            ttl=5,
            hop=0,
        )
        ts = int(time.time() * 1000)
        bad_sig = sign_public_message(spoof, hdr.encode(), ts, b"forged!")
        raw = encode_packet(hdr, ChatPublicPayload(ts, "forged!", bad_sig))
        await nodes["A"].router._send_to_all_links(raw)

        await asyncio.sleep(0.1)
        assert len(received["B"]) == 0
        assert len(received["C"]) == 0
    finally:
        for node in nodes.values():
            await node.stop()


async def test_five_node_linear_chain_public_and_e2ee_dm(tmp_path: Path) -> None:
    hub = NetworkHub()
    names = ["Alice", "Bob", "Carol", "Dave", "Eve"]
    nodes: dict[str, LinkChatNode] = {}
    pub: dict[str, list[MessageRecord]] = {n: [] for n in names}
    dm: dict[str, list[MessageRecord]] = {n: [] for n in names}
    statuses: list[tuple[str, str]] = []

    for n in names:
        node = LinkChatNode(
            tmp_path / n,
            VirtualTransport(n, hub),
            nickname=n,
            jitter_range=(0.002, 0.006),
        )
        node.on_public_message = lambda rec, name=n: pub[name].append(rec)
        node.on_dm_received = lambda rec, name=n: dm[name].append(rec)
        if n == "Alice":
            node.on_dm_status_changed = lambda mid, st: statuses.append((mid, st))
        await node.start()
        nodes[n] = node

    try:
        for a, b in zip(names, names[1:]):
            await hub.connect(a, b, latency_ms=2.0, mtu=23)  # force multi-chunk MTU 23

        await _wait_until(lambda: all(len(n.get_peers()) == 4 for n in nodes.values()))

        alice = nodes["Alice"]
        eve = nodes["Eve"]
        eve_peer = next(p for p in alice.get_peers() if p.node_id == eve.node_id)
        assert eve_peer.hop_count == 4

        await alice.send_public("hello 5-node mesh")
        await _wait_until(lambda: all(len(pub[n]) == 1 for n in names[1:]))
        assert pub["Eve"][0].hop_count == 4

        dm_rec = await alice.send_dm(eve.node_id, "secret for eve")
        await _wait_until(
            lambda: len(dm["Eve"]) == 1 and (dm_rec.msg_id, "delivered") in statuses
        )
        assert dm["Eve"][0].text == "secret for eve"
        assert all(len(dm[n]) == 0 for n in ("Bob", "Carol", "Dave"))

        # Persisted DM status updated in Alice's SQLite history
        history = alice.get_history(eve.node_id)
        assert len(history) == 1
        assert history[0].status == "delivered"
    finally:
        for node in nodes.values():
            await node.stop()
