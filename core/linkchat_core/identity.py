"""Identity management, Ed25519/X25519 keys, and safety fingerprints."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

# 64 distinct, widely supported Unicode emojis for 6-emoji safety verification.
EMOJI_PALETTE: tuple[str, ...] = (
    "🐶", "🐱", "🦊", "🐻", "🐼", "🐨", "🦁", "🐯",
    "🐸", "🐙", "🐳", "🐬", "🦋", "🐝", "🦉", "🦅",
    "🐢", "🦎", "🦄", "🐉", "🌵", "🌲", "🌴", "🌻",
    "🌹", "🍄", "🍎", "🍊", "🍋", "🍇", "🍉", "🍓",
    "🍒", "🥑", "🥨", "🍕", "🚀", "🛸", "⚓", "⛵",
    "🚲", "🚂", "✈️", "🛰️", "🌋", "🏔️", "🏝️", "🌈",
    "⚡", "🔥", "❄️", "💧", "🌙", "☀️", "⭐", "💎",
    "🔑", "🔒", "🔔", "🎵", "🎸", "🎲", "🧩", "🧭",
)


def compute_node_id(ed25519_pub: bytes) -> bytes:
    """Derive 8-byte node_id from an Ed25519 public key."""
    if len(ed25519_pub) != 32:
        raise ValueError("Ed25519 public key must be 32 bytes")
    return hashlib.sha256(ed25519_pub).digest()[:8]


def normalize_node_id(node_id: bytes | str) -> bytes:
    """Convert 8-byte or 16-char hex node_id into 8 raw bytes."""
    if isinstance(node_id, bytes):
        if len(node_id) != 8:
            raise ValueError("node_id must be 8 bytes")
        return node_id
    if isinstance(node_id, str):
        raw = bytes.fromhex(node_id.strip())
        if len(raw) != 8:
            raise ValueError("node_id hex must decode to 8 bytes")
        return raw
    raise TypeError("node_id must be bytes or hex str")


@dataclass(frozen=True, slots=True)
class SafetyFingerprint:
    """Symmetric MITM verification fingerprint for two peers."""

    safety_number: str
    emoji_hash: str
    groups: tuple[str, ...]
    emojis: tuple[str, ...]


def compute_safety_fingerprint(ed_pub_a: bytes, ed_pub_b: bytes) -> SafetyFingerprint:
    """Compute symmetric 30-digit safety number and 6-emoji fingerprint."""
    if len(ed_pub_a) != 32 or len(ed_pub_b) != 32:
        raise ValueError("Ed25519 public keys must be 32 bytes")
    lo, hi = (ed_pub_a, ed_pub_b) if ed_pub_a <= ed_pub_b else (ed_pub_b, ed_pub_a)
    digest = hashlib.sha256(b"linkchat-fp-v1" + lo + hi).digest()

    groups = tuple(
        f"{int.from_bytes(digest[i * 4 : (i + 1) * 4], 'big') % 100000:05d}"
        for i in range(6)
    )
    emojis = tuple(EMOJI_PALETTE[digest[i] % len(EMOJI_PALETTE)] for i in range(6))
    return SafetyFingerprint(
        safety_number=" ".join(groups),
        emoji_hash=" ".join(emojis),
        groups=groups,
        emojis=emojis,
    )


class Identity:
    """Node identity holding Ed25519 signing and X25519 DH keypairs."""

    def __init__(
        self,
        ed25519_priv: Ed25519PrivateKey,
        x25519_priv: X25519PrivateKey,
    ) -> None:
        self.ed25519_priv = ed25519_priv
        self.x25519_priv = x25519_priv
        self.ed25519_pub: bytes = ed25519_priv.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        )
        self.x25519_pub: bytes = x25519_priv.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        )
        self.node_id: bytes = compute_node_id(self.ed25519_pub)
        self.node_id_hex: str = self.node_id.hex()
        self.short_tag: str = self.node_id_hex[:4]

    @classmethod
    def generate(cls) -> Identity:
        """Generate fresh random Ed25519 and X25519 keypairs."""
        return cls(
            Ed25519PrivateKey.generate(),
            X25519PrivateKey.generate(),
        )

    @classmethod
    def from_private_bytes(cls, ed_bytes: bytes, x_bytes: bytes) -> Identity:
        """Restore Identity from raw 32-byte Ed25519 and X25519 private keys."""
        return cls(
            Ed25519PrivateKey.from_private_bytes(ed_bytes),
            X25519PrivateKey.from_private_bytes(x_bytes),
        )

    def private_bytes(self) -> tuple[bytes, bytes]:
        """Export raw 32-byte private keys (ed25519, x25519) for persistence."""
        ed_raw = self.ed25519_priv.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()
        )
        x_raw = self.x25519_priv.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()
        )
        return ed_raw, x_raw

    def sign(self, data: bytes) -> bytes:
        """Sign bytes with this identity's Ed25519 private key."""
        return self.ed25519_priv.sign(data)

    @staticmethod
    def verify(ed25519_pub: bytes, data: bytes, signature: bytes) -> bool:
        """Verify an Ed25519 signature against a 32-byte public key."""
        if len(ed25519_pub) != 32 or len(signature) != 64:
            return False
        try:
            pub = Ed25519PublicKey.from_public_bytes(ed25519_pub)
            pub.verify(signature, data)
            return True
        except (InvalidSignature, ValueError):
            return False

    @staticmethod
    def validate_x25519_pub(x25519_pub: bytes) -> bool:
        """Return True if x25519_pub is a valid 32-byte X25519 public key."""
        if len(x25519_pub) != 32:
            return False
        try:
            X25519PublicKey.from_public_bytes(x25519_pub)
            return True
        except ValueError:
            return False
