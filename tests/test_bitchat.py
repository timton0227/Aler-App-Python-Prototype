"""Tests for alertmesh.bitchat: the iPhone app's Bluetooth packets.

Ported from: ../alert-mesh/localPackages/BitFoundation/Tests/BitFoundationTests/
             BinaryProtocolTests.swift, BinaryProtocolPaddingTests.swift and
             PeerIDTests.swift (the parts about packets, padding, compression and the
             peer ID). The Swift tests round-trip only; byte-exact vectors made by the
             Swift code itself come in step 16.2.
"""
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from alertmesh import bitchat
from alertmesh.bitchat import Flags, MessageType, Packet
from alertmesh.chat import Identity

NOW = 1_790_000_000_000
SENDER = bytes.fromhex("0011223344556677")


def packet(payload=b"test payload", **fields):
    values = dict(type=0x01, sender_id=SENDER, timestamp=NOW, payload=payload, ttl=3)
    values.update(fields)
    return Packet(**values)


def header(flags=0, length=0, version=1, kind=1, ttl=10, timestamp=0):
    size = 4 if version == 2 else 2
    return bytes([version, kind, ttl]) + timestamp.to_bytes(8, "big") + bytes([flags]) + length.to_bytes(size, "big")


# --- Layout -----------------------------------------------------------------------


def test_the_layout_byte_by_byte():
    # BLEService's public message "hello", as the Swift source lays it out.
    raw = bitchat.encode(packet(b"hello", type=MessageType.MESSAGE, ttl=7, signature=b"\x55" * 64))
    assert raw == (bytes([1, 2, 7]) + NOW.to_bytes(8, "big") + bytes([Flags.HAS_SIGNATURE]) + b"\x00\x05"
                   + SENDER + b"hello" + b"\x55" * 64)
    assert len(raw) == 91


def test_basic_packet_encoding_decoding():
    original = packet()
    decoded = bitchat.decode(bitchat.encode(original))
    assert decoded == original


def test_packet_with_recipient():
    original = packet(recipient_id=bytes.fromhex("8899aabbccddeeff"))
    raw = bitchat.encode(original)
    assert raw[11] & Flags.HAS_RECIPIENT
    assert bitchat.decode(raw).recipient_id == bytes.fromhex("8899aabbccddeeff")
    assert not bitchat.decode(raw).is_broadcast
    assert packet(recipient_id=bitchat.BROADCAST).is_broadcast and packet().is_broadcast


def test_packet_with_signature():
    original = packet(signature=os.urandom(64))
    assert bitchat.decode(bitchat.encode(original)).signature == original.signature


def test_short_ids_are_padded_with_zeros():
    raw = bitchat.encode(packet(sender_id=b"\x01\x02"))
    assert bitchat.decode(raw).sender_id == b"\x01\x02" + bytes(6)


def test_v2_packet_with_a_route_round_trips_and_v1_ignores_the_route():
    hops = (bytes.fromhex("0102030405060708"), b"\x09")
    v2 = packet(version=2, route=hops)
    decoded = bitchat.decode(bitchat.encode(v2))
    assert decoded.route == (hops[0], b"\x09" + bytes(7))
    assert decoded.version == 2
    v1 = bitchat.encode(packet(route=hops[:1]))
    assert not v1[11] & Flags.HAS_ROUTE and bitchat.decode(v1).route == ()


def test_v1_and_v2_payload_length_difference():
    route = (bytes.fromhex("0102030405060708"),)
    v1 = bitchat.encode(packet(b"test-payload", route=route, ttl=6))
    v2 = bitchat.encode(packet(b"test-payload", route=route, ttl=6, version=2))
    assert len(v2) - len(v1) == 2 + 1 + 8  # longer length field, route count, one hop


def test_v2_packet_without_route_decodes():
    decoded = bitchat.decode(bitchat.encode(packet(version=2)))
    assert decoded.version == 2 and decoded.route == ()


# --- Compression --------------------------------------------------------------------


