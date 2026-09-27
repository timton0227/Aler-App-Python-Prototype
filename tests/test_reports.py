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
