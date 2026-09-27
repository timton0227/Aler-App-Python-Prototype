"""Tests for alertmesh.wire.

Swift reference: ../alert-mesh/AlertMeshTests/AlertMesh/Protocols/AlertPacketsTests.swift.
Test names keep the Swift test name in their docstring where one exists.
"""
from alertmesh import wire
from alertmesh.wire import HazardType, Severity


def test_constants_match_the_swift_app():
    assert wire.ALERT_ID_LENGTH == 16
    assert wire.SIGNATURE_LENGTH == 64
    assert wire.HEADLINE_MAX_BYTES == 100
    assert wire.ACTION_TEXT_MAX_BYTES == 100
    assert (wire.AREA_GEOHASH_MIN_LENGTH, wire.AREA_GEOHASH_MAX_LENGTH) == (2, 8)
    assert wire.MAX_AREA_CELLS == 4
    assert wire.MAX_LIFETIME_MS == 604_800_000
    assert wire.ALERT_SIGNING_CONTEXT == "alertmesh-official-v1"
    assert wire.CANCELLATION_SIGNING_CONTEXT == "alertmesh-cancel-v1"


def test_constants_budget_is_derived_from_packet_overhead():
    """Swift: budgetIsDerivedFromUpstreamPacketOverhead."""
    assert wire.MAX_ENCODED_BYTES == 383


def test_constants_hazard_wire_values_are_frozen():
    """Swift: hazardWireValuesAreFrozen."""
    assert HazardType.FLOOD == 0x01
    assert HazardType.BUSHFIRE == 0x02
    assert HazardType.STORM == 0x03
    assert HazardType.FIRE_WEATHER == 0x04
    assert HazardType.CYCLONE == 0x05
    assert HazardType.HEATWAVE == 0x06


def test_constants_severity_values_are_frozen_and_ordered():
    """Swift: severityIsOrdered."""
    assert (Severity.ADVICE, Severity.WATCH_AND_ACT, Severity.EMERGENCY_WARNING) == (1, 2, 3)
    assert Severity.ADVICE < Severity.WATCH_AND_ACT < Severity.EMERGENCY_WARNING


def test_constants_retired_tlv_0x06_is_not_reused():
    assert 0x06 not in {t.value for t in wire.TLVType}


def test_constants_pinned_key_is_the_documented_dev_key():
    assert wire.PINNED_PUBLIC_KEY.hex() == "365182c9ee5be834763d712e7f0a26b0b6bbe77ed7e5c405e82b340acfdcf043"


_KNOWN = {t.value for t in wire.TLVType}
_REPEAT = frozenset({wire.TLVType.AREA_GEOHASH})


def test_tlv_put_writes_type_big_endian_length_and_value():
    assert wire.put_tlv(0x04, b"AB") == bytes([0x04, 0x00, 0x02, 0x41, 0x42])
    assert wire.put_tlv(0x0B, bytes(300))[:3] == bytes([0x0B, 0x01, 0x2C])


def test_tlv_read_round_trips_and_keeps_order():
    data = wire.put_tlv(0x01, b"\x01") + wire.put_tlv(0x03, b"r7hg") + wire.put_tlv(0x03, b"r7hu")
    assert wire.read_tlvs(data, _KNOWN, _REPEAT) == [(1, b"\x01"), (3, b"r7hg"), (3, b"r7hu")]


def test_tlv_read_returns_unknown_types_for_the_caller_to_skip():
    data = wire.put_tlv(0x7F, b"\xde\xad") + wire.put_tlv(0x06, bytes(32))
    assert wire.read_tlvs(data, _KNOWN, _REPEAT) == [(0x7F, b"\xde\xad"), (0x06, bytes(32))]


def test_tlv_read_rejects_a_repeated_known_field():
    data = wire.put_tlv(0x0A, b"\x03") + wire.put_tlv(0x0A, b"\x01")
    assert wire.read_tlvs(data, _KNOWN, _REPEAT) is None


