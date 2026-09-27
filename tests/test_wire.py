"""Tests for alertmesh.wire.

Swift reference: ../alert-mesh/AlertMeshTests/AlertMesh/Protocols/AlertPacketsTests.swift.
Test names keep the Swift test name in their docstring where one exists.
"""
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

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


# --- Decode (step 2.6). Helpers mirror makeSignedAlert in AlertPacketsTests.swift.

PUBLISHER = Ed25519PrivateKey.generate()
PUBLISHER_PUBLIC = PUBLISHER.public_key().public_bytes_raw()


def make_signed_alert(
    hazard=HazardType.FLOOD,
    severity=Severity.WATCH_AND_ACT,
    area_cells=("r7hg",),
    headline="Moderate flooding at Fitzroy Crossing",
    action_text="Move to higher ground now.",
    issued_at=1_700_000_000_000,
    lifetime_ms=6 * 60 * 60 * 1000,
    key=None,
    hazard_code=None,
):
    code = int(hazard) if hazard_code is None else hazard_code
    alert_id = os.urandom(16)
    expires_at = issued_at + lifetime_ms
    sb = wire.alert_signing_bytes(alert_id, code, severity, area_cells, headline, action_text, issued_at, expires_at)
    signature = (key or PUBLISHER).sign(sb)
    return wire.OfficialAlert(alert_id, code, severity, tuple(area_cells), headline, action_text, issued_at, expires_at, signature)


def value_offset(tlv_type, data):
    """Swift: valueOffset(ofTLVType:in:). Walks the structure instead of scanning bytes."""
    off = 0
    while off + 3 <= len(data):
        t, length = data[off], (data[off + 1] << 8) | data[off + 2]
        if off + 3 + length > len(data):
            return None
        if t == tlv_type:
            return off + 3
        off += 3 + length
    return None


def test_decodes_frozen_vector_from_the_signing_script():
    """Swift: decodesTheFrozenVectorFromTheSigningScript."""
    data = bytes.fromhex(FROZEN_ALERT_HEX)
    alert = wire.decode(data)
    assert alert is not None
    assert wire.verify_pinned(alert)
    assert alert.hazard is HazardType.BUSHFIRE
    assert alert.severity is Severity.EMERGENCY_WARNING
    assert alert.area_cells == ("r7hg", "r7hu")
    assert alert.headline == "Bushfire at Mount Barker - leave now"
    assert alert.action_text == "Travel north on Highway 1. Do not wait."
    assert alert.issued_at == 1_700_000_000_000
    assert alert.expires_at == 1_700_000_000_000 + 6 * 60 * 60 * 1000
    assert alert.alert_id == bytes(range(16))
    assert len(data) == 215


def test_decodes_frozen_vector_fails_against_an_unrelated_key():
    """Swift: frozenVectorFailsAgainstAnUnrelatedKey."""
    assert not wire.verify(wire.decode(bytes.fromhex(FROZEN_ALERT_HEX)), PUBLISHER_PUBLIC)


def test_decode_round_trip():
    """Swift: alertRoundTrip."""
    alert = make_signed_alert(hazard=HazardType.BUSHFIRE, severity=Severity.EMERGENCY_WARNING)
    decoded = wire.decode(wire.encode_alert(alert))
    assert decoded == alert
    assert wire.verify(decoded, PUBLISHER_PUBLIC)
    assert decoded.hazard is HazardType.BUSHFIRE


def test_decode_multiple_area_cells_round_trip_in_order():
    """Swift: multipleAreaCellsRoundTripInOrder."""
    cells = ("r7hg", "r7hu", "r7hs", "r7hk")
    decoded = wire.decode(wire.encode_alert(make_signed_alert(area_cells=cells)))
    assert decoded.area_cells == cells
    assert wire.verify(decoded, PUBLISHER_PUBLIC)


def test_decode_empty_action_text_is_allowed():
    """Swift: emptyActionTextIsAllowed."""
    decoded = wire.decode(wire.encode_alert(make_signed_alert(action_text="")))
    assert decoded is not None and wire.verify(decoded, PUBLISHER_PUBLIC)


def test_decode_forged_signature_fails_verification():
    """Swift: forgedSignatureFailsVerification, alertFromAnotherKeyFailsAgainstPinnedPublisher."""
    attacker = Ed25519PrivateKey.generate()
    decoded = wire.decode(wire.encode_alert(make_signed_alert(key=attacker)))
    assert decoded is not None
    assert not wire.verify(decoded, PUBLISHER_PUBLIC)
    assert not wire.verify_pinned(wire.decode(wire.encode_alert(make_signed_alert())))


