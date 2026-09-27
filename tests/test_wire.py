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
