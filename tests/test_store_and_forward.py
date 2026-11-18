"""Tests for caches and store-and-forward catch-up sync after reconnect."""

from __future__ import annotations

import asyncio
from pathlib import Path

from linkchat_core import LinkChatNode, MessageRecord
from linkchat_core.cache import OutboundDMQueue, PublicMessageCache
from linkchat_sim.virtual_transport import NetworkHub, VirtualTransport


async def _wait_until(predicate, timeout: float = 4.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.015)
    raise AssertionError("Condition not met within timeout")


def test_public_cache_limits_and_expiry() -> None:
    cache = PublicMessageCache(max_size=100, max_age_sec=7200.0)
    for i in range(105):
        mid = i.to_bytes(8, "big")
        cache.add(mid, b"pkt" + mid, now=1000.0 + i)

    assert len(cache) == 100
    assert cache.get((4).to_bytes(8, "big"), now=1200.0) is None
    assert cache.get((5).to_bytes(8, "big"), now=1200.0) is not None

    # After > 2 hours from last entry (1104 + 7201)
    assert cache.msg_ids(now=8305.0) == []


def test_outbound_dm_queue_expiry_and_ack() -> None:
    q = OutboundDMQueue(max_age_sec=86400.0)
    mid = b"\x01" * 8
    target = b"\x02" * 8
    q.enqueue(mid, target, b"raw", now=100.0)
    assert len(q.pending_for(target, now=200.0)) == 1
    assert q.ack(mid)
    assert len(q.pending_for(target, now=200.0)) == 0

    q.enqueue(mid, target, b"raw", now=100.0)
    assert len(q.pending_for(target, now=86501.0)) == 0


async def test_sync_digest_catchup_after_partition_reconnect(tmp_path: Path) -> None:
    hub = NetworkHub()
    names = ["Alice", "Bob", "Carol"]
    nodes: dict[str, LinkChatNode] = {}
    pub: dict[str, list[MessageRecord]] = {n: [] for n in names}

    for n in names:
        node = LinkChatNode(
            tmp_path / n,
            VirtualTransport(n, hub),
            nickname=n,
            jitter_range=(0.002, 0.005),
        )
        node.on_public_message = lambda rec, name=n: pub[name].append(rec)
        await node.start()
        nodes[n] = node

    try:
        await hub.connect("Alice", "Bob", latency_ms=2.0)
        await hub.connect("Bob", "Carol", latency_ms=2.0)
        await _wait_until(lambda: all(len(n.get_peers()) == 2 for n in nodes.values()))

        # Partition Carol
        await hub.disconnect("Bob", "Carol")
        sent_1 = await nodes["Alice"].send_public("missed one")
        sent_2 = await nodes["Alice"].send_public("missed two")

        await _wait_until(lambda: len(pub["Bob"]) == 2)
        assert len(pub["Carol"]) == 0

        # Reconnect Carol -> SYNC_DIGEST + SYNC_REQ replays missed messages preserving msg_id
        await hub.connect("Bob", "Carol", latency_ms=2.0)
        await _wait_until(lambda: len(pub["Carol"]) == 2)
        assert {m.msg_id for m in pub["Carol"]} == {sent_1.msg_id, sent_2.msg_id}
        assert {m.text for m in pub["Carol"]} == {"missed one", "missed two"}
    finally:
        for node in nodes.values():
            await node.stop()


async def test_queued_dm_delivered_after_peer_reconnects(tmp_path: Path) -> None:
    hub = NetworkHub()
    alice = LinkChatNode(
        tmp_path / "Alice",
        VirtualTransport("Alice", hub),
        nickname="Alice",
        jitter_range=(0.002, 0.005),
    )
    bob = LinkChatNode(
        tmp_path / "Bob",
        VirtualTransport("Bob", hub),
        nickname="Bob",
        jitter_range=(0.002, 0.005),
    )
    bob_dms: list[MessageRecord] = []
    alice_statuses: list[tuple[str, str]] = []
    bob.on_dm_received = lambda rec: bob_dms.append(rec)
    alice.on_dm_status_changed = lambda mid, st: alice_statuses.append((mid, st))

    await alice.start()
    await bob.start()
    try:
        # Initial contact so Alice learns Bob's X25519 key
        await hub.connect("Alice", "Bob", latency_ms=2.0)
        await _wait_until(lambda: len(alice.get_peers()) == 1 and len(bob.get_peers()) == 1)

        # Disconnect Bob, send DM while offline
        await hub.disconnect("Alice", "Bob")
        await _wait_until(lambda: not alice.get_peers()[0].connected)

        dm_rec = await alice.send_dm(bob.node_id, "queued while offline")
        assert dm_rec.status == "sending"
        assert len(bob_dms) == 0

        # Reconnect -> Alice flushes queued DM, Bob decrypts and returns DM_ACK
        await hub.connect("Alice", "Bob", latency_ms=2.0)
        await _wait_until(
            lambda: len(bob_dms) == 1 and (dm_rec.msg_id, "delivered") in alice_statuses
        )
        assert bob_dms[0].text == "queued while offline"
    finally:
        await alice.stop()
        await bob.stop()
