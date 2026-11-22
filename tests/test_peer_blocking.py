"""Tests for mesh-preserving DM-only peer blocking and post-unblock suppression."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from linkchat_core import DMStatus, LinkChatNode, MessageRecord
from linkchat_core.protocol import ChatDmPayload, PacketHeader, PacketType, encode_packet
from linkchat_core.crypto import derive_dm_key, encrypt_dm
from linkchat_sim.virtual_transport import NetworkHub, VirtualTransport


async def _wait_until(pred: Any, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Condition not satisfied within timeout")


async def test_blocked_peer_relays_mesh_and_public_chat_but_drops_dms(
    tmp_path: Path,
) -> None:
    """Alice <-> Bob <-> Carol: Bob blocks Alice; relay and #public work, DMs are dropped."""
    hub = NetworkHub()
    names = ["Alice", "Bob", "Carol"]
    nodes: dict[str, LinkChatNode] = {}
    pub: dict[str, list[MessageRecord]] = {n: [] for n in names}
    dm: dict[str, list[MessageRecord]] = {n: [] for n in names}
    alice_statuses: list[tuple[str, str]] = []

    for n in names:
        node = LinkChatNode(
            tmp_path / n,
            VirtualTransport(n, hub),
            nickname=n,
            jitter_range=(0.002, 0.005),
        )
        node.on_public_message = lambda rec, name=n: pub[name].append(rec)
        node.on_dm_received = lambda rec, name=n: dm[name].append(rec)
        if n == "Alice":
            node.on_dm_status_changed = lambda mid, st: alice_statuses.append((mid, st))
        await node.start()
        nodes[n] = node

    try:
        await hub.connect("Alice", "Bob", latency_ms=2.0, mtu=247)
        await hub.connect("Bob", "Carol", latency_ms=2.0, mtu=247)
        await _wait_until(lambda: all(len(n.get_peers()) == 2 for n in nodes.values()))

        alice, bob, carol = nodes["Alice"], nodes["Bob"], nodes["Carol"]

        # Bob blocks Alice.
        bob.set_peer_blocked(alice.node_id, True)
        assert bob.is_peer_blocked(alice.node_id) is True
        assert bob.router.peers[alice.node_id].blocked is True

        # Bob cannot send DMs to Alice while blocked.
        with pytest.raises(ValueError, match="blocked"):
            await bob.send_dm(alice.node_id, "should not send")

        # #public chat from Alice still reaches Bob and Carol, and Bob -> Alice works too.
        await alice.send_public("public from alice")
        await bob.send_public("public from bob")
        await _wait_until(
            lambda: len(pub["Bob"]) == 1
            and len(pub["Carol"]) == 2
            and len(pub["Alice"]) == 1
        )
        assert pub["Bob"][0].text == "public from alice"
        assert pub["Alice"][0].text == "public from bob"

        # Alice <-> Carol E2EE DMs STILL relay through Bob!
        dm_ac = await alice.send_dm(carol.node_id, "relay through bob")
        await _wait_until(
            lambda: len(dm["Carol"]) == 1
            and (dm_ac.msg_id, DMStatus.DELIVERED.value) in alice_statuses
        )
        assert dm["Carol"][0].text == "relay through bob"
        assert dm["Carol"][0].hop_count == 2
        assert len(dm["Bob"]) == 0

        # Alice sends a DM to Bob while blocked -> silently dropped, no DM_ACK back.
        dm_ab = await alice.send_dm(bob.node_id, "blocked private msg")
        await asyncio.sleep(0.15)
        assert len(dm["Bob"]) == 0
        assert bob.get_history(alice.node_id) == []
        assert (dm_ab.msg_id, DMStatus.DELIVERED.value) not in alice_statuses

        # Bob unblocks Alice, and Alice retries/flushes her outbound queue (e.g. via HELLO).
        bob.set_peer_blocked(alice.node_id, False)
        assert bob.is_peer_blocked(alice.node_id) is False
        await bob.router.broadcast_hello()
        await asyncio.sleep(0.15)

        # Message sent while blocked must STILL not be received after unblocking!
        assert len(dm["Bob"]) == 0
        assert bob.get_history(alice.node_id) == []

        # New DM sent AFTER unblocking is delivered normally.
        dm_after = await alice.send_dm(bob.node_id, "after unblock")
        await _wait_until(
            lambda: len(dm["Bob"]) == 1
            and (dm_after.msg_id, DMStatus.DELIVERED.value) in alice_statuses
        )
        assert dm["Bob"][0].text == "after unblock"
    finally:
        for node in nodes.values():
            await node.stop()


