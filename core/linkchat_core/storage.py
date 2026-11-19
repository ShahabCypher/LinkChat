"""SQLite persistence for identity, TOFU peer trust, and chat history."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from .identity import Identity
from .transport import MessageRecord, PeerInfo


def _secure_delete_file(path: Path) -> None:
    """Overwrite a file with random bytes and fsync before unlinking."""
    if not path.exists() or not path.is_file():
        return
    size = path.stat().st_size
    if size > 0:
        with open(path, "r+b") as handle:
            remaining = size
            while remaining > 0:
                chunk = min(remaining, 65536)
                handle.write(os.urandom(chunk))
                remaining -= chunk
            handle.flush()
            os.fsync(handle.fileno())
    path.unlink(missing_ok=True)


class Storage:
    """Thread-safe/injected SQLite store rooted at an explicit data_dir."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "linkchat.db"
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute("PRAGMA secure_delete = ON")
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS identity (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    ed25519_priv BLOB NOT NULL,
                    x25519_priv BLOB NOT NULL,
                    nickname TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS peers (
                    node_id_hex TEXT PRIMARY KEY,
                    node_id BLOB NOT NULL,
                    nickname TEXT NOT NULL,
                    ed25519_pub BLOB NOT NULL,
                    x25519_pub BLOB NOT NULL,
                    verified INTEGER NOT NULL DEFAULT 0,
                    key_changed INTEGER NOT NULL DEFAULT 0,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    msg_id TEXT PRIMARY KEY,
                    channel TEXT NOT NULL,
                    origin_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    sender_nick TEXT NOT NULL,
                    text TEXT NOT NULL,
                    timestamp_ms INTEGER NOT NULL,
                    is_outgoing INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    hop_count INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_channel_ts
                    ON messages (channel, timestamp_ms);
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def close(self) -> None:
        self._conn.close()

    def wipe_and_reinit(self) -> None:
        """Securely overwrite and delete linkchat.db (and sidecars), then recreate an empty DB."""
        row = self._conn.execute(
            "SELECT MAX(timestamp_ms) AS max_ts FROM messages WHERE channel = '#public'"
        ).fetchone()
        prev_max_ts = int(row["max_ts"]) if row is not None and row["max_ts"] is not None else 0
        self._conn.close()
        for suffix in ("", "-wal", "-shm", "-journal"):
            _secure_delete_file(Path(f"{self.db_path}{suffix}"))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        cutoff_ms = max(int(time.time() * 1000), prev_max_ts + 1)
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('min_public_ts_ms', ?)",
                (str(cutoff_ms),),
            )

    def get_min_public_ts_ms(self) -> int:
        """Return the post-wipe public sync cutoff timestamp in ms, or 0 if never wiped."""
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'min_public_ts_ms'"
        ).fetchone()
        return int(row["value"]) if row is not None else 0

    def load_or_create_identity(
        self, nickname: str | None = None
    ) -> tuple[Identity, str]:
        """Load persisted identity & nickname, or generate and save a new one."""
        row = self._conn.execute(
            "SELECT ed25519_priv, x25519_priv, nickname FROM identity WHERE id = 1"
        ).fetchone()
        if row is not None:
            identity = Identity.from_private_bytes(
                bytes(row["ed25519_priv"]), bytes(row["x25519_priv"])
            )
            nick = nickname if nickname is not None else str(row["nickname"])
            if nickname is not None and nickname != row["nickname"]:
                self.save_nickname(nickname)
            return identity, nick

        identity = Identity.generate()
        nick = nickname if nickname is not None else f"Node-{identity.short_tag}"
        ed_priv, x_priv = identity.private_bytes()
        with self._conn:
            self._conn.execute(
                "INSERT INTO identity (id, ed25519_priv, x25519_priv, nickname) VALUES (1, ?, ?, ?)",
                (ed_priv, x_priv, nick),
            )
        return identity, nick

    def save_nickname(self, nickname: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE identity SET nickname = ? WHERE id = 1", (nickname,)
            )

    def upsert_peer(
        self,
        node_id: bytes,
        nickname: str,
        ed25519_pub: bytes,
        x25519_pub: bytes,
        now: float | None = None,
    ) -> tuple[bool, bool]:
        """Apply TOFU peer tracking; return (verified, key_changed)."""
        ts = time.time() if now is None else now
        node_hex = node_id.hex()
        row = self._conn.execute(
            "SELECT ed25519_pub, x25519_pub, verified, key_changed FROM peers WHERE node_id_hex = ?",
            (node_hex,),
        ).fetchone()

        if row is None:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO peers (
                        node_id_hex, node_id, nickname, ed25519_pub, x25519_pub,
                        verified, key_changed, first_seen, last_seen
                    ) VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)
                    """,
                    (node_hex, node_id, nickname, ed25519_pub, x25519_pub, ts, ts),
                )
            return False, False

        keys_match = (
            bytes(row["ed25519_pub"]) == ed25519_pub
            and bytes(row["x25519_pub"]) == x25519_pub
        )
        if keys_match:
            with self._conn:
                self._conn.execute(
                    "UPDATE peers SET nickname = ?, last_seen = ? WHERE node_id_hex = ?",
                    (nickname, ts, node_hex),
                )
            return bool(row["verified"]), bool(row["key_changed"])

        # Key changed for a previously known node_id: reset verification and raise warning flag.
        with self._conn:
            self._conn.execute(
                """
                UPDATE peers
                SET nickname = ?, ed25519_pub = ?, x25519_pub = ?,
                    verified = 0, key_changed = 1, last_seen = ?
                WHERE node_id_hex = ?
                """,
                (nickname, ed25519_pub, x25519_pub, ts, node_hex),
            )
        return False, True

    def set_peer_verified(self, node_id_hex: str, verified: bool = True) -> bool:
        with self._conn:
            cur = self._conn.execute(
                "UPDATE peers SET verified = ?, key_changed = CASE WHEN ? = 1 THEN 0 ELSE key_changed END WHERE node_id_hex = ?",
                (1 if verified else 0, 1 if verified else 0, node_id_hex),
            )
        return cur.rowcount > 0

    def load_peers(self) -> list[PeerInfo]:
        rows = self._conn.execute("SELECT * FROM peers ORDER BY last_seen DESC").fetchall()
        return [
            PeerInfo(
                node_id=bytes(r["node_id"]),
                node_id_hex=str(r["node_id_hex"]),
                nickname=str(r["nickname"]),
                ed25519_pub=bytes(r["ed25519_pub"]),
                x25519_pub=bytes(r["x25519_pub"]),
                hop_count=0,
                rssi=0,
                direct=False,
                connected=False,
                verified=bool(r["verified"]),
                key_changed=bool(r["key_changed"]),
                last_seen=float(r["last_seen"]),
                link_handle=None,
            )
            for r in rows
        ]

    def save_message(self, record: MessageRecord) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO messages (
                    msg_id, channel, origin_id, target_id, sender_nick,
                    text, timestamp_ms, is_outgoing, status, hop_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.msg_id,
                    record.channel,
                    record.origin_id,
                    record.target_id,
                    record.sender_nick,
                    record.text,
                    record.timestamp_ms,
                    1 if record.is_outgoing else 0,
                    record.status,
                    record.hop_count,
                ),
            )

    def update_message_status(self, msg_id: str, status: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE messages SET status = ? WHERE msg_id = ?",
                (status, msg_id),
            )

    def get_history(self, channel: str, limit: int = 200) -> list[MessageRecord]:
        rows = self._conn.execute(
            """
            SELECT msg_id, channel, origin_id, target_id, sender_nick,
                   text, timestamp_ms, is_outgoing, status, hop_count
            FROM messages
            WHERE channel = ?
            ORDER BY timestamp_ms ASC, rowid ASC
            LIMIT ?
            """,
            (channel, limit),
        ).fetchall()
        return [
            MessageRecord(
                msg_id=str(r["msg_id"]),
                channel=str(r["channel"]),
                origin_id=str(r["origin_id"]),
                target_id=str(r["target_id"]),
                sender_nick=str(r["sender_nick"]),
                text=str(r["text"]),
                timestamp_ms=int(r["timestamp_ms"]),
                is_outgoing=bool(r["is_outgoing"]),
                status=str(r["status"]),
                hop_count=int(r["hop_count"]),
            )
            for r in rows
        ]