def test_tlv_read_allows_repeated_unknown_fields():
    data = wire.put_tlv(0x7F, b"a") + wire.put_tlv(0x7F, b"b")
    assert wire.read_tlvs(data, _KNOWN, _REPEAT) is not None


def test_tlv_read_rejects_a_field_running_past_the_end():
    data = wire.put_tlv(0x04, b"ABC")[:-1]
    assert wire.read_tlvs(data, _KNOWN, _REPEAT) is None


def test_tlv_read_ignores_one_or_two_stray_trailing_bytes():
    data = wire.put_tlv(0x04, b"AB")
    assert wire.read_tlvs(data + b"\x00\x00", _KNOWN, _REPEAT) == [(4, b"AB")]
    assert wire.read_tlvs(b"", _KNOWN, _REPEAT) == []


def _fields_ok(cells=("r7hg",), headline=10, action=5, issued=1_000, expires=2_000):
    return wire.alert_fields_are_valid(list(cells), headline, action, issued, expires)


def test_validation_accepts_a_normal_alert():
    assert _fields_ok()
    assert _fields_ok(action=0)  # Swift: emptyActionTextIsAllowed
    assert _fields_ok(cells=("r7hg", "r7hu", "r7hs", "r7hk"))


def test_validation_area_cells():
    """Swift: rejectsMissingAreaCells, rejectsTooManyAreaCells,
    rejectsInvalidGeohashCharacters, rejectsAreaCellOutsidePrecisionBounds."""
    assert not _fields_ok(cells=())
    assert not _fields_ok(cells=("r7hg",) * 5)
    assert not _fields_ok(cells=("ails",))
    assert not _fields_ok(cells=("r",))
    assert not _fields_ok(cells=("r7hg2bcd9",))
    assert not _fields_ok(cells=("R7HG",))  # canonical lowercase only


def test_validation_text_lengths():
    """Swift: rejectsOversizedHeadline, rejectsEmptyHeadline."""
    assert not _fields_ok(headline=0)
    assert not _fields_ok(headline=101)
    assert _fields_ok(headline=100, action=100)
    assert not _fields_ok(action=101)


def test_validation_times():
    """Swift: rejectsExpiryBeforeIssue, rejectsExpiryBeyondSevenDays."""
    assert not _fields_ok(issued=2_000, expires=2_000)
    assert not _fields_ok(issued=2_000, expires=1_000)
    assert _fields_ok(issued=0, expires=wire.MAX_LIFETIME_MS)
    assert not _fields_ok(issued=0, expires=wire.MAX_LIFETIME_MS + 1)


def test_validation_unknown_hazard_code_is_kept_but_has_no_type():
    alert = wire.OfficialAlert(bytes(16), 0x7F, Severity.ADVICE, ("r7hg",), "h", "", 1, 2, bytes(64))
    assert alert.hazard is None
    assert alert.hazard_code == 0x7F
    assert wire.OfficialAlert(bytes(16), 2, Severity.ADVICE, ("r7hg",), "h", "", 1, 2, bytes(64)).hazard is HazardType.BUSHFIRE


