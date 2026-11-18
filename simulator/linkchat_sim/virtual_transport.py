"""In-memory graph radio simulator with configurable latency, MTU, RSSI, and drop rate."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass(slots=True)
class EdgeConfig:
    latency_ms: float = 5.0
    mtu: int = 247
    rssi: int = -55
    drop_rate: float = 0.0


class VirtualTransport:
    """TransportAdapter implementation backed by a NetworkHub graph."""

    def __init__(self, name: str, hub: NetworkHub) -> None:
        self.name = name
        self.hub = hub
        self._started = False
        self._on_link_up: Callable[[str, int, int], Awaitable[None]] | None = None
        self._on_link_down: Callable[[str], Awaitable[None]] | None = None
        self._on_chunk: Callable[[str, bytes], Awaitable[None]] | None = None
        self._send_queues: dict[str, asyncio.Queue[bytes]] = {}
        self._send_workers: dict[str, asyncio.Task[None]] = {}
        hub._register(self)

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
        self._started = True
        for peer_name, edge in list(self.hub._neighbors(self.name)):
            peer = self.hub._nodes.get(peer_name)
            if peer is not None and peer._started:
                await self.hub._notify_link_up(self, peer, edge)

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        for peer_name in list(self._send_workers):
            self._stop_worker(peer_name)
        for peer_name, _ in list(self.hub._neighbors(self.name)):
            peer = self.hub._nodes.get(peer_name)
            if peer is not None and peer._started:
                await self.hub._notify_link_down(self, peer)

    def _start_worker(self, peer_name: str) -> None:
        if peer_name in self._send_workers:
            return
        q: asyncio.Queue[bytes] = asyncio.Queue()
        self._send_queues[peer_name] = q
        self._send_workers[peer_name] = asyncio.create_task(
            self._deliver_loop(peer_name, q)
        )

    def _stop_worker(self, peer_name: str) -> None:
        task = self._send_workers.pop(peer_name, None)
        self._send_queues.pop(peer_name, None)
        if task is not None:
            task.cancel()

    async def _deliver_loop(
        self, peer_name: str, queue: asyncio.Queue[bytes]
    ) -> None:
        try:
            while True:
                chunk = await queue.get()
                edge = self.hub.get_edge(self.name, peer_name)
                peer = self.hub._nodes.get(peer_name)
                if edge is None or peer is None or not peer._started:
                    continue
                if edge.latency_ms > 0:
                    await asyncio.sleep(edge.latency_ms / 1000.0)
                if not self._started or not peer._started:
                    continue
                if self.hub.get_edge(self.name, peer_name) is None:
                    continue
                if edge.drop_rate > 0.0 and random.random() < edge.drop_rate:
                    continue
                if peer._on_chunk is not None:
                    await peer._on_chunk(self.name, chunk)
        except asyncio.CancelledError:
            pass

    async def send_chunk(self, peer_handle: str, chunk: bytes) -> None:
        if not self._started:
            return
        queue = self._send_queues.get(peer_handle)
        if queue is not None:
            await queue.put(chunk)


class NetworkHub:
    """Undirected virtual radio topology connecting VirtualTransport instances."""

    def __init__(self) -> None:
        self._nodes: dict[str, VirtualTransport] = {}
        self._edges: dict[frozenset[str], EdgeConfig] = {}

    def _register(self, transport: VirtualTransport) -> None:
        self._nodes[transport.name] = transport

    def _neighbors(self, name: str) -> list[tuple[str, EdgeConfig]]:
        result: list[tuple[str, EdgeConfig]] = []
        for pair, cfg in self._edges.items():
            if name in pair:
                other = next(iter(pair - {name}))
                result.append((other, cfg))
        return result

    def get_edge(self, a: str, b: str) -> EdgeConfig | None:
        return self._edges.get(frozenset((a, b)))

    async def connect(
        self,
        a: str,
        b: str,
        latency_ms: float = 5.0,
        mtu: int = 247,
        rssi: int = -55,
        drop_rate: float = 0.0,
    ) -> None:
        if a == b:
            raise ValueError("Cannot connect a node to itself")
        key = frozenset((a, b))
        cfg = EdgeConfig(
            latency_ms=latency_ms, mtu=mtu, rssi=rssi, drop_rate=drop_rate
        )
        self._edges[key] = cfg
        ta = self._nodes.get(a)
        tb = self._nodes.get(b)
        if ta is not None and tb is not None and ta._started and tb._started:
            await self._notify_link_up(ta, tb, cfg)

    async def disconnect(self, a: str, b: str) -> None:
        key = frozenset((a, b))
        if key not in self._edges:
            return
        del self._edges[key]
        ta = self._nodes.get(a)
        tb = self._nodes.get(b)
        if ta is not None and tb is not None:
            await self._notify_link_down(ta, tb)

    async def _notify_link_up(
        self, a: VirtualTransport, b: VirtualTransport, cfg: EdgeConfig
    ) -> None:
        a._start_worker(b.name)
        b._start_worker(a.name)
        tasks = []
        if a._on_link_up is not None:
            tasks.append(a._on_link_up(b.name, cfg.mtu, cfg.rssi))
        if b._on_link_up is not None:
            tasks.append(b._on_link_up(a.name, cfg.mtu, cfg.rssi))
        if tasks:
            await asyncio.gather(*tasks)

    async def _notify_link_down(
        self, a: VirtualTransport, b: VirtualTransport
    ) -> None:
        a._stop_worker(b.name)
        b._stop_worker(a.name)
        tasks = []
        if a._started and a._on_link_down is not None:
            tasks.append(a._on_link_down(b.name))
        if b._started and b._on_link_down is not None:
            tasks.append(b._on_link_down(a.name))
        if tasks:
            await asyncio.gather(*tasks)