def test_a_large_compressible_payload_is_compressed_and_round_trips():
    payload = ("This is a test message. " * 200).encode()
    raw = bitchat.encode(packet(payload))
    assert raw[11] & Flags.IS_COMPRESSED
    assert len(raw) < bitchat.V1_HEADER_SIZE + bitchat.SENDER_ID_SIZE + len(payload)
    assert bitchat.decode(raw).payload == payload


def test_small_payloads_are_not_compressed():
    raw = bitchat.encode(packet(b"Hi"))
    assert not raw[11] & Flags.IS_COMPRESSED and bitchat.decode(raw).payload == b"Hi"


def test_should_compress_follows_the_swift_rule():
    assert not bitchat.should_compress(b"a" * 99)
    assert bitchat.should_compress(b"a" * 100)
    assert not bitchat.should_compress(bytes(range(256)))  # every value once: looks compressed already
    text = ("Flood water over the causeway, take the high road. " * 3).encode()
    assert bitchat.should_compress(text)


def test_oversized_payload_claims_are_rejected():
    assert bitchat.decode(header(length=0xFFFF, version=2) + SENDER + b"\x00" * 10) is None
    assert bitchat.decode(header(length=bitchat.MAX_FRAMED_BYTES + 1, version=2) + SENDER) is None


# --- Padding ------------------------------------------------------------------------


def test_padded_and_unpadded_both_decode():
    original = packet()
    padded = bitchat.encode(original, padding=True)
    unpadded = bitchat.encode(original)
    assert len(padded) == 256 and len(padded) >= len(unpadded)
    assert bitchat.decode(padded) == original == bitchat.decode(unpadded)


@pytest.mark.parametrize("size,block", [(10, 256), (240, 256), (241, 241), (256, 256), (257, 512), (496, 512),
                                        (497, 497), (769, 1024), (1009, 1009), (1793, 2048), (2033, 2033)])
def test_padding_blocks(size, block):
    assert len(bitchat.pad(bytes(size), bitchat.optimal_block_size(size))) == block


def test_message_padding_gives_standard_sizes():
    for text in ("Short", "Medium length message content " * 10,
                 "Long message content that should exceed the 512 byte limit " * 20,
                 "Very long message content that should definitely exceed the 2048 byte limit for sure " * 30):
        raw = bitchat.encode(packet(text.encode()), padding=True)
        assert len(raw) in bitchat.BLOCK_SIZES or len(raw) > 2048
        assert bitchat.decode(raw).payload == text.encode()


def test_unpad_checks_every_pad_byte():
    assert bitchat.unpad(b"abc\x02\x02") == b"abc"
    assert bitchat.unpad(b"abc\x01\x02") == b"abc\x01\x02"
    assert bitchat.unpad(b"abc\x00") == b"abc\x00"
    assert bitchat.unpad(b"\x09") == b"\x09"
    assert bitchat.unpad(b"") == b""


def test_invalid_pkcs7_padding_is_rejected_or_harmless():
    original = packet(b"A" * 50)
    padded = bytearray(bitchat.pad(bitchat.encode(original), 256))
    padded[-1] = padded[-1] - 1
    decoded = bitchat.decode(bytes(padded))
    assert decoded is None or decoded.payload == original.payload  # the core reads as it is either way


# --- Malformed input ------------------------------------------------------------------


def test_too_small_random_or_wrong_version_data_is_rejected():
    assert bitchat.decode(bytes(5)) is None
    raw = bytearray(bitchat.encode(packet()))
    raw[0] = 0xFF
    assert bitchat.decode(bytes(raw)) is None
    raw[0] = 99
    assert bitchat.decode(bytes(raw)) is None


def test_payload_length_beyond_the_data():
    data = header(length=0xC1) + b"\x01" * 8 + b"\x02" * 8
    assert len(data) == 30 and bitchat.decode(data) is None


@pytest.mark.parametrize("cut", [0, 5, 10, 15, 20, 25])
def test_truncated_packets(cut):
    assert bitchat.decode(bitchat.encode(packet())[:cut]) is None