# Frozen vectors, copied from AlertPacketsTests.swift (made by scripts/sign-test-alert.swift).
FROZEN_ALERT_HEX = (
    "01000101020010000102030405060708090a0b0c0d0e0f0300047237686703000472376875"
    "0400244275736866697265206174204d6f756e74204261726b6572202d206c65617665206e"
    "6f7705002754726176656c206e6f727468206f6e204869676877617920312e20446f206e6f"
    "7420776169742e0700080000018bcfe568000800080000018bd12eff00090001020a000103"
    "0b0040efefaaa2e7b4f16203f884e2c60836b273823f6769aba723273827f614a118b328f8"
    "80187f4a42de85725d2566a6a775526c8cb1e2c87094999584e030ac5902"
)
FROZEN_CANCELLATION_HEX = (
    "01000102020010000102030405060708090a0b0c0d0e0f0700080000018bd01c56800b00"
    "40f1a7e51fe5929aa9f0b1cf3e4930595b4b5aaaebc2d1b125101abb5cbac8d7e7302fdf"
    "3ac605770593433bd484c1e846f412398163c9b85611f812584f666b0b"
)
FROZEN_FIELDS = dict(
    alert_id=bytes(range(16)),
    hazard_code=HazardType.BUSHFIRE,
    severity=Severity.EMERGENCY_WARNING,
    area_cells=("r7hg", "r7hu"),
    headline="Bushfire at Mount Barker - leave now",
    action_text="Travel north on Highway 1. Do not wait.",
    issued_at=1_700_000_000_000,
    expires_at=1_700_000_000_000 + 6 * 60 * 60 * 1000,
)


def test_signing_bytes_start_with_the_frozen_context_prefix():
    """Swift: signingContextIsFrozen. The 22 bytes from docs/ALERT-WIRE-FORMAT.md."""
    frozen = bytes.fromhex("15616c6572746d6573682d6f6666696369616c2d7631")
    assert wire.alert_signing_bytes(**FROZEN_FIELDS)[:22] == frozen


def test_signing_bytes_layout_matches_the_spec():
    sb = wire.alert_signing_bytes(**FROZEN_FIELDS)
    assert sb[22:38] == bytes(range(16))          # alertID
    assert sb[38:41] == bytes([0x02, 0x03, 0x02])  # hazard, severity, cell count
    assert sb[41:47] == b"\x00\x04r7hg"            # first cell, length-prefixed
    assert sb[-16:] == (1_700_000_000_000).to_bytes(8, "big") + (1_700_021_600_000).to_bytes(8, "big")


def test_signing_bytes_are_what_the_swift_signature_covers():
    """The Swift-made signature in the frozen vector verifies over Python's bytes."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    swift_signature = bytes.fromhex(FROZEN_ALERT_HEX)[-64:]
    key = Ed25519PublicKey.from_public_bytes(wire.PINNED_PUBLIC_KEY)
    key.verify(swift_signature, wire.alert_signing_bytes(**FROZEN_FIELDS))  # raises if wrong


def _frozen_alert(signature: bytes) -> wire.OfficialAlert:
    return wire.OfficialAlert(**FROZEN_FIELDS, signature=signature)


def test_frozen_vector_prefix_matches_first_151_bytes():
    """docs/ALERT-WIRE-FORMAT.md: everything before the signature must match byte for byte.

    Python's signer is deterministic (RFC 8032) and Apple's is randomised, so the
    signature bytes themselves differ; they only have to verify.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    dev_private = bytes.fromhex("9077bd3b4bf110ba5c9bc7375e7e771d11597918ffa4a9ddc7a2f089a291f8cc")
    signature = Ed25519PrivateKey.from_private_bytes(dev_private).sign(
        wire.alert_signing_bytes(**FROZEN_FIELDS)
    )
    encoded = wire.encode_alert(_frozen_alert(signature))
    assert len(encoded) == 215
    assert encoded[:151] == bytes.fromhex(FROZEN_ALERT_HEX)[:151]


def test_frozen_vector_prefix_whole_packet_with_the_swift_signature():
    """With the Swift-made signature, all 215 bytes are identical."""
    frozen = bytes.fromhex(FROZEN_ALERT_HEX)
    assert wire.encode_alert(_frozen_alert(frozen[-64:])) == frozen


def test_frozen_vector_prefix_first_seven_bytes():
    """Swift: encodedPrefixIsFrozen. kind TLV, then the alertID TLV header."""
    encoded = wire.encode_alert(_frozen_alert(bytes(64)))
    assert encoded[:7] == bytes([0x01, 0x00, 0x01, 0x01, 0x02, 0x00, 0x10])
