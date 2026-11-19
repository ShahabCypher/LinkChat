"""Asyncio-to-CustomTkinter event loop bridge and Windows app entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import queue
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from linkchat_core import (
    LinkChatNode,
    LogEntry,
    MessageRecord,
    PeerInfo,
    SafetyFingerprint,
)

from .ble_transport import WindowsBleTransport


def default_data_dir() -> Path:
    """Return the default Windows user app-data directory for LinkChat."""
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "LinkChat"
    return Path.home() / ".linkchat"


@dataclass(frozen=True, slots=True)
class NodeReadyEvent:
    node_id_hex: str
    short_tag: str
    nickname: str
    mode_label: str
    central_only: bool
    initial_peers: list[PeerInfo]
    public_history: list[MessageRecord]


@dataclass(frozen=True, slots=True)
class ModeChangedEvent:
    central_only: bool
    mode_label: str


@dataclass(frozen=True, slots=True)
class PeerUpdatedEvent:
    peer: PeerInfo


@dataclass(frozen=True, slots=True)
class PublicMessageEvent:
    record: MessageRecord


@dataclass(frozen=True, slots=True)
class DmReceivedEvent:
    record: MessageRecord


@dataclass(frozen=True, slots=True)
class DmStatusChangedEvent:
    msg_id: str
    status: str


@dataclass(frozen=True, slots=True)
class MeshLogEvent:
    entry: LogEntry


@dataclass(frozen=True, slots=True)
class HistoryLoadedEvent:
    channel: str
    messages: list[MessageRecord]


@dataclass(frozen=True, slots=True)
class FingerprintReadyEvent:
    node_id_hex: str
    peer: PeerInfo
    fingerprint: SafetyFingerprint


@dataclass(frozen=True, slots=True)
class ErrorEvent:
    message: str


class BackendBridge:
    """Hosts LinkChatNode + transport in an asyncio daemon thread for Tkinter UI."""

    def __init__(
        self,
        data_dir: str | Path | None = None,
        nickname: str | None = None,
        *,
        force_central_only: bool = False,
        transport_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else default_data_dir()
        self.nickname = nickname
        self.force_central_only = force_central_only
        self._transport_factory = transport_factory

        self.events: queue.Queue[Any] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._node: LinkChatNode | None = None
        self._transport: Any = None
        self._ready = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._thread_main,
            name="linkchat-asyncio",
            daemon=True,
        )
        self._thread.start()

    def wait_ready(self, timeout: float = 5.0) -> bool:
        return self._ready.wait(timeout=timeout)

    def stop(self, timeout: float = 3.0) -> None:
        loop = self._loop
        stop_event = self._stop_event
        if loop is not None and stop_event is not None and not loop.is_closed():
            loop.call_soon_threadsafe(stop_event.set)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._async_main())
        except Exception as exc:
            self.events.put(ErrorEvent(f"Backend error: {exc}"))
        finally:
            self._ready.set()
            loop.close()
            self._loop = None

    async def _async_main(self) -> None:
        self._stop_event = asyncio.Event()

        def _on_mode_changed(central_only: bool) -> None:
            label = "Central-Only" if central_only else "Dual-Role"
            self.events.put(ModeChangedEvent(central_only=central_only, mode_label=label))

        if self._transport_factory is not None:
            transport = self._transport_factory()
        else:
            transport = WindowsBleTransport(
                force_central_only=self.force_central_only,
                on_mode_changed=_on_mode_changed,
            )
        self._transport = transport

        node = LinkChatNode(
            data_dir=self.data_dir,
            transport=transport,
            nickname=self.nickname,
        )
        if hasattr(transport, "set_node_id"):
            transport.set_node_id(node.node_id_hex)

        node.on_peer_updated = lambda peer: self.events.put(
            PeerUpdatedEvent(replace(peer))
        )
        node.on_public_message = lambda rec: self.events.put(PublicMessageEvent(rec))
        node.on_dm_received = lambda rec: self.events.put(DmReceivedEvent(rec))
        node.on_dm_status_changed = lambda mid, st: self.events.put(
            DmStatusChangedEvent(mid, st)
        )
        node.on_mesh_log = lambda entry: self.events.put(MeshLogEvent(entry))
        self._node = node

        await node.start()

        central_only = bool(getattr(transport, "central_only", False))
        mode_label = getattr(
            transport, "mode_label", "Central-Only" if central_only else "Dual-Role"
        )
        self.events.put(
            NodeReadyEvent(
                node_id_hex=node.node_id_hex,
                short_tag=node.short_tag,
                nickname=node.nickname,
                mode_label=mode_label,
                central_only=central_only,
                initial_peers=[replace(p) for p in node.get_peers()],
                public_history=node.get_history("#public"),
            )
        )
        self._ready.set()

        await self._stop_event.wait()
        await node.stop()
        self._node = None
        self._transport = None

    def _submit(self, coro_factory: Callable[[LinkChatNode], Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        async def _runner() -> None:
            if self._node is None:
                return
            try:
                res = coro_factory(self._node)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as exc:
                self.events.put(ErrorEvent(str(exc)))

        asyncio.run_coroutine_threadsafe(_runner(), loop)

    def send_public(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return

        async def _op(node: LinkChatNode) -> None:
            rec = await node.send_public(cleaned)
            self.events.put(PublicMessageEvent(rec))

        self._submit(_op)

    def send_dm(self, target_id_hex: str, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return

        async def _op(node: LinkChatNode) -> None:
            rec = await node.send_dm(target_id_hex, cleaned)
            self.events.put(DmReceivedEvent(rec))

        self._submit(_op)

    def set_nickname(self, nickname: str) -> None:
        cleaned = nickname.strip()
        if not cleaned:
            return
        self._submit(lambda node: node.set_nickname(cleaned))

    def verify_peer(self, node_id_hex: str, verified: bool = True) -> None:
        def _op(node: LinkChatNode) -> None:
            node.verify_peer(node_id_hex, verified=verified)
            peer = node.router.peers.get(bytes.fromhex(node_id_hex))
            if peer is not None:
                self.events.put(PeerUpdatedEvent(replace(peer)))

        self._submit(_op)

    def request_history(self, channel_or_peer: str) -> None:
        def _op(node: LinkChatNode) -> None:
            msgs = node.get_history(channel_or_peer)
            self.events.put(HistoryLoadedEvent(channel=channel_or_peer, messages=msgs))

        self._submit(_op)

    def request_fingerprint(self, node_id_hex: str) -> None:
        def _op(node: LinkChatNode) -> None:
            peer = node.router.peers.get(bytes.fromhex(node_id_hex))
            if peer is None:
                raise KeyError(f"Unknown peer: {node_id_hex}")
            fp = node.get_safety_fingerprint(node_id_hex)
            self.events.put(
                FingerprintReadyEvent(
                    node_id_hex=node_id_hex,
                    peer=replace(peer),
                    fingerprint=fp,
                )
            )

        self._submit(_op)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LinkChat Windows BLE Mesh Messenger")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Directory for SQLite identity and chat history (defaults to %%LOCALAPPDATA%%/LinkChat)",
    )
    parser.add_argument(
        "--nickname",
        type=str,
        default=None,
        help="Override local display nickname",
    )
    parser.add_argument(
        "--central-only",
        action="store_true",
        help="Disable BLE Peripheral GATT Server and run in Central-only mode",
    )
    return parser.parse_args(argv)


def run_app(argv: list[str] | None = None) -> int:
    from .ui.main_window import MainWindow

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_args(argv)
    bridge = BackendBridge(
        data_dir=args.data_dir,
        nickname=args.nickname,
        force_central_only=args.central_only,
    )
    window = MainWindow(bridge)
    bridge.start()
    window.run()
    return 0


def main() -> None:
    raise SystemExit(run_app())