async def test_offline_dm_sent_during_block_window_is_rejected_after_unblock_and_restart(
    tmp_path: Path,
) -> None:
    """DM created offline during block window is still rejected after unblock & DB restart."""
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
    alice_dms: list[MessageRecord] = []
    bob.on_dm_received = lambda rec: bob_dms.append(rec)
    alice.on_dm_received = lambda rec: alice_dms.append(rec)

    await alice.start()
    await bob.start()

    try:
        await hub.connect("Alice", "Bob", latency_ms=2.0, mtu=247)
        await _wait_until(
            lambda: len(alice.get_peers()) == 1 and len(bob.get_peers()) == 1
        )

        # Pre-block queued outbound DM on Bob gets cancelled when Bob blocks Alice.
        await hub.disconnect("Alice", "Bob")
        await _wait_until(lambda: not bob.router.peers[alice.node_id].connected)
        await bob.send_dm(alice.node_id, "queued before block")
        assert len(bob.router.dm_queue.pending_for(alice.node_id)) == 1

        bob.set_peer_blocked(alice.node_id, True)
        assert len(bob.router.dm_queue.pending_for(alice.node_id)) == 0

        # Wait briefly so blocked_at_ms < offline_ts < unblocked_at_ms cleanly.
        await asyncio.sleep(0.02)
        offline_ts_ms = int(time.time() * 1000)
        await asyncio.sleep(0.02)

        # Bob unblocks Alice BEFORE Alice reconnects.
        await asyncio.sleep(0.01)
        bob.set_peer_blocked(alice.node_id, False)
        await asyncio.sleep(0.01)

        # Craft an offline DM from Alice stamped during Bob's block window.
        msg_id = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        hdr = PacketHeader(
            pkt_type=PacketType.CHAT_DM,
            origin_id=alice.node_id,
            target_id=bob.node_id,
            ttl=5,
            hop=0,
            msg_id=msg_id,
        )
        dm_key = derive_dm_key(
            alice.identity.x25519_priv,
            alice.router.peers[bob.node_id].x25519_pub,
            alice.node_id,
            bob.node_id,
        )
        nonce, ct = encrypt_dm(dm_key, hdr.encode(), offline_ts_ms, b"sent while blocked offline")
        raw_offline = encode_packet(
            hdr, ChatDmPayload(timestamp_ms=offline_ts_ms, nonce=nonce, ciphertext=ct)
        )
        alice.router.dm_queue.enqueue(msg_id, bob.node_id, raw_offline)

        # Restart Bob from disk to confirm block window + peer state persisted across restart.
        await bob.stop()
        bob2 = LinkChatNode(
            tmp_path / "Bob",
            VirtualTransport("Bob", hub),
            nickname="Bob",
            jitter_range=(0.002, 0.005),
        )
        bob2_dms: list[MessageRecord] = []
        bob2.on_dm_received = lambda rec: bob2_dms.append(rec)
        await bob2.start()
        try:
            await hub.connect("Alice", "Bob", latency_ms=2.0, mtu=247)
            await _wait_until(lambda: bob2.router.peers[alice.node_id].connected)
            await asyncio.sleep(0.15)
            assert len(bob2_dms) == 0
            assert len(alice_dms) == 0
            assert [m for m in bob2.get_history(alice.node_id) if not m.is_outgoing] == []

            # A fresh DM sent after unblocking works.
            await alice.send_dm(bob2.node_id, "fresh after unblock")
            await _wait_until(lambda: len(bob2_dms) == 1)
            assert bob2_dms[0].text == "fresh after unblock"

            # reset_all clears block state and windows.
            bob2.set_peer_blocked(alice.node_id, True)
            assert bob2.is_peer_blocked(alice.node_id) is True
            await bob2.reset_all()
            assert bob2.is_peer_blocked(alice.node_id) is False
        finally:
            await bob2.stop()
    finally:
        await alice.stop()
        if bob.router._started:
            await bob.stop()