def test_compressed_packet_too_short_for_its_original_size():
    assert bitchat.decode(header(flags=Flags.IS_COMPRESSED, length=1) + b"\x01" * 8 + b"\x99") is None


def test_compressed_packet_with_unreasonable_original_size():
    data = header(flags=Flags.IS_COMPRESSED, length=0x10) + b"\x01" * 8 + b"\x20\x00" + b"\x01\x02\x03\x04"
    assert bitchat.decode(data.ljust(37, b"\x00")) is None


def test_compressed_packet_with_suspicious_ratio():
    assert bitchat.decode(header(flags=Flags.IS_COMPRESSED, length=3) + b"\x01" * 8 + b"\xff\xff\x99") is None


def test_packet_designed_to_overflow():
    data = header(flags=Flags.HAS_RECIPIENT | Flags.HAS_SIGNATURE, length=0xFFFE) + b"\x01" * 8 + b"\x02" * 8
    assert bitchat.decode(data + b"\x01\x02") is None


@pytest.mark.parametrize("size", [0, 1, 5, 10, 12])
def test_incomplete_headers(size):
    assert bitchat.decode(b"\x01" * size) is None


def test_boundaries():
    core = bitchat.encode(packet())
    assert bitchat.decode(core[:len(core) - 10]) is None
    empty = header(length=0) + b"\x01" * 8
    assert bitchat.decode(empty).payload == b""


def test_bytes_after_a_packet_are_ignored():
    original = packet(b"hello")
    assert bitchat.decode(bitchat.encode(original) + b"trailing") == original


# --- Signatures ---------------------------------------------------------------------


def test_signing_bytes_are_padded_with_ttl_zero_and_no_signature_or_rsr():
    signed_view = bitchat.signing_bytes(packet(b"hello", type=2, ttl=7, signature=b"\x01" * 64, is_rsr=True))
    expected = bytes([1, 2, 0]) + NOW.to_bytes(8, "big") + b"\x00" + b"\x00\x05" + SENDER + b"hello"
    assert signed_view == expected + bytes([229]) * 229  # padded to 256
    assert len(signed_view) == 256


def test_sign_and_verify():
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes_raw()
    signed = bitchat.sign(packet(b"hello", type=2, ttl=7), key)
    assert bitchat.verify(signed, public)
    received = bitchat.decode(bitchat.encode(signed))
    assert bitchat.verify(received, public)


def test_ttl_and_rsr_changes_keep_the_signature():
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes_raw()
    raw = bitchat.encode(bitchat.sign(packet(b"hello", type=2, ttl=7), key))
    relayed = bitchat.set_ttl(raw, 3)
    assert relayed[2] == 3 and bitchat.verify(bitchat.decode(relayed), public)
    assert bitchat.verify(replace(bitchat.decode(raw), is_rsr=True), public)


def test_any_other_change_breaks_the_signature():
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes_raw()
    signed = bitchat.sign(packet(b"hello", type=2, ttl=7), key)
    for changed in (replace(signed, payload=b"hellO"), replace(signed, timestamp=NOW + 1),
                    replace(signed, type=3), replace(signed, sender_id=bytes(8)),
                    replace(signed, recipient_id=bytes(8))):
        assert not bitchat.verify(changed, public)
    assert not bitchat.verify(signed, Ed25519PrivateKey.generate().public_key().public_bytes_raw())
    assert not bitchat.verify(replace(signed, signature=None), public)
    assert not bitchat.verify(signed, b"short")


def test_a_compressed_packet_is_signed_over_its_compressed_bytes_and_checked_from_the_air():
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes_raw()
    text = ("Flood water over the causeway, take the high road north to the school. " * 3).encode()
    signed = bitchat.sign(packet(text, type=2, ttl=7), key)
    assert signed.compressed is not None
    raw = bitchat.encode(signed)
    assert raw[11] & Flags.IS_COMPRESSED
    received = bitchat.decode(raw)
    assert received.payload == text and received.compressed == signed.compressed
    assert bitchat.verify(received, public)