def test_decode_rejects_bounds():
    """Swift: rejectsExpiryBeyondSevenDays, rejectsOversizedHeadline, rejectsEmptyHeadline,
    rejectsMissingAreaCells, rejectsTooManyAreaCells, rejectsInvalidGeohashCharacters,
    rejectsAreaCellOutsidePrecisionBounds."""
    bad = [
        make_signed_alert(lifetime_ms=wire.MAX_LIFETIME_MS + 1),
        make_signed_alert(headline="a" * 101),
        make_signed_alert(headline=""),
        make_signed_alert(area_cells=()),
        make_signed_alert(area_cells=("r7hg",) * 5),
        make_signed_alert(area_cells=("ails",)),
        make_signed_alert(area_cells=("r",)),
        make_signed_alert(area_cells=("r7hg2bcd9",)),
    ]
    for alert in bad:
        assert wire.decode(wire.encode_alert(alert)) is None


def test_decode_rejects_expiry_before_issue():
    """Swift: rejectsExpiryBeforeIssue."""
    a = make_signed_alert()
    backwards = wire.OfficialAlert(a.alert_id, a.hazard_code, a.severity, a.area_cells, a.headline,
                                   a.action_text, a.expires_at, a.issued_at, a.signature)
    assert wire.decode(wire.encode_alert(backwards)) is None


def test_decode_rejects_unknown_severity():
    """Swift: rejectsUnknownSeverity."""
    encoded = bytearray(wire.encode_alert(make_signed_alert()))
    encoded[value_offset(0x0A, encoded)] = 0x7F
    assert wire.decode(bytes(encoded)) is None


def test_decode_tolerates_unknown_hazard_and_still_verifies():
    """Swift: toleratesUnknownHazardTypeAndStillVerifies."""
    alert = make_signed_alert(hazard_code=0x7F, severity=Severity.EMERGENCY_WARNING, headline="Unfamiliar hazard", action_text="")
    decoded = wire.decode(wire.encode_alert(alert))
    assert wire.verify(decoded, PUBLISHER_PUBLIC)
    assert decoded.hazard is None and decoded.hazard_code == 0x7F


def test_decode_cyclone_and_heatwave_round_trip():
    """Swift: cycloneAndHeatwaveRoundTrip."""
    for hazard in (HazardType.CYCLONE, HazardType.HEATWAVE):
        decoded = wire.decode(wire.encode_alert(make_signed_alert(hazard=hazard)))
        assert decoded.hazard is hazard and wire.verify(decoded, PUBLISHER_PUBLIC)


def test_decode_rejects_duplicate_severity_and_headline():
    """Swift: rejectsDuplicateSeverityTLV, rejectsDuplicateHeadlineTLV."""
    encoded = wire.encode_alert(make_signed_alert(severity=Severity.ADVICE))
    assert wire.decode(bytes([0x0A, 0x00, 0x01, 0x03]) + encoded) is None
    assert wire.decode(encoded + bytes([0x04, 0x00, 0x02, 0x41, 0x42])) is None


def test_decode_area_cells_remain_repeatable():
    """Swift: areaCellsRemainRepeatable."""
    assert wire.decode(wire.encode_alert(make_signed_alert(area_cells=("r7hg", "r7hu", "r7hs")))) is not None


def test_decode_tolerates_unknown_and_retired_tlvs():
    """Swift: toleratesUnknownTLVs, toleratesARetiredPublisherKeyTLV."""
    alert = make_signed_alert()
    encoded = wire.encode_alert(alert)
    assert wire.decode(encoded + bytes([0x7F, 0x00, 0x02, 0xDE, 0xAD])) == alert
    assert wire.decode(encoded + bytes([0x06, 0x00, 0x20]) + bytes([0xAB]) * 32) == alert


def test_decode_rejects_truncated_payload():
    """Swift: rejectsTruncatedPayload."""
    encoded = wire.encode_alert(make_signed_alert())
    assert wire.decode(encoded[:-1]) is None


def test_decode_severity_peek():
    """Swift: severityPeekMatchesDecodedSeverity, severityPeekReturnsNilOnGarbage."""
    for severity in Severity:
        assert wire.severity_peek(wire.encode_alert(make_signed_alert(severity=severity))) is severity
    assert wire.severity_peek(bytes([0x00, 0x01, 0x02])) is None
    assert wire.severity_peek(b"") is None


# --- Attacks (step 2.7). Each keeps the genuine signature and changes the content.


def _with(alert, **changes):
    fields = {f: getattr(alert, f) for f in alert.__dataclass_fields__}
    fields.update(changes)
    return wire.OfficialAlert(**fields)


def test_attack_tampered_headline_fails():
    """Swift: tamperedHeadlineFailsVerification."""
    alert = make_signed_alert()
    assert not wire.verify(_with(alert, headline="All clear, no action required"), PUBLISHER_PUBLIC)


def test_attack_downgraded_severity_fails():
    """Swift: tamperedSeverityFailsVerification. The highest-harm tamper."""
    alert = make_signed_alert(severity=Severity.EMERGENCY_WARNING)
    assert not wire.verify(_with(alert, severity=Severity.ADVICE), PUBLISHER_PUBLIC)


def test_attack_adding_an_area_cell_fails():
    """Swift: addingAnAreaCellFailsVerification. The cell count stops this."""
    alert = make_signed_alert(area_cells=("r7hg",))
    assert not wire.verify(_with(alert, area_cells=("r7hg", "r3gx")), PUBLISHER_PUBLIC)


