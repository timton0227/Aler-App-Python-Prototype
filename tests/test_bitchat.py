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


# --- Announce ---------------------------------------------------------------------------
# Ported from: ../alert-mesh/AlertMeshTests/Protocols/PacketsTests.swift

KEY_A, KEY_B = b"\x11" * 32, b"\x22" * 32


def tlv(kind, value):
    return bytes([kind, len(value)]) + value


def test_announcement_round_trips_neighbors_and_skips_unknown_tlvs():
    neighbors = tuple(bytes([i]) * 8 for i in range(12))
    encoded = bitchat.encode_announcement(bitchat.Announcement("alice", KEY_A, KEY_B, neighbors)) + tlv(0xFF, b"\xab")
    decoded = bitchat.decode_announcement(encoded)
    assert (decoded.nickname, decoded.noise_key, decoded.signing_key) == ("alice", KEY_A, KEY_B)
    assert len(decoded.neighbors) == 10 and decoded.neighbors[0] == neighbors[0] and decoded.neighbors[-1] == neighbors[9]


def test_announcement_encode_rejects_oversized_fields_and_skips_invalid_neighbor_groups():
    assert bitchat.encode_announcement(bitchat.Announcement("a" * 256, KEY_A, KEY_B)) is None
    assert bitchat.encode_announcement(bitchat.Announcement("alice", b"\x55" * 256, KEY_B)) is None
    assert bitchat.encode_announcement(bitchat.Announcement("alice", KEY_A, b"\x66" * 256)) is None
    assert (bitchat.encode_announcement(bitchat.Announcement("alice", KEY_A, KEY_B, (b"\x01\x02\x03",)))
            == bitchat.encode_announcement(bitchat.Announcement("alice", KEY_A, KEY_B)))


def test_announcement_decode_rejects_missing_fields_and_truncation():
    assert bitchat.decode_announcement(tlv(1, b"alice") + tlv(2, KEY_A)) is None
    valid = bitchat.encode_announcement(bitchat.Announcement("alice", KEY_A, KEY_B))
    assert bitchat.decode_announcement(valid[:-1]) is None
    assert bitchat.decode_announcement(tlv(1, b"\xff\xfe") + tlv(2, KEY_A) + tlv(3, KEY_B)) is None  # not UTF-8


def test_announcement_decode_ignores_invalid_neighbor_lengths():
    encoded = bitchat.encode_announcement(bitchat.Announcement("alice", KEY_A, KEY_B)) + tlv(4, b"\x99" * 7)
    assert bitchat.decode_announcement(encoded).neighbors == ()


def test_announcement_capabilities_survive_as_bytes():
    plain = bitchat.encode_announcement(bitchat.Announcement("alice", KEY_A, KEY_B))
    assert bitchat.decode_announcement(plain).capabilities is None
    assert bitchat.decode_announcement(plain + tlv(5, b"\x80\x01")).capabilities == b"\x80\x01"


def test_the_laptop_marker_round_trips_and_is_the_last_tlv():
    a = bitchat.Announcement("Laptop", KEY_A, KEY_B, laptop=True)
    encoded = bitchat.encode_announcement(a)
    assert encoded.endswith(tlv(0x70, b"\x01"))
    assert bitchat.decode_announcement(encoded) == a
    assert not bitchat.decode_announcement(encoded[:-3]).laptop  # an iPhone's announce
    assert not bitchat.decode_announcement(encoded[:-1] + b"\x02").laptop  # a later format we do not know


def test_our_announce_stays_uncompressed_up_to_the_safe_nickname():
    a = bitchat.Announcement("n" * bitchat.SAFE_NICKNAME_BYTES, KEY_A, KEY_B, laptop=True)
    assert len(bitchat.encode_announcement(a)) == bitchat.COMPRESSION_THRESHOLD - 1


# --- Catch-up request ---------------------------------------------------------------------
# Ported from: ../alert-mesh/AlertMeshTests/Sync/RequestSyncPacketFragmentFilterTests.swift and
# the RequestSyncPacket / SyncTypeFlags wire rules.


def test_the_catch_up_request_is_an_empty_filter_for_people_chat_warnings_and_reports():
    raw = bitchat.encode_request_sync(bitchat.catch_up_request())
    assert raw == bytes.fromhex("010001" "07" "020004" "00000001" "030000" "040002" "0318")
    decoded = bitchat.decode_request_sync(raw)
    assert (decoded.p, decoded.m, decoded.data) == (7, 1, b"")
    assert decoded.types == (1 << 0) | (1 << 1) | (1 << 11) | (1 << 12)


