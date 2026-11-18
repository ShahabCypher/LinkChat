"""Cryptographic operations: Ed25519 public signing and ChaCha20-Poly1305 DM AEAD."""

from __future__ import annotations

import os
import struct

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .identity import Identity

HKDF_INFO = b"linkchat-dm-v1"
NONCE_SIZE = 12


def _public_signing_input(
    header_bytes: bytes, timestamp_ms: int, text_bytes: bytes
) -> bytes:
    """Build Ed25519 input excluding mutable ttl and hop bytes (offsets 26..27)."""
    if len(header_bytes) < 26:
        raise ValueError("header_bytes must be at least 26 bytes")
    return header_bytes[:26] + struct.pack("!Q", timestamp_ms) + text_bytes


def sign_public_message(
    identity: Identity,
    header_bytes: bytes,
    timestamp_ms: int,
    text_bytes: bytes,
) -> bytes:
    """Sign a CHAT_PUBLIC message using Ed25519."""
    return identity.sign(_public_signing_input(header_bytes, timestamp_ms, text_bytes))


def verify_public_message(
    ed25519_pub: bytes,
    header_bytes: bytes,
    timestamp_ms: int,
    text_bytes: bytes,
    signature: bytes,
) -> bool:
    """Verify a CHAT_PUBLIC Ed25519 signature."""
    if len(header_bytes) < 26:
        return False
    return Identity.verify(
        ed25519_pub,
        _public_signing_input(header_bytes, timestamp_ms, text_bytes),
        signature,
    )


def derive_dm_key(
    my_x25519_priv: X25519PrivateKey,
    peer_x25519_pub: bytes,
    id_a: bytes,
    id_b: bytes,
) -> bytes:
    """Derive 32-byte ChaCha20-Poly1305 key using X25519 + HKDF-SHA256."""
    if len(id_a) != 8 or len(id_b) != 8:
        raise ValueError("node IDs must be 8 bytes")
    peer_key = X25519PublicKey.from_public_bytes(peer_x25519_pub)
    shared_secret = my_x25519_priv.exchange(peer_key)
    lo, hi = (id_a, id_b) if id_a <= id_b else (id_b, id_a)
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=lo + hi,
        info=HKDF_INFO,
    ).derive(shared_secret)


def build_dm_aad(header_bytes: bytes, timestamp_or_acked_id: bytes | int) -> bytes:
    """Build AEAD Associated Data binding immutable routing metadata."""
    if len(header_bytes) < 26:
        raise ValueError("header_bytes must be at least 26 bytes")
    if isinstance(timestamp_or_acked_id, int):
        suffix = struct.pack("!Q", timestamp_or_acked_id)
    else:
        if len(timestamp_or_acked_id) != 8:
            raise ValueError("acked_msg_id must be 8 bytes")
        suffix = timestamp_or_acked_id
    return header_bytes[:26] + suffix


def encrypt_dm(
    key: bytes,
    header_bytes: bytes,
    timestamp_ms: int,
    plaintext: bytes,
) -> tuple[bytes, bytes]:
    """Encrypt DM plaintext with a fresh random 12-byte nonce and routing AAD."""
    nonce = os.urandom(NONCE_SIZE)
    aad = build_dm_aad(header_bytes, timestamp_ms)
    ciphertext_and_tag = ChaCha20Poly1305(key).encrypt(nonce, plaintext, aad)
    return nonce, ciphertext_and_tag


def decrypt_dm(
    key: bytes,
    header_bytes: bytes,
    timestamp_ms: int,
    nonce: bytes,
    ciphertext_and_tag: bytes,
) -> bytes:
    """Decrypt and authenticate DM ciphertext; raises InvalidTag on tampering."""
    if len(nonce) != NONCE_SIZE:
        raise ValueError("nonce must be 12 bytes")
    aad = build_dm_aad(header_bytes, timestamp_ms)
    return ChaCha20Poly1305(key).decrypt(nonce, ciphertext_and_tag, aad)


def encrypt_dm_ack(
    key: bytes,
    header_bytes: bytes,
    acked_msg_id: bytes,
) -> tuple[bytes, bytes]:
    """Encrypt b'ACK' for DM_ACK with AAD binding acked_msg_id."""
    nonce = os.urandom(NONCE_SIZE)
    aad = build_dm_aad(header_bytes, acked_msg_id)
    ciphertext_and_tag = ChaCha20Poly1305(key).encrypt(nonce, b"ACK", aad)
    return nonce, ciphertext_and_tag


def decrypt_dm_ack(
    key: bytes,
    header_bytes: bytes,
    acked_msg_id: bytes,
    nonce: bytes,
    ciphertext_and_tag: bytes,
) -> bytes:
    """Decrypt and authenticate DM_ACK payload."""
    if len(nonce) != NONCE_SIZE:
        raise ValueError("nonce must be 12 bytes")
    aad = build_dm_aad(header_bytes, acked_msg_id)
    return ChaCha20Poly1305(key).decrypt(nonce, ciphertext_and_tag, aad)