def test_attack_moving_bytes_between_headline_and_action_fails():
    """Swift: movingBytesBetweenHeadlineAndActionFailsVerification. Length prefixes stop this."""
    alert = make_signed_alert(headline="Flood warning AB", action_text="CD leave now")
    shifted = _with(alert, headline="Flood warning A", action_text="BCD leave now")
    assert not wire.verify(shifted, PUBLISHER_PUBLIC)


def test_attack_changed_times_or_id_fail():
    alert = make_signed_alert()
    assert not wire.verify(_with(alert, expires_at=alert.expires_at + 1), PUBLISHER_PUBLIC)
    assert not wire.verify(_with(alert, issued_at=alert.issued_at + 1), PUBLISHER_PUBLIC)
    assert not wire.verify(_with(alert, alert_id=bytes(16)), PUBLISHER_PUBLIC)


def test_attack_genuine_alert_still_verifies():
    """Guards against a verify that fails for everything, which would make the tests above meaningless."""
    assert wire.verify(make_signed_alert(), PUBLISHER_PUBLIC)


# --- Cancellations (step 2.8)


def make_signed_cancellation(alert_id, issued_at=1_700_003_600_000, key=None):
    signature = (key or PUBLISHER).sign(wire.cancellation_signing_bytes(alert_id, issued_at))
    return wire.AlertCancellation(alert_id, issued_at, signature)


def test_cancellation_round_trip():
    """Swift: cancellationRoundTrip."""
    cancellation = make_signed_cancellation(make_signed_alert().alert_id)
    encoded = wire.encode(cancellation)
    decoded = wire.decode(encoded)
    assert decoded == cancellation
    assert wire.verify(decoded, PUBLISHER_PUBLIC)
    assert wire.severity_peek(encoded) is None  # carries no severity, gets no priority


def test_cancellation_signed_by_another_key_fails():
    """Swift: cancellationSignedByAnotherKeyFailsVerification."""
    forged = make_signed_cancellation(make_signed_alert().alert_id, key=Ed25519PrivateKey.generate())
    assert not wire.verify(wire.decode(wire.encode(forged)), PUBLISHER_PUBLIC)


def test_cancellation_retargeted_to_another_alert_fails():
    """Swift: cancellationRetargetedToAnotherAlertFailsVerification."""
    genuine = make_signed_cancellation(make_signed_alert().alert_id)
    retargeted = wire.AlertCancellation(make_signed_alert().alert_id, genuine.issued_at, genuine.signature)
    assert not wire.verify(retargeted, PUBLISHER_PUBLIC)


def test_cancellation_flipped_from_a_signed_alert_decodes_but_fails():
    """Swift: flippingASignedAlertIntoACancellationFailsVerification."""
    alert = make_signed_alert(severity=Severity.EMERGENCY_WARNING)
    encoded = bytearray(wire.encode(alert))
    offset = value_offset(0x01, encoded)
    assert encoded[offset] == 0x01
    encoded[offset] = 0x02
    decoded = wire.decode(bytes(encoded))
    assert isinstance(decoded, wire.AlertCancellation)
    assert decoded.alert_id == alert.alert_id
    assert not wire.verify(decoded, PUBLISHER_PUBLIC)


def test_cancellation_flipped_into_an_alert_fails_decode():
    """Swift: flippingACancellationIntoAnAlertFailsDecode."""
    encoded = bytearray(wire.encode(make_signed_cancellation(make_signed_alert().alert_id)))
    encoded[value_offset(0x01, encoded)] = 0x01
    assert wire.decode(bytes(encoded)) is None


def test_cancellation_rejects_missing_fields():
    """Swift: cancellationRejectsMissingFields."""
    encoded = wire.encode(make_signed_cancellation(make_signed_alert().alert_id))
    assert wire.decode(encoded[: -3 - wire.SIGNATURE_LENGTH]) is None


def test_cancellation_frozen_vector():
    """Swift: decodesTheFrozenCancellationVectorFromTheSigningScript.
    Spec: the first 37 bytes must match; the signature must verify."""
    data = bytes.fromhex(FROZEN_CANCELLATION_HEX)
    decoded = wire.decode(data)
    assert wire.verify_pinned(decoded)
    assert not wire.verify(decoded, PUBLISHER_PUBLIC)
    assert decoded.alert_id == bytes(range(16))
    assert decoded.issued_at == 1_700_003_600_000
    assert len(data) == 101

    dev_private = bytes.fromhex("9077bd3b4bf110ba5c9bc7375e7e771d11597918ffa4a9ddc7a2f089a291f8cc")
    ours = make_signed_cancellation(bytes(range(16)), key=Ed25519PrivateKey.from_private_bytes(dev_private))
    ours_encoded = wire.encode(ours)
    assert ours_encoded[:37] == data[:37]
    assert wire.verify_pinned(ours)
    assert wire.encode(wire.AlertCancellation(bytes(range(16)), 1_700_003_600_000, data[-64:])) == data