def test_request_sync_round_trips_since_and_fragment_filter():
    r = bitchat.RequestSync(8, 1000, b"\x12\x34", bitchat.sync_types(MessageType.OFFICIAL_ALERT), 1_790_000_000_000,
                            "0011223344556677")
    assert bitchat.decode_request_sync(bitchat.encode_request_sync(r)) == r


def test_request_sync_decode_rejects_bad_parameters_and_ignores_unknown_tlvs():
    good = bitchat.encode_request_sync(bitchat.catch_up_request())
    assert bitchat.decode_request_sync(good + b"\x7f\x00\x01\x00") is not None
    assert bitchat.decode_request_sync(good[:-1]) is None  # truncated
    for p, m in ((0, 1), (33, 1), (7, 0)):
        assert bitchat.decode_request_sync(bitchat.encode_request_sync(bitchat.RequestSync(p, m, b""))) is None
    too_big = bitchat.RequestSync(7, 10, b"\x00" * 1025)
    assert bitchat.decode_request_sync(bitchat.encode_request_sync(too_big)) is None
    oversized_filter = bitchat.RequestSync(7, 1, b"", None, None, "a" * 1025)
    assert bitchat.decode_request_sync(bitchat.encode_request_sync(oversized_filter)).fragment_filter is None


# --- Fragments -------------------------------------------------------------------------
# Ported from: ../alert-mesh/AlertMeshTests/Services/BLEOutboundFragmentPlannerTests.swift and
# BLEFragmentAssemblyBufferTests.swift.


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def big_packet(size=600):
    identity = Identity("Big", bytes(range(64)))
    return identity.sign_packet(packet(os.urandom(size), type=MessageType.OFFICIAL_ALERT, ttl=7,
                                       sender_id=identity.peer_id)), identity