def test_a_packet_from_another_compressor_is_checked_on_its_own_bytes():
    """A sender whose compressor makes other bytes (say, level 9) still verifies here:
    the signed bytes are rebuilt from what came off the air, not compressed again."""
    import zlib

    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes_raw()
    text = ("Calls for help near the river crossing, bring rope and a boat please. " * 4).encode()
    engine = zlib.compressobj(9, zlib.DEFLATED, -15, 9, zlib.Z_FILTERED)
    theirs = engine.compress(text) + engine.flush()
    assert theirs != bitchat.compress(text)
    signed = bitchat.sign(packet(text, type=2, ttl=7, compressed=theirs), key)
    received = bitchat.decode(bitchat.encode(signed))
    assert received.compressed == theirs and bitchat.verify(received, public)


# --- Peer ID and bookkeeping --------------------------------------------------------


def test_peer_id_is_the_start_of_the_sha256_of_the_x25519_key():
    key = bytes(range(32))
    assert bitchat.peer_id(key) == hashlib.sha256(key).digest()[:8]
    identity = Identity("Me")
    assert identity.peer_id == bitchat.peer_id(identity.chat_key) and len(identity.peer_id) == 8


def test_identity_signs_packets_with_its_signing_key():
    identity = Identity("Me")
    signed = identity.sign_packet(packet(b"hi", sender_id=identity.peer_id))
    assert bitchat.verify(signed, identity.signing_key)


def test_dedup_key_tells_same_millisecond_packets_apart():
    a, b = packet(b"one"), packet(b"two")
    assert bitchat.dedup_key(a) != bitchat.dedup_key(b)
    assert bitchat.dedup_key(a) == bitchat.dedup_key(replace(a, ttl=1))  # relayed copies are the same packet
    assert bitchat.dedup_key(a).startswith(SENDER.hex() + f"-{NOW}-1-")


# --- Made by the iPhone's own code (tests/data/bitchat_vectors.json) --------------------
# Written by tools/cross_check_bitchat.py from the app's BitFoundation package and
# CryptoKit, so these run everywhere, also where Swift is missing.

VECTORS = json.loads((Path(__file__).resolve().parent / "data" / "bitchat_vectors.json").read_text())


def vector_packet(v: dict) -> Packet:
    s = v["packet"]
    return Packet(s["type"], bytes.fromhex(s["sender"]), s["timestamp"], bytes.fromhex(s["payload"]), s["ttl"],
                  bytes.fromhex(s["recipient"]) if "recipient" in s else None, None, s["version"],
                  tuple(bytes.fromhex(h) for h in s.get("route", [])), s["is_rsr"])


@pytest.mark.parametrize("v", VECTORS["packets"], ids=[v["name"] for v in VECTORS["packets"]])
def test_the_same_bytes_as_the_iphone(v):
    p = vector_packet(v)
    assert bitchat.encode(p).hex() == v["wire"]
    assert bitchat.signing_bytes(p).hex() == v["signed_view"]
    received = bitchat.decode(bytes.fromhex(v["frame"]))
    assert received.payload == p.payload and received.type == p.type
    assert bitchat.verify(received, bytes.fromhex(VECTORS["public_key"]))


def test_compression_matches_apple_when_the_self_check_says_so():
    if not bitchat.APPLE_COMPRESSION_OK:
        pytest.skip("this computer's zlib compresses differently from Apple's: messages stay short")
    for sample in VECTORS["compression"]:
        assert bitchat.compress(bytes.fromhex(sample["text"])).hex() == sample["apple"]


def test_what_the_phone_app_signs_stays_uncompressed_under_the_safe_limits():
    assert not bitchat.should_compress(b"x" * bitchat.SAFE_MESSAGE_BYTES)
    assert bitchat.SAFE_MESSAGE_BYTES == 99
