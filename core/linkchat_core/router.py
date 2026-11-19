"""Mesh router: handshake, deduplication, multi-hop relay, and store-and-forward sync."""

from __future__ import annotations

import asyncio
import inspect
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Callable

from cryptography.exceptions import InvalidTag

from .cache import OutboundDMQueue, PublicMessageCache, SeenCache
from .crypto import (
    decrypt_dm,
    decrypt_dm_ack,
    derive_dm_key,
    encrypt_dm,
    encrypt_dm_ack,
    sign_public_message,
    verify_public_message,
)
from .identity import Identity, compute_node_id
from .protocol import (
    BROADCAST_TARGET,
    DEFAULT_TTL,
    ChatDmPayload,
    ChatPublicPayload,
    ChunkAssembler,
    DmAckPayload,
    HelloPayload,
    Packet,
    PacketHeader,
    PacketType,
    ProtocolError,
    SyncDigestPayload,
    SyncReqPayload,
    decode_packet,
    encode_packet,
    packet_with_hop,
)
from .storage import Storage
from .transport import DMStatus, LogEntry, MessageRecord, PeerInfo, TransportAdapter


@dataclass(slots=True)
class LinkState:
    handle: str
    mtu: int
    rssi: int
    peer_node_id: bytes | None = None


class MeshRouter:
    """Coordinates BLE link events, packet routing, E2EE, and store-and-forward."""

    def __init__(
        self,
        identity: Identity,
        nickname: str,
        storage: Storage,
        transport: TransportAdapter,
        stale_timeout_sec: float = 90.0,
        jitter_range: tuple[float, float] = (0.015, 0.060),
    ) -> None:
        self.identity = identity
        self.nickname = nickname
        self.storage = storage
        self.transport = transport
        self.stale_timeout_sec = stale_timeout_sec
        self.jitter_range = jitter_range

        self.assembler = ChunkAssembler()
        self.seen_cache = SeenCache()
        self.public_cache = PublicMessageCache()
        self.dm_queue = OutboundDMQueue()

        self.links: dict[str, LinkState] = {}
        self.peers: dict[bytes, PeerInfo] = {}
        self._known_hellos: dict[bytes, bytes] = {}  # origin_id -> latest raw HELLO
        self._pending_public: set[bytes] = set()
        self._forward_tasks: set[asyncio.Task[None]] = set()
        self._maintenance_task: asyncio.Task[None] | None = None
        self._started = False

        # Event callbacks (sync or async)
        self.on_peer_updated: Callable[[PeerInfo], Any] | None = None
        self.on_public_message: Callable[[MessageRecord], Any] | None = None
        self.on_dm_received: Callable[[MessageRecord], Any] | None = None
        self.on_dm_status_changed: Callable[[str, str], Any] | None = None
        self.on_mesh_log: Callable[[LogEntry], Any] | None = None

    async def start(self) -> None:
        if self._started:
            return
        for peer in self.storage.load_peers():
            self.peers[peer.node_id] = peer
        pending_public = [
            rec
            for rec in self.storage.get_history("#public")
            if rec.is_outgoing and rec.status == DMStatus.SENDING.value
        ]
        for rec in pending_public[-self.public_cache.max_size :]:
            msg_id = bytes.fromhex(rec.msg_id)
            raw = self._build_public_packet(msg_id, rec.timestamp_ms, rec.text)
            self.seen_cache.check_and_add(self.identity.node_id, msg_id)
            self.public_cache.add(msg_id, raw)
            self._pending_public.add(msg_id)
        self.transport.set_callbacks(
            on_link_up=self._on_link_up,
            on_link_down=self._on_link_down,
            on_chunk=self._on_chunk,
        )
        self._started = True
        self._maintenance_task = asyncio.create_task(self._maintenance_loop())
        await self.transport.start()

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        if self._maintenance_task is not None:
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass
            self._maintenance_task = None
        for task in list(self._forward_tasks):
            task.cancel()
        if self._forward_tasks:
            await asyncio.gather(*self._forward_tasks, return_exceptions=True)
        self._forward_tasks.clear()
        await self.transport.stop()

    async def _emit(self, callback: Callable[..., Any] | None, *args: Any) -> None:
        if callback is None:
            return
        result = callback(*args)
        if inspect.isawaitable(result):
            await result

    async def _log(
        self,
        event_type: str,
        message: str,
        pkt_type: str = "",
        msg_id: str = "",
        origin_id: str = "",
        target_id: str = "",
        hop: int = 0,
        ttl: int = 0,
    ) -> None:
        entry = LogEntry(
            timestamp_ms=int(time.time() * 1000),
            event_type=event_type,
            message=message,
            pkt_type=pkt_type,
            msg_id=msg_id,
            origin_id=origin_id,
            target_id=target_id,
            hop=hop,
            ttl=ttl,
        )
        await self._emit(self.on_mesh_log, entry)

    async def _maintenance_loop(self) -> None:
        while self._started:
            await asyncio.sleep(5.0)
            self.assembler.purge_expired()
            now = time.time()
            for peer in self.peers.values():
                if (
                    peer.connected
                    and not peer.direct
                    and (now - peer.last_seen) > self.stale_timeout_sec
                ):
                    peer.connected = False
                    await self._emit(self.on_peer_updated, peer)

    async def _send_packet_to_link(self, handle: str, raw_packet: bytes) -> bool:
        link = self.links.get(handle)
        if link is None:
            return False
        chunks = self.assembler.chunk_packet(raw_packet, mtu=link.mtu, peer_handle=handle)
        for chunk in chunks:
            if handle not in self.links:
                return False
            await self.transport.send_chunk(handle, chunk)
        return True

    def _build_hello_packet(self) -> bytes:
        header = PacketHeader(
            pkt_type=PacketType.HELLO,
            origin_id=self.identity.node_id,
            target_id=BROADCAST_TARGET,
            ttl=DEFAULT_TTL,
            hop=0,
        )
        payload = HelloPayload(
            caps=0x01,
            nickname=self.nickname,
            ed25519_pub=self.identity.ed25519_pub,
            x25519_pub=self.identity.x25519_pub,
        )
        return encode_packet(header, payload)

    async def broadcast_hello(self) -> None:
        """Broadcast a fresh HELLO packet across all active links."""
        raw = self._build_hello_packet()
        for handle in list(self.links):
            await self._send_packet_to_link(handle, raw)

    async def _on_link_up(self, handle: str, mtu: int, rssi: int) -> None:
        self.links[handle] = LinkState(handle=handle, mtu=mtu, rssi=rssi)
        await self._log("LINK_UP", f"Link up {handle} (mtu={mtu}, rssi={rssi})")
        hello_raw = self._build_hello_packet()
        await self._send_packet_to_link(handle, hello_raw)

    async def _on_link_down(self, handle: str) -> None:
        link = self.links.pop(handle, None)
        self.assembler.clear_peer(handle)
        await self._log("LINK_DOWN", f"Link down {handle}")
        if link is not None and link.peer_node_id is not None:
            peer = self.peers.get(link.peer_node_id)
            if peer is not None and peer.link_handle == handle:
                peer.direct = False
                peer.connected = False
                peer.link_handle = None
                await self._emit(self.on_peer_updated, peer)

    async def _on_chunk(self, handle: str, chunk: bytes) -> None:
        raw_packet = self.assembler.feed_chunk(handle, chunk)
        if raw_packet is not None:
            await self._handle_packet(handle, raw_packet)

    async def _handle_packet(self, from_handle: str, raw_packet: bytes) -> None:
        try:
            pkt = decode_packet(raw_packet)
        except ProtocolError as exc:
            await self._log("DROP", f"Malformed packet from {from_handle}: {exc}")
            return

        hdr = pkt.header
        if hdr.origin_id == self.identity.node_id:
            return

        if self.seen_cache.check_and_add(hdr.origin_id, hdr.msg_id):
            return

        if hdr.pkt_type == PacketType.HELLO:
            await self._handle_hello(from_handle, pkt, raw_packet)
        elif hdr.pkt_type == PacketType.CHAT_PUBLIC:
            await self._handle_chat_public(from_handle, pkt, raw_packet)
        elif hdr.pkt_type == PacketType.CHAT_DM:
            await self._handle_chat_dm(from_handle, pkt, raw_packet)
        elif hdr.pkt_type == PacketType.DM_ACK:
            await self._handle_dm_ack(from_handle, pkt, raw_packet)
        elif hdr.pkt_type == PacketType.SYNC_DIGEST:
            await self._handle_sync_digest(from_handle, pkt)
        elif hdr.pkt_type == PacketType.SYNC_REQ:
            await self._handle_sync_req(from_handle, pkt)

    async def _handle_hello(
        self, from_handle: str, pkt: Packet, raw_packet: bytes
    ) -> None:
        assert isinstance(pkt.payload, HelloPayload)
        hdr = pkt.header
        payload = pkt.payload

        # Bind node_id to ed25519_pub to prevent identity spoofing.
        try:
            derived_id = compute_node_id(payload.ed25519_pub)
        except ValueError:
            return
        if derived_id != hdr.origin_id or not Identity.validate_x25519_pub(
            payload.x25519_pub
        ):
            await self._log("DROP", f"Invalid HELLO key binding from {from_handle}")
            return

        now = time.time()
        verified, key_changed = self.storage.upsert_peer(
            node_id=hdr.origin_id,
            nickname=payload.nickname,
            ed25519_pub=payload.ed25519_pub,
            x25519_pub=payload.x25519_pub,
            now=now,
        )

        link = self.links.get(from_handle)
        existing = self.peers.get(hdr.origin_id)
        is_direct = hdr.hop == 0

        if is_direct and link is not None:
            link.peer_node_id = hdr.origin_id
            hop_count = 1
            rssi = link.rssi
            direct = True
            link_handle: str | None = from_handle
        else:
            observed = hdr.hop + 1
            if existing is not None and existing.direct and existing.connected:
                hop_count = 1
                rssi = existing.rssi
                direct = True
                link_handle = existing.link_handle
            else:
                hop_count = (
                    min(existing.hop_count, observed)
                    if (existing is not None and existing.connected and existing.hop_count > 0)
                    else observed
                )
                rssi = existing.rssi if existing is not None else -99
                direct = False
                link_handle = None

        peer = PeerInfo(
            node_id=hdr.origin_id,
            node_id_hex=hdr.origin_id.hex(),
            nickname=payload.nickname,
            ed25519_pub=payload.ed25519_pub,
            x25519_pub=payload.x25519_pub,
            hop_count=hop_count,
            rssi=rssi,
            direct=direct,
            connected=True,
            verified=verified,
            key_changed=key_changed,
            last_seen=now,
            link_handle=link_handle,
        )
        self.peers[hdr.origin_id] = peer
        self._known_hellos[hdr.origin_id] = raw_packet
        await self._emit(self.on_peer_updated, peer)
        await self._log(
            "HELLO",
            f"Peer {payload.nickname} ({peer.node_id_hex[:4]}) at {hop_count} hop(s)",
            pkt_type="HELLO",
            msg_id=hdr.msg_id.hex(),
            origin_id=peer.node_id_hex,
            hop=hdr.hop,
            ttl=hdr.ttl,
        )

        if is_direct:
            await self._share_known_hellos(from_handle, exclude_origin=hdr.origin_id)
            await self._send_sync_digest(from_handle)

        await self._flush_outbound_dms(hdr.origin_id)
        self._schedule_forward(from_handle, pkt, raw_packet)

    async def _send_sync_digest(self, handle: str) -> None:
        ids = self.public_cache.msg_ids()
        if not ids:
            return
        header = PacketHeader(
            pkt_type=PacketType.SYNC_DIGEST,
            origin_id=self.identity.node_id,
            target_id=BROADCAST_TARGET,
            ttl=1,
            hop=0,
        )
        raw = encode_packet(header, SyncDigestPayload(msg_ids=ids))
        await self._send_packet_to_link(handle, raw)

    async def _share_known_hellos(self, handle: str, exclude_origin: bytes) -> None:
        """Forward cached peer HELLO packets so newly connected peers learn the mesh."""
        for origin_id, raw_hello in list(self._known_hellos.items()):
            if origin_id == exclude_origin or origin_id == self.identity.node_id:
                continue
            try:
                cached = decode_packet(raw_hello)
            except ProtocolError:
                continue
            if cached.header.ttl <= 1:
                continue
            fwd = packet_with_hop(
                raw_hello, ttl=cached.header.ttl - 1, hop=cached.header.hop + 1
            )
            await self._send_packet_to_link(handle, fwd)

    async def _handle_chat_public(
        self, from_handle: str, pkt: Packet, raw_packet: bytes
    ) -> None:
        assert isinstance(pkt.payload, ChatPublicPayload)
        hdr = pkt.header
        payload = pkt.payload
        peer = self.peers.get(hdr.origin_id)
        if peer is None:
            await self._log(
                "DROP",
                f"Dropped CHAT_PUBLIC from unknown peer {hdr.origin_id.hex()[:4]}",
                pkt_type="CHAT_PUBLIC",
                msg_id=hdr.msg_id.hex(),
            )
            return

        if not verify_public_message(
            peer.ed25519_pub,
            pkt.raw_header,
            payload.timestamp_ms,
            payload.text.encode("utf-8"),
            payload.ed25519_sig,
        ):
            await self._log(
                "DROP",
                f"Invalid Ed25519 signature on CHAT_PUBLIC from {peer.nickname}",
                pkt_type="CHAT_PUBLIC",
                msg_id=hdr.msg_id.hex(),
            )
            return

        self._update_relayed_reachability(peer, hdr.hop)
        self.public_cache.add(hdr.msg_id, raw_packet)

        record = MessageRecord(
            msg_id=hdr.msg_id.hex(),
            channel="#public",
            origin_id=hdr.origin_id.hex(),
            target_id=BROADCAST_TARGET.hex(),
            sender_nick=peer.nickname,
            text=payload.text,
            timestamp_ms=payload.timestamp_ms,
            is_outgoing=False,
            status=DMStatus.DELIVERED.value,
            hop_count=hdr.hop + 1,
        )
        self.storage.save_message(record)
        await self._emit(self.on_public_message, record)
        await self._log(
            "RX_PUBLIC",
            f"#public from {peer.nickname} (hop={hdr.hop + 1})",
            pkt_type="CHAT_PUBLIC",
            msg_id=record.msg_id,
            origin_id=record.origin_id,
            hop=hdr.hop,
            ttl=hdr.ttl,
        )
        self._schedule_forward(from_handle, pkt, raw_packet)

    async def _handle_chat_dm(
        self, from_handle: str, pkt: Packet, raw_packet: bytes
    ) -> None:
        assert isinstance(pkt.payload, ChatDmPayload)
        hdr = pkt.header
        payload = pkt.payload

        if hdr.target_id != self.identity.node_id:
            await self._log(
                "RELAY_DM",
                f"Relaying encrypted CHAT_DM {hdr.msg_id.hex()[:6]} (hop={hdr.hop + 1}, ttl={hdr.ttl})",
                pkt_type="CHAT_DM",
                msg_id=hdr.msg_id.hex(),
                origin_id=hdr.origin_id.hex(),
                target_id=hdr.target_id.hex(),
                hop=hdr.hop,
                ttl=hdr.ttl,
            )
            self._schedule_forward(from_handle, pkt, raw_packet)
            return

        peer = self.peers.get(hdr.origin_id)
        if peer is None:
            return
        try:
            dm_key = derive_dm_key(
                self.identity.x25519_priv,
                peer.x25519_pub,
                self.identity.node_id,
                hdr.origin_id,
            )
            plaintext = decrypt_dm(
                dm_key,
                pkt.raw_header,
                payload.timestamp_ms,
                payload.nonce,
                payload.ciphertext,
            )
            text = plaintext.decode("utf-8")
        except (InvalidTag, ValueError, UnicodeDecodeError):
            await self._log(
                "DROP",
                f"Failed DM decryption/auth from {peer.nickname}",
                pkt_type="CHAT_DM",
                msg_id=hdr.msg_id.hex(),
            )
            return

        record = MessageRecord(
            msg_id=hdr.msg_id.hex(),
            channel=peer.node_id_hex,
            origin_id=peer.node_id_hex,
            target_id=self.identity.node_id_hex,
            sender_nick=peer.nickname,
            text=text,
            timestamp_ms=payload.timestamp_ms,
            is_outgoing=False,
            status=DMStatus.DELIVERED.value,
            hop_count=hdr.hop + 1,
        )
        self.storage.save_message(record)
        await self._emit(self.on_dm_received, record)
        await self._log(
            "RX_DM",
            f"Decrypted DM from {peer.nickname} (hop={hdr.hop + 1})",
            pkt_type="CHAT_DM",
            msg_id=record.msg_id,
            origin_id=record.origin_id,
            target_id=record.target_id,
            hop=hdr.hop,
            ttl=hdr.ttl,
        )

        ack_header = PacketHeader(
            pkt_type=PacketType.DM_ACK,
            origin_id=self.identity.node_id,
            target_id=hdr.origin_id,
            ttl=DEFAULT_TTL,
            hop=0,
        )
        ack_nonce, ack_ct = encrypt_dm_ack(dm_key, ack_header.encode(), hdr.msg_id)
        ack_raw = encode_packet(
            ack_header,
            DmAckPayload(acked_msg_id=hdr.msg_id, nonce=ack_nonce, ciphertext=ack_ct),
        )
        await self._send_to_all_links(ack_raw)

    async def _handle_dm_ack(
        self, from_handle: str, pkt: Packet, raw_packet: bytes
    ) -> None:
        assert isinstance(pkt.payload, DmAckPayload)
        hdr = pkt.header
        payload = pkt.payload

        if hdr.target_id != self.identity.node_id:
            await self._log(
                "RELAY_ACK",
                f"Relaying DM_ACK for {payload.acked_msg_id.hex()[:6]}",
                pkt_type="DM_ACK",
                msg_id=hdr.msg_id.hex(),
                origin_id=hdr.origin_id.hex(),
                target_id=hdr.target_id.hex(),
                hop=hdr.hop,
                ttl=hdr.ttl,
            )
            self._schedule_forward(from_handle, pkt, raw_packet)
            return

        peer = self.peers.get(hdr.origin_id)
        if peer is None:
            return
        try:
            dm_key = derive_dm_key(
                self.identity.x25519_priv,
                peer.x25519_pub,
                self.identity.node_id,
                hdr.origin_id,
            )
            pt = decrypt_dm_ack(
                dm_key,
                pkt.raw_header,
                payload.acked_msg_id,
                payload.nonce,
                payload.ciphertext,
            )
        except (InvalidTag, ValueError):
            return

        if pt != b"ACK":
            return

        acked_hex = payload.acked_msg_id.hex()
        self.dm_queue.ack(payload.acked_msg_id)
        self.storage.update_message_status(acked_hex, DMStatus.DELIVERED.value)
        await self._emit(
            self.on_dm_status_changed, acked_hex, DMStatus.DELIVERED.value
        )
        await self._log(
            "RX_ACK",
            f"DM {acked_hex[:6]} delivered to {peer.nickname}",
            pkt_type="DM_ACK",
            msg_id=acked_hex,
            origin_id=peer.node_id_hex,
        )

    async def _handle_sync_digest(self, from_handle: str, pkt: Packet) -> None:
        assert isinstance(pkt.payload, SyncDigestPayload)
        missing = [
            mid for mid in pkt.payload.msg_ids if self.public_cache.get(mid) is None
        ]
        if not missing:
            return
        req_header = PacketHeader(
            pkt_type=PacketType.SYNC_REQ,
            origin_id=self.identity.node_id,
            target_id=BROADCAST_TARGET,
            ttl=1,
            hop=0,
        )
        req_raw = encode_packet(req_header, SyncReqPayload(msg_ids=missing))
        await self._send_packet_to_link(from_handle, req_raw)
        await self._log(
            "SYNC_REQ",
            f"Requested {len(missing)} missed public msg(s) on {from_handle}",
            pkt_type="SYNC_REQ",
        )

    async def _handle_sync_req(self, from_handle: str, pkt: Packet) -> None:
        assert isinstance(pkt.payload, SyncReqPayload)
        sent = 0
        for mid in pkt.payload.msg_ids:
            cached_raw = self.public_cache.get(mid)
            if cached_raw is not None and await self._send_packet_to_link(
                from_handle, cached_raw
            ):
                sent += 1
                if mid in self._pending_public:
                    self._pending_public.discard(mid)
                    msg_hex = mid.hex()
                    self.storage.update_message_status(msg_hex, DMStatus.RELAYED.value)
                    await self._emit(
                        self.on_dm_status_changed, msg_hex, DMStatus.RELAYED.value
                    )
        if sent:
            await self._log(
                "SYNC_REPLAY",
                f"Replayed {sent} cached public msg(s) to {from_handle}",
                pkt_type="SYNC_REQ",
            )

    def _update_relayed_reachability(self, peer: PeerInfo, hop: int) -> None:
        now = time.time()
        peer.last_seen = now
        if peer.direct and peer.connected:
            return
        observed = hop + 1
        if not peer.connected or peer.hop_count == 0:
            peer.hop_count = observed
        else:
            peer.hop_count = min(peer.hop_count, observed)
        peer.connected = True
        peer.direct = False

    def _schedule_forward(
        self, from_handle: str, pkt: Packet, raw_packet: bytes
    ) -> None:
        if pkt.header.ttl <= 1:
            return
        targets = [h for h in self.links if h != from_handle]
        if not targets:
            return
        fwd_raw = packet_with_hop(
            raw_packet, ttl=pkt.header.ttl - 1, hop=pkt.header.hop + 1
        )
        task = asyncio.create_task(self._forward_after_jitter(from_handle, fwd_raw))
        self._forward_tasks.add(task)
        task.add_done_callback(self._forward_tasks.discard)

    async def _forward_after_jitter(self, from_handle: str, fwd_raw: bytes) -> None:
        lo, hi = self.jitter_range
        if hi > 0:
            await asyncio.sleep(random.uniform(lo, hi))
        if not self._started:
            return
        for handle in list(self.links):
            if handle != from_handle:
                await self._send_packet_to_link(handle, fwd_raw)

    async def _send_to_all_links(self, raw_packet: bytes) -> int:
        sent = 0
        for handle in list(self.links):
            if await self._send_packet_to_link(handle, raw_packet):
                sent += 1
        return sent

    async def _flush_outbound_dms(self, target_id: bytes) -> None:
        if not self.links:
            return
        for item in self.dm_queue.pending_for(target_id):
            await self._send_to_all_links(item.raw_packet)
            msg_hex = item.msg_id.hex()
            self.storage.update_message_status(msg_hex, DMStatus.RELAYED.value)
            await self._emit(
                self.on_dm_status_changed, msg_hex, DMStatus.RELAYED.value
            )

    def _build_public_packet(self, msg_id: bytes, ts_ms: int, text: str) -> bytes:
        header = PacketHeader(
            pkt_type=PacketType.CHAT_PUBLIC,
            origin_id=self.identity.node_id,
            target_id=BROADCAST_TARGET,
            ttl=DEFAULT_TTL,
            hop=0,
            msg_id=msg_id,
        )
        sig = sign_public_message(
            self.identity, header.encode(), ts_ms, text.encode("utf-8")
        )
        return encode_packet(
            header,
            ChatPublicPayload(timestamp_ms=ts_ms, text=text, ed25519_sig=sig),
        )

    async def send_public(self, text: str) -> MessageRecord:
        """Sign, cache, persist, and broadcast a #public message."""
        ts_ms = int(time.time() * 1000)
        msg_id = os.urandom(8)
        raw = self._build_public_packet(msg_id, ts_ms, text)
        self.seen_cache.check_and_add(self.identity.node_id, msg_id)
        self.public_cache.add(msg_id, raw)

        sent = await self._send_to_all_links(raw)
        status = DMStatus.RELAYED.value if sent > 0 else DMStatus.SENDING.value
        if sent == 0:
            self._pending_public.add(msg_id)

        record = MessageRecord(
            msg_id=msg_id.hex(),
            channel="#public",
            origin_id=self.identity.node_id_hex,
            target_id=BROADCAST_TARGET.hex(),
            sender_nick=self.nickname,
            text=text,
            timestamp_ms=ts_ms,
            is_outgoing=True,
            status=status,
            hop_count=0,
        )
        self.storage.save_message(record)
        return record

    async def send_dm(self, target_id: bytes, text: str) -> MessageRecord:
        """Encrypt, persist, queue, and transmit a 1-to-1 DM."""
        peer = self.peers.get(target_id)
        if peer is None:
            raise ValueError(f"Unknown peer {target_id.hex()}: no X25519 key")

        ts_ms = int(time.time() * 1000)
        msg_id = os.urandom(8)
        header = PacketHeader(
            pkt_type=PacketType.CHAT_DM,
            origin_id=self.identity.node_id,
            target_id=target_id,
            ttl=DEFAULT_TTL,
            hop=0,
            msg_id=msg_id,
        )
        dm_key = derive_dm_key(
            self.identity.x25519_priv,
            peer.x25519_pub,
            self.identity.node_id,
            target_id,
        )
        nonce, ct = encrypt_dm(
            dm_key, header.encode(), ts_ms, text.encode("utf-8")
        )
        raw = encode_packet(
            header,
            ChatDmPayload(timestamp_ms=ts_ms, nonce=nonce, ciphertext=ct),
        )
        self.seen_cache.check_and_add(self.identity.node_id, msg_id)
        self.dm_queue.enqueue(msg_id, target_id, raw)

        reachable = peer.connected and bool(self.links)
        status = DMStatus.RELAYED.value if reachable else DMStatus.SENDING.value
        record = MessageRecord(
            msg_id=msg_id.hex(),
            channel=peer.node_id_hex,
            origin_id=self.identity.node_id_hex,
            target_id=peer.node_id_hex,
            sender_nick=self.nickname,
            text=text,
            timestamp_ms=ts_ms,
            is_outgoing=True,
            status=status,
            hop_count=0,
        )
        self.storage.save_message(record)
        if reachable:
            await self._send_to_all_links(raw)
        return record
