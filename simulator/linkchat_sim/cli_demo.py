"""CLI demo running 5-node multi-hop mesh & partition-reconnect scenarios."""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

from linkchat_core import LinkChatNode, LogEntry, MessageRecord
from linkchat_sim.virtual_transport import NetworkHub, VirtualTransport


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def _wait_until(predicate, timeout: float = 5.0, step: float = 0.02) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(step)
    raise TimeoutError("Timed out waiting for simulated mesh condition")


async def run_linear_chain_demo() -> None:
    print("=== Scenario 1: 5-Node Linear Chain (Alice - Bob - Carol - Dave - Eve) ===")
    names = ["Alice", "Bob", "Carol", "Dave", "Eve"]
    hub = NetworkHub()
    nodes: dict[str, LinkChatNode] = {}
    public_inbox: dict[str, list[MessageRecord]] = {n: [] for n in names}
    dm_inbox: dict[str, list[MessageRecord]] = {n: [] for n in names}
    dm_statuses: dict[str, list[tuple[str, str]]] = {n: [] for n in names}
    relay_logs: dict[str, list[LogEntry]] = {n: [] for n in names}

    with tempfile.TemporaryDirectory(prefix="linkchat_sim_chain_") as tmp:
        for name in names:
            t = VirtualTransport(name, hub)
            node = LinkChatNode(Path(tmp) / name, t, nickname=name)
            node.on_public_message = lambda rec, n=name: public_inbox[n].append(rec)
            node.on_dm_received = lambda rec, n=name: dm_inbox[n].append(rec)
            node.on_dm_status_changed = (
                lambda mid, st, n=name: dm_statuses[n].append((mid, st))
            )
            node.on_mesh_log = lambda entry, n=name: relay_logs[n].append(entry)
            await node.start()
            nodes[name] = node

        try:
            for a, b in zip(names, names[1:]):
                await hub.connect(a, b, latency_ms=5.0, mtu=247, rssi=-58)

            # Wait for all nodes to discover the other 4 peers across up to 4 hops.
            await _wait_until(
                lambda: all(len(n.get_peers()) == 4 for n in nodes.values())
            )

            alice = nodes["Alice"]
            eve = nodes["Eve"]
            eve_from_alice = next(
                p for p in alice.get_peers() if p.node_id == eve.node_id
            )
            print(
                f"Alice sees Eve at {eve_from_alice.hop_count} hops (id={eve.short_tag})"
            )

            fp_alice = alice.get_safety_fingerprint(eve.node_id)
            fp_eve = eve.get_safety_fingerprint(alice.node_id)
            assert fp_alice == fp_eve
            print(
                f"Safety Fingerprint Alice<->Eve: {fp_alice.safety_number} | {fp_alice.emoji_hash}"
            )

            pub_text = "Hello mesh from Alice across 4 hops!"
            await alice.send_public(pub_text)
            await _wait_until(
                lambda: all(
                    any(m.text == pub_text for m in public_inbox[n])
                    for n in names[1:]
                )
            )
            for name in names[1:]:
                msg = next(m for m in public_inbox[name] if m.text == pub_text)
                print(f"  [PUBLIC] {name} received '{msg.text}' (hop_count={msg.hop_count})")

            dm_text = "Top-secret E2EE message for Eve only"
            dm_rec = await alice.send_dm(eve.node_id, dm_text)
            await _wait_until(
                lambda: any(m.text == dm_text for m in dm_inbox["Eve"])
                and any(
                    mid == dm_rec.msg_id and st == "delivered"
                    for mid, st in dm_statuses["Alice"]
                )
            )
            print(f"  [DM] Eve decrypted: '{dm_inbox['Eve'][0].text}'")
            for mid_name in ("Bob", "Carol", "Dave"):
                relayed = [
                    e for e in relay_logs[mid_name] if e.event_type == "RELAY_DM"
                ]
                assert len(dm_inbox[mid_name]) == 0
                print(
                    f"  [RELAY] {mid_name} relayed {len(relayed)} encrypted DM packet(s); plaintext unread={len(dm_inbox[mid_name]) == 0}"
                )
            print("  [ACK] Alice observed DM status -> delivered")
        finally:
            for node in nodes.values():
                await node.stop()


async def run_partition_reconnect_demo() -> None:
    print("\n=== Scenario 2: Partition & Reconnect (Store-and-Forward Sync) ===")
    names = ["Alice", "Bob", "Carol", "Dave", "Eve"]
    hub = NetworkHub()
    nodes: dict[str, LinkChatNode] = {}
    public_inbox: dict[str, list[MessageRecord]] = {n: [] for n in names}

    with tempfile.TemporaryDirectory(prefix="linkchat_sim_part_") as tmp:
        for name in names:
            t = VirtualTransport(name, hub)
            node = LinkChatNode(Path(tmp) / name, t, nickname=name)
            node.on_public_message = lambda rec, n=name: public_inbox[n].append(rec)
            await node.start()
            nodes[name] = node

        try:
            for a, b in zip(names, names[1:]):
                await hub.connect(a, b, latency_ms=5.0, mtu=247, rssi=-60)

            await _wait_until(
                lambda: all(len(n.get_peers()) == 4 for n in nodes.values())
            )

            # Disconnect Carol from both Bob and Dave (isolate Carol).
            await hub.disconnect("Bob", "Carol")
            await hub.disconnect("Carol", "Dave")
            print("Disconnected Carol from Bob and Dave.")

            missed_1 = "Missed message #1 while Carol was offline"
            missed_2 = "Missed message #2 while Carol was offline"
            await nodes["Alice"].send_public(missed_1)
            await nodes["Alice"].send_public(missed_2)

            await _wait_until(
                lambda: len(public_inbox["Bob"]) == 2
                and len(public_inbox["Carol"]) == 0
            )
            print(
                f"Bob cached {len(public_inbox['Bob'])} messages; Carol currently has {len(public_inbox['Carol'])}."
            )

            # Reconnect Carol to Bob & Dave -> SYNC_DIGEST / SYNC_REQ catches Carol up.
            await hub.connect("Bob", "Carol", latency_ms=5.0, mtu=247, rssi=-60)
            await hub.connect("Carol", "Dave", latency_ms=5.0, mtu=247, rssi=-60)
            await _wait_until(
                lambda: {m.text for m in public_inbox["Carol"]} == {missed_1, missed_2}
                and {m.text for m in public_inbox["Eve"]} == {missed_1, missed_2}
            )
            print(
                f"After reconnect: Carol caught up with {len(public_inbox['Carol'])} messages; Eve has {len(public_inbox['Eve'])}."
            )
        finally:
            for node in nodes.values():
                await node.stop()


async def main_async(scenario: str) -> None:
    if scenario in ("chain", "all"):
        await run_linear_chain_demo()
    if scenario in ("partition", "all"):
        await run_partition_reconnect_demo()


def main() -> None:
    _configure_stdout()
    parser = argparse.ArgumentParser(description="LinkChat 5-node mesh simulator demo")
    parser.add_argument(
        "--scenario",
        choices=("chain", "partition", "all"),
        default="all",
        help="Scenario to run (default: all)",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args.scenario))


if __name__ == "__main__":
    main()