def test_split_preserves_the_packet_and_copies_sender_time_ttl():
    original, identity = big_packet()
    fragments = bitchat.split(original, 150, fragment_id=b"\x42" * 8)
    whole = bitchat.encode(original)
    assert len(fragments) == -(-len(whole) // 150)
    for i, f in enumerate(fragments):
        assert (f.type, f.sender_id, f.timestamp, f.ttl, f.signature) == (0x20, original.sender_id, NOW, 7, None)
        assert f.payload[:8] == b"\x42" * 8
        assert int.from_bytes(f.payload[8:10], "big") == i and int.from_bytes(f.payload[10:12], "big") == len(fragments)
        assert f.payload[12] == MessageType.OFFICIAL_ALERT
    assembler = bitchat.FragmentAssembler(Clock())
    results = [assembler.add(bitchat.decode(bitchat.encode(f))) for f in reversed(fragments)]
    assert results[:-1] == [None] * (len(fragments) - 1) and results[-1] == whole
    back = bitchat.decode(results[-1])
    assert back.payload == original.payload and bitchat.verify(back, identity.signing_key)


def test_chunks_are_never_below_64_bytes():
    original, _ = big_packet(300)
    assert all(len(f.payload) - 13 <= 64 for f in bitchat.split(original, 10))
    assert bitchat.chunk_size_for(80) == 64 and bitchat.chunk_size_for(182) == 140


def test_route_aware_fragments_use_version_two():
    original = packet(os.urandom(300), version=2, route=(bytes(8),))
    assert all(f.version == 2 and f.route == (bytes(8),) for f in bitchat.split(original, 100))


def fragment(fid=b"\x01" * 8, index=0, total=2, data=b"x", sender=SENDER, kind=2):
    return packet(fid + index.to_bytes(2, "big") + total.to_bytes(2, "big") + bytes([kind]) + data,
                  type=MessageType.FRAGMENT, sender_id=sender)


def test_duplicates_do_not_complete_early_and_order_does_not_matter():
    assembler = bitchat.FragmentAssembler(Clock())
    assert assembler.add(fragment(index=1, data=b"B")) is None
    assert assembler.add(fragment(index=1, data=b"B")) is None
    assert assembler.add(fragment(index=0, data=b"A")) == b"AB"


def test_same_fragment_id_from_two_senders_stays_apart():
    assembler = bitchat.FragmentAssembler(Clock())
    assembler.add(fragment(index=0, data=b"A"))
    assert assembler.add(fragment(index=1, data=b"Z", sender=b"\x99" * 8)) is None
    assert assembler.add(fragment(index=1, data=b"B")) == b"AB"


@pytest.mark.parametrize("bad", [fragment(total=0), fragment(index=2, total=2), fragment(total=10_001),
                                 packet(b"\x01" * 12, type=MessageType.FRAGMENT)])
def test_invalid_fragment_headers_are_refused(bad):
    assert bitchat.fragment_header(bad) is None
    assert bitchat.FragmentAssembler(Clock()).add(bad) is None


def test_unfinished_packets_expire_after_30_seconds():
    clock = Clock()
    assembler = bitchat.FragmentAssembler(clock)
    assembler.add(fragment(index=0, data=b"A"))
    clock.now += 31
    assert assembler.add(fragment(index=1, data=b"B")) is None  # its first half is gone
    assert assembler.add(fragment(index=0, data=b"A")) == b"AB"


def test_at_most_128_assemblies_the_oldest_goes_first():
    clock = Clock()
    assembler = bitchat.FragmentAssembler(clock)
    for i in range(129):
        clock.now += 0.001
        assembler.add(fragment(fid=i.to_bytes(8, "big"), index=0, data=b"A"))
    assert assembler.add(fragment(fid=(0).to_bytes(8, "big"), index=1, data=b"B")) is None  # evicted
    assert assembler.add(fragment(fid=(128).to_bytes(8, "big"), index=1, data=b"B")) == b"AB"


def test_an_assembly_over_the_size_limit_is_dropped(monkeypatch):
    monkeypatch.setattr(bitchat, "MAX_ASSEMBLED_BYTES", 10)
    assembler = bitchat.FragmentAssembler(Clock())
    assert assembler.add(fragment(index=0, total=3, data=b"12345678")) is None
    assert assembler.add(fragment(index=1, total=3, data=b"12345")) is None  # 13 > 10: dropped
    assert assembler.add(fragment(index=2, total=3, data=b"1")) is None


# --- Notifications as a stream ---------------------------------------------------------------
# Ported from: ../alert-mesh/AlertMeshTests/NotificationStreamAssemblerTests.swift


def stream_packet(ts=0x0102030405):
    return packet(b"\xde\xad\xbe\xef", type=MessageType.MESSAGE, timestamp=ts)


def test_one_frame_across_chunks():
    frame = bitchat.encode(stream_packet())
    stream = bitchat.NotificationStream(Clock())
    assert stream.append(frame[:20]) == []
    assert stream.append(frame[20:]) == [frame]
    assert bitchat.NotificationStream(Clock()).append(frame) == [frame]


def test_several_frames_in_order():
    one, two = bitchat.encode(stream_packet(0xABC)), bitchat.encode(stream_packet(0xDEF))
    stream = bitchat.NotificationStream(Clock())
    assert stream.append((one + two)[:20]) == []
    assert stream.append((one + two)[20:]) == [one, two]


def test_a_stray_byte_before_a_frame_is_dropped():
    frame = bitchat.encode(stream_packet(0xF00))
    assert bitchat.NotificationStream(Clock()).append(b"\x00" + frame) == [frame]


def test_padding_between_frames_is_skipped():
    one = bitchat.encode(stream_packet(0x111), padding=True)
    two = bitchat.encode(stream_packet(0x222), padding=True)
    stream = bitchat.NotificationStream(Clock())
    [first] = stream.append(one)
    [second] = stream.append(two)
    assert bitchat.decode(first).timestamp == 0x111 and bitchat.decode(second).timestamp == 0x222


def test_a_frame_still_incomplete_after_250_ms_is_dropped():
    clock = Clock()
    frame = bitchat.encode(packet(b"x" * 60, type=MessageType.MESSAGE))
    later = bitchat.encode(stream_packet(0x2))
    stream = bitchat.NotificationStream(clock)
    assert stream.append(frame[:25]) == []
    clock.now += 0.1
    assert stream.append(frame[25:30]) == []  # still waiting
    clock.now += 0.3
    assert stream.append(frame[30:35]) == []  # waited too long: thrown away
    assert stream.append(later) == [later]


def test_a_compressed_frame_comes_through_whole():
    text = ("Flood water over the causeway, take the high road north to the school. " * 20).encode()
    frame = bitchat.encode(packet(text, type=MessageType.MESSAGE))
    stream = bitchat.NotificationStream(Clock())
    got = []
    for i in range(0, len(frame), 30):
        got += stream.append(frame[i:i + 30])
    assert got == [frame] and bitchat.decode(got[0]).payload == text
