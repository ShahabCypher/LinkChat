"""Tests for Ed25519/X25519 identity, AEAD DM crypto, TOFU, and safety fingerprints."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from linkchat_core.crypto import (
    decrypt_dm,
    decrypt_dm_ack,
    derive_dm_key,
    encrypt_dm,
    encrypt_dm_ack,
    sign_public_message,
    verify_public_message,
)
from linkchat_core.identity import Identity, compute_safety_fingerprint
from linkchat_core.protocol import BROADCAST_TARGET, PacketHeader, PacketType
from linkchat_core.storage import Storage


def test_identity_node_id_and_persistence(tmp_path: Path) -> None:
    ident = Identity.generate()
    assert len(ident.ed25519_pub) == 32
    assert len(ident.x25519_pub) == 32
    assert ident.node_id == hashlib.sha256(ident.ed25519_pub).digest()[:8]

    ed_priv, x_priv = ident.private_bytes()
    restored = Identity.from_private_bytes(ed_priv, x_priv)
    assert restored.node_id == ident.node_id
    assert restored.ed25519_pub == ident.ed25519_pub
    assert restored.x25519_pub == ident.x25519_pub

    store = Storage(tmp_path)
    loaded, nick = store.load_or_create_identity("Alice")
    loaded2, nick2 = store.load_or_create_identity()
    assert loaded.node_id == loaded2.node_id
    assert nick == "Alice"
    assert nick2 == "Alice"
    store.close()


def test_public_signature_and_ttl_hop_invariance() -> None:
    alice = Identity.generate()
    hdr = PacketHeader(PacketType.CHAT_PUBLIC, alice.node_id, BROADCAST_TARGET, ttl=5, hop=0)
    hdr_bytes = hdr.encode()
    ts = 1730000000000
    text = b"hello everyone"
    sig = sign_public_message(alice, hdr_bytes, ts, text)

    assert verify_public_message(alice.ed25519_pub, hdr_bytes, ts, text, sig)

    # Relay nodes mutate ttl & hop without invalidating the signature
    relayed_hdr = bytearray(hdr_bytes)
    relayed_hdr[26] = 2
    relayed_hdr[27] = 3
    assert verify_public_message(alice.ed25519_pub, bytes(relayed_hdr), ts, text, sig)

    # Tampering with text, timestamp, or header origin fails verification
    assert not verify_public_message(alice.ed25519_pub, hdr_bytes, ts, b"tampered", sig)
    assert not verify_public_message(alice.ed25519_pub, hdr_bytes, ts + 1, text, sig)
    bad_hdr = bytearray(hdr_bytes)
    bad_hdr[10] ^= 0xFF
    assert not verify_public_message(alice.ed25519_pub, bytes(bad_hdr), ts, text, sig)


def test_dm_encryption_aad_and_ack() -> None:
    alice = Identity.generate()
    bob = Identity.generate()
    eve = Identity.generate()

    hdr = PacketHeader(PacketType.CHAT_DM, alice.node_id, bob.node_id, ttl=5, hop=0)
    hdr_bytes = hdr.encode()
    ts = 1730000000999

    alice_key = derive_dm_key(alice.x25519_priv, bob.x25519_pub, alice.node_id, bob.node_id)
    bob_key = derive_dm_key(bob.x25519_priv, alice.x25519_pub, bob.node_id, alice.node_id)
    assert alice_key == bob_key

    nonce, ct = encrypt_dm(alice_key, hdr_bytes, ts, b"secret dm payload")
    assert decrypt_dm(bob_key, hdr_bytes, ts, nonce, ct) == b"secret dm payload"

    # Eve cannot derive the same key
    eve_key = derive_dm_key(eve.x25519_priv, alice.x25519_pub, eve.node_id, alice.node_id)
    with pytest.raises(InvalidTag):
        decrypt_dm(eve_key, hdr_bytes, ts, nonce, ct)

    # Tampering ciphertext fails
    bad_ct = bytearray(ct)
    bad_ct[0] ^= 0x01
    with pytest.raises(InvalidTag):
        decrypt_dm(bob_key, hdr_bytes, ts, nonce, bytes(bad_ct))

    # Tampering AAD (target_id or timestamp) fails
    bad_hdr = bytearray(hdr_bytes)
    bad_hdr[18] ^= 0xFF
    with pytest.raises(InvalidTag):
        decrypt_dm(bob_key, bytes(bad_hdr), ts, nonce, ct)
    with pytest.raises(InvalidTag):
        decrypt_dm(bob_key, hdr_bytes, ts + 1, nonce, ct)

    # DM_ACK round-trip & AAD binding
    ack_hdr = PacketHeader(PacketType.DM_ACK, bob.node_id, alice.node_id, ttl=5, hop=0).encode()
    ack_nonce, ack_ct = encrypt_dm_ack(bob_key, ack_hdr, hdr.msg_id)
    assert decrypt_dm_ack(alice_key, ack_hdr, hdr.msg_id, ack_nonce, ack_ct) == b"ACK"
    with pytest.raises(InvalidTag):
        decrypt_dm_ack(alice_key, ack_hdr, b"\x00" * 8, ack_nonce, ack_ct)


def test_safety_fingerprint_symmetry() -> None:
    alice = Identity.generate()
    bob = Identity.generate()
    fp_ab = compute_safety_fingerprint(alice.ed25519_pub, bob.ed25519_pub)
    fp_ba = compute_safety_fingerprint(bob.ed25519_pub, alice.ed25519_pub)

    assert fp_ab == fp_ba
    assert len(fp_ab.groups) == 6
    assert all(len(g) == 5 and g.isdigit() for g in fp_ab.groups)
    assert len(fp_ab.emojis) == 6


def test_tofu_key_change_warning(tmp_path: Path) -> None:
    store = Storage(tmp_path)
    peer_1 = Identity.generate()
    peer_2 = Identity.generate()

    verified, changed = store.upsert_peer(
        peer_1.node_id, "Bob", peer_1.ed25519_pub, peer_1.x25519_pub
    )
    assert (verified, changed) == (False, False)

    assert store.set_peer_verified(peer_1.node_id_hex, True)
    verified, changed = store.upsert_peer(
        peer_1.node_id, "Bob", peer_1.ed25519_pub, peer_1.x25519_pub
    )
    assert (verified, changed) == (True, False)

    # Same node_id presenting a different key resets verified and raises key_changed
    verified, changed = store.upsert_peer(
        peer_1.node_id, "Bob", peer_2.ed25519_pub, peer_2.x25519_pub
    )
    assert (verified, changed) == (False, True)
    store.close()
