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
