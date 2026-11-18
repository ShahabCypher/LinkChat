"""In-memory deduplication and store-and-forward caches."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass


class SeenCache:
    """Bounded LRU/TTL cache keyed by (origin_id, msg_id) for packet deduplication."""

    def __init__(self, max_size: int = 2000, ttl_sec: float = 3600.0) -> None:
        self.max_size = max_size
        self.ttl_sec = ttl_sec
        self._entries: OrderedDict[tuple[bytes, bytes], float] = OrderedDict()

    def _evict_expired(self, now: float) -> None:
        while self._entries:
            oldest_key, ts = next(iter(self._entries.items()))
            if now - ts <= self.ttl_sec:
                break
            self._entries.popitem(last=False)

    def check_and_add(
        self, origin_id: bytes, msg_id: bytes, now: float | None = None
    ) -> bool:
        """Return True if already seen (duplicate), else record and return False."""
        ts = time.monotonic() if now is None else now
        self._evict_expired(ts)
        key = (origin_id, msg_id)
        if key in self._entries:
            self._entries.move_to_end(key)
            return True
        self._entries[key] = ts
        if len(self._entries) > self.max_size:
            self._entries.popitem(last=False)
        return False

    def __len__(self) -> int:
        return len(self._entries)


@dataclass(slots=True)
class CachedPublicPacket:
    msg_id: bytes
    raw_packet: bytes
    created_at: float


class PublicMessageCache:
    """Stores the last 100 CHAT_PUBLIC packets (max age 2 hours) for SYNC_DIGEST/SYNC_REQ."""

    def __init__(self, max_size: int = 100, max_age_sec: float = 7200.0) -> None:
        self.max_size = max_size
        self.max_age_sec = max_age_sec
        self._items: OrderedDict[bytes, CachedPublicPacket] = OrderedDict()

    def _prune(self, now: float) -> None:
        while self._items:
            _, item = next(iter(self._items.items()))
            if now - item.created_at <= self.max_age_sec:
                break
            self._items.popitem(last=False)

    def add(self, msg_id: bytes, raw_packet: bytes, now: float | None = None) -> None:
        ts = time.monotonic() if now is None else now
        self._prune(ts)
        if msg_id in self._items:
            self._items.move_to_end(msg_id)
            return
        self._items[msg_id] = CachedPublicPacket(
            msg_id=msg_id, raw_packet=raw_packet, created_at=ts
        )
        if len(self._items) > self.max_size:
            self._items.popitem(last=False)

    def get(self, msg_id: bytes, now: float | None = None) -> bytes | None:
        ts = time.monotonic() if now is None else now
        self._prune(ts)
        item = self._items.get(msg_id)
        return item.raw_packet if item is not None else None

    def msg_ids(self, now: float | None = None) -> list[bytes]:
        ts = time.monotonic() if now is None else now
        self._prune(ts)
        return list(self._items.keys())

    def __len__(self) -> int:
        return len(self._items)


@dataclass(slots=True)
class QueuedDM:
    msg_id: bytes
    target_id: bytes
    raw_packet: bytes
    created_at: float


class OutboundDMQueue:
    """Holds undelivered outbound CHAT_DM packets (max age 24 hours) until DM_ACK."""

    def __init__(self, max_age_sec: float = 86400.0) -> None:
        self.max_age_sec = max_age_sec
        self._items: OrderedDict[bytes, QueuedDM] = OrderedDict()

    def _prune(self, now: float) -> None:
        while self._items:
            _, item = next(iter(self._items.items()))
            if now - item.created_at <= self.max_age_sec:
                break
            self._items.popitem(last=False)

    def enqueue(
        self,
        msg_id: bytes,
        target_id: bytes,
        raw_packet: bytes,
        now: float | None = None,
    ) -> None:
        ts = time.monotonic() if now is None else now
        self._prune(ts)
        self._items[msg_id] = QueuedDM(
            msg_id=msg_id, target_id=target_id, raw_packet=raw_packet, created_at=ts
        )

    def ack(self, msg_id: bytes) -> bool:
        return self._items.pop(msg_id, None) is not None

    def pending_for(self, target_id: bytes, now: float | None = None) -> list[QueuedDM]:
        ts = time.monotonic() if now is None else now
        self._prune(ts)
        return [item for item in self._items.values() if item.target_id == target_id]

    def __len__(self) -> int:
        return len(self._items)
