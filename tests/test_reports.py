"""Tests for alertmesh.reports.

Swift reference: ../alert-mesh/AlertMeshTests/AlertMesh/Protocols/CommunityReportPacketsTests.swift.
Test docstrings name the Swift test they port, where one exists.
"""
from alertmesh import reports, wire
from alertmesh.reports import ReportKind, ReportSeverity


def test_constants_match_the_swift_app():
    assert reports.REPORT_ID_LENGTH == 16
    assert reports.SIGNING_KEY_LENGTH == 32
    assert reports.SIGNATURE_LENGTH == 64
    assert reports.NOTE_MAX_BYTES == 140
    assert reports.NICKNAME_MAX_BYTES == 32
    assert (reports.GEOHASH_MIN_LENGTH, reports.GEOHASH_MAX_LENGTH) == (2, 8)
    assert reports.SOS_GEOHASH_MAX_LENGTH == 7
    assert reports.HAZARD_MAX_LIFETIME_MS == 86_400_000
    assert reports.SOS_MAX_LIFETIME_MS == 21_600_000


def test_constants_wire_values_are_frozen():
    """Swift: wireValuesAreFrozen."""
    assert (ReportKind.HAZARD, ReportKind.SOS, ReportKind.SAFE) == (1, 2, 3)
    assert (ReportSeverity.LOW, ReportSeverity.MODERATE, ReportSeverity.HIGH) == (1, 2, 3)
    assert ReportSeverity.LOW < ReportSeverity.HIGH
    assert reports.MESSAGE_TYPE == 0x2E


def test_constants_signing_context_is_distinct():
    """Swift: signingContextIsFrozenAndDistinct (the constant part)."""
    assert reports.SIGNING_CONTEXT == "alertmesh-report-v1"
    assert reports.SIGNING_CONTEXT not in (wire.ALERT_SIGNING_CONTEXT, wire.CANCELLATION_SIGNING_CONTEXT)


def test_constants_report_severity_is_not_the_official_severity():
    assert ReportSeverity is not wire.Severity
    official_words = {s.name for s in wire.Severity}
    assert not official_words & {s.name for s in ReportSeverity}


SOS_FIELDS = dict(
    kind=ReportKind.SOS,
    report_id=bytes(range(16)),
    geohash="r7hg2bc",
    hazard_code=0,
    severity=None,
    note="Trapped on roof",
    author_signing_key=bytes(32),
    author_nickname="tim",
    created_at=1_700_000_000_000,
    expires_at=1_700_003_600_000,
)


def test_signing_bytes_start_with_context_then_kind():
    """Swift: signingContextIsFrozenAndDistinct. 0x13, "alertmesh-report-v1", then the kind."""
    hazard = reports.report_signing_bytes(**{**SOS_FIELDS, "kind": ReportKind.HAZARD})
    expected = bytes([0x13]) + b"alertmesh-report-v1" + bytes([0x01])
    assert hazard[: len(expected)] == expected


def test_signing_bytes_differ_by_kind_so_sos_cannot_become_safe():
    sos = reports.report_signing_bytes(**SOS_FIELDS)
    safe = reports.report_signing_bytes(**{**SOS_FIELDS, "kind": ReportKind.SAFE})
    assert sos != safe
    assert sos[20] == 0x02 and safe[20] == 0x03


def test_signing_bytes_layout_matches_the_spec():
    sb = reports.report_signing_bytes(**SOS_FIELDS)
    off = 21
    assert sb[off : off + 16] == bytes(range(16)); off += 16
    assert sb[off : off + 9] == b"\x00\x07r7hg2bc"; off += 9
    assert sb[off : off + 2] == b"\x00\x00"; off += 2  # no hazard, no severity
    assert sb[off : off + 17] == b"\x00\x0fTrapped on roof"; off += 17
    assert sb[off : off + 32] == bytes(32); off += 32
    assert sb[off : off + 5] == b"\x00\x03tim"; off += 5
    assert sb[off:] == (1_700_000_000_000).to_bytes(8, "big") + (1_700_003_600_000).to_bytes(8, "big")


def test_signing_bytes_severity_and_hazard_are_signed():
    base = {**SOS_FIELDS, "kind": ReportKind.HAZARD, "hazard_code": 1}
    low = reports.report_signing_bytes(**{**base, "severity": ReportSeverity.LOW})
    high = reports.report_signing_bytes(**{**base, "severity": ReportSeverity.HIGH})
    other_hazard = reports.report_signing_bytes(**{**base, "severity": ReportSeverity.LOW, "hazard_code": 2})
    assert low != high
    assert low != other_hazard


def test_signing_bytes_of_a_report_match_the_function():
    report = reports.CommunityReport(**SOS_FIELDS, signature=bytes(64))
    assert reports.signing_bytes_of(report) == reports.report_signing_bytes(**SOS_FIELDS)
    assert report.hazard is None
