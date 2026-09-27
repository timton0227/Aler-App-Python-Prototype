"""Tests for alertmesh.report_store.

Swift reference: ../alert-mesh/AlertMeshTests/AlertMesh/Services/CommunityReportStoreTests.swift.
"""
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from alertmesh import reports
from alertmesh.alert_store import CLOCK_SKEW_MS, IngestResult
from alertmesh.report_store import (
    MAX_CHECK_INS_PER_AUTHOR, MAX_HAZARD_REPORTS_PER_AUTHOR, MAX_REPORTS, ReportStore,
)
from alertmesh.reports import CommunityReport, ReportKind, ReportSeverity

AUTHOR = Ed25519PrivateKey.generate()
BASE_MS = 1_700_000_000_000
HOUR_MS = 60 * 60 * 1000


class Clock:
    def __init__(self, now_ms=BASE_MS):
        self.now_ms = now_ms

    def __call__(self):
        return self.now_ms


def make_report(kind=ReportKind.HAZARD, report_id=None, severity=ReportSeverity.MODERATE, created_at=BASE_MS,
                lifetime_ms=HOUR_MS, key=None, claim_key=None):
    """Swift: makeReport. Built directly, so the store's own checks are tested, not the decoder's."""
    signer = key or AUTHOR
    claimed = claim_key or signer.public_key().public_bytes_raw()
    report_id = report_id or os.urandom(16)
    hazard_code = 1 if kind == ReportKind.HAZARD else 0
    sev = severity if kind == ReportKind.HAZARD else None
    note = {ReportKind.HAZARD: "Causeway under water", ReportKind.SOS: "Trapped on roof"}.get(kind, "")
    args = (kind, report_id, "r7hg2bc", hazard_code, sev, note, claimed, "tim", created_at, created_at + lifetime_ms)
    return CommunityReport(*args, signer.sign(reports.report_signing_bytes(*args)))


def test_report_whose_signature_does_not_match_its_author_key_is_rejected():
    """Swift: reportWhoseSignatureDoesNotMatchItsAuthorKeyIsRejected."""
    store = ReportStore(Clock())
    forged = make_report(ReportKind.SOS, key=Ed25519PrivateKey.generate(), claim_key=AUTHOR.public_key().public_bytes_raw())
    assert store.ingest(forged) is IngestResult.REJECTED
    assert store.live_reports() == [] and store.sync_candidates() == []


def test_stranger_cannot_mark_author_safe():
    """Swift: strangerCannotMarkAuthorSafe. THE test for this store."""
    store = ReportStore(Clock())
    sos = make_report(ReportKind.SOS)
    assert store.ingest(sos) is IngestResult.ACCEPTED
    fake_safe = make_report(ReportKind.SAFE, sos.report_id, created_at=BASE_MS + 1000, key=Ed25519PrivateKey.generate())
    assert store.ingest(fake_safe) is IngestResult.ACCEPTED  # a separate record
    live = store.live_reports()
    assert len(live) == 2
    assert any(r.kind is ReportKind.SOS and r.author_signing_key == sos.author_signing_key for r in live)


def test_ingest_stores_and_deduplicates():
    """Swift: ingestStoresAndDeduplicates, sameReportCarriedByAnotherPeerIsDuplicate."""
    store = ReportStore(Clock())
    report = make_report()
    assert store.ingest(report) is IngestResult.ACCEPTED
    assert store.ingest(report) is IngestResult.DUPLICATE
    assert store.ingest_payload(reports.encode(report)) is IngestResult.DUPLICATE
    assert len(store.live_reports()) == 1 and len(store.sync_candidates()) == 1


def test_time_rules():
    """Swift: rejectsAlreadyExpiredReport, rejectsReportCreatedBeyondClockSkew,
    acceptsReportCreatedWithinClockSkew, rejectsSOSExpiringBeyondItsKindsLifetime."""
    store = ReportStore(Clock())
    assert store.ingest(make_report(created_at=BASE_MS - 2 * HOUR_MS, lifetime_ms=HOUR_MS)) is IngestResult.REJECTED
    assert store.ingest(make_report(created_at=BASE_MS + CLOCK_SKEW_MS + 60_000)) is IngestResult.REJECTED
    assert store.ingest(make_report(created_at=BASE_MS + CLOCK_SKEW_MS - 60_000)) is IngestResult.ACCEPTED
    assert store.ingest(make_report(ReportKind.SOS, lifetime_ms=20 * HOUR_MS)) is IngestResult.REJECTED


def test_safe_with_same_id_and_author_replaces_sos():
    """Swift: safeWithSameIDAndAuthorReplacesSOS."""
    store = ReportStore(Clock())
    sos = make_report(ReportKind.SOS)
    safe = make_report(ReportKind.SAFE, sos.report_id, created_at=BASE_MS + 60_000)
    assert store.ingest(sos) is IngestResult.ACCEPTED
    assert store.ingest(safe) is IngestResult.ACCEPTED
    live = store.live_reports()
    assert len(live) == 1 and live[0].kind is ReportKind.SAFE
    assert store.sync_candidates() == [reports.encode(safe)]  # the SOS no longer circulates


def test_stale_sos_arriving_after_safe_is_rejected():
    """Swift: staleSOSArrivingAfterSafeIsRejected."""
    store = ReportStore(Clock(BASE_MS + 120_000))
    sos = make_report(ReportKind.SOS)
    safe = make_report(ReportKind.SAFE, sos.report_id, created_at=BASE_MS + 60_000)
    assert store.ingest(safe) is IngestResult.ACCEPTED
    assert store.ingest(sos) is IngestResult.REJECTED
    assert store.live_reports()[0].kind is ReportKind.SAFE


def test_updated_hazard_report_replaces_older_version():
    """Swift: updatedHazardReportReplacesOlderVersion."""
    store = ReportStore(Clock())
    first = make_report(severity=ReportSeverity.LOW)
    worse = make_report(report_id=first.report_id, severity=ReportSeverity.HIGH, created_at=BASE_MS + 1000)
    store.ingest(first)
    assert store.ingest(worse) is IngestResult.ACCEPTED
    assert [r.severity for r in store.live_reports()] == [ReportSeverity.HIGH]


def test_five_hazard_reports_do_not_evict_the_authors_sos():
    """Swift: fiveHazardReportsDoNotEvictTheAuthorsSOS. The most important quota test."""
    store = ReportStore(Clock())
    sos = make_report(ReportKind.SOS)
    assert store.ingest(sos) is IngestResult.ACCEPTED
    for index in range(MAX_HAZARD_REPORTS_PER_AUTHOR):
        assert store.ingest(make_report(created_at=BASE_MS + 1000 + index * 1000)) is IngestResult.ACCEPTED
    live = store.live_reports()
    assert len(live) == MAX_HAZARD_REPORTS_PER_AUTHOR + 1
    assert any(r.kind is ReportKind.SOS and r.report_id == sos.report_id for r in live)


def test_hazard_quota_evicts_oldest_hazard_only():
    """Swift: hazardQuotaEvictsOldestHazardOnly."""
    store = ReportStore(Clock())
    ids = []
    for index in range(MAX_HAZARD_REPORTS_PER_AUTHOR + 1):
        report = make_report(created_at=BASE_MS + index * 1000)
        ids.append(report.report_id)
        assert store.ingest(report) is IngestResult.ACCEPTED
    live = store.live_reports()
    assert len(live) == MAX_HAZARD_REPORTS_PER_AUTHOR
    assert ids[0] not in {r.report_id for r in live}


def test_check_in_quota_is_separate_and_evicts_safe_before_sos():
    """Swift: checkInQuotaIsSeparateAndEvictsSafeBeforeSOS."""
    store = ReportStore(Clock())
    old_safe = make_report(ReportKind.SAFE, created_at=BASE_MS)
    sos = make_report(ReportKind.SOS, created_at=BASE_MS + 1000)
    new_safe = make_report(ReportKind.SAFE, created_at=BASE_MS + 2000)
    for report in (old_safe, sos, new_safe):
        assert store.ingest(report) is IngestResult.ACCEPTED
    live_ids = {r.report_id for r in store.live_reports()}
    assert len(live_ids) == MAX_CHECK_INS_PER_AUTHOR
    assert sos.report_id in live_ids and old_safe.report_id not in live_ids


def test_quotas_are_counted_per_author():
    """Swift: quotasAreCountedPerAuthor."""
    store = ReportStore(Clock())
    other = Ed25519PrivateKey.generate()
    for index in range(MAX_HAZARD_REPORTS_PER_AUTHOR):
        assert store.ingest(make_report(created_at=BASE_MS + index * 1000)) is IngestResult.ACCEPTED
        assert store.ingest(make_report(created_at=BASE_MS + index * 1000, key=other)) is IngestResult.ACCEPTED
    assert len(store.live_reports()) == 2 * MAX_HAZARD_REPORTS_PER_AUTHOR


def test_global_cap_evicts_hazard_reports_before_sos_calls():
    """Swift: globalCapEvictsHazardReportsBeforeSOSCalls."""
    store = ReportStore(Clock())
    assert store.ingest(make_report(ReportKind.SOS, key=Ed25519PrivateKey.generate())) is IngestResult.ACCEPTED
    for index in range(MAX_REPORTS):
        hazard = make_report(created_at=BASE_MS + 1000 + index, key=Ed25519PrivateKey.generate())
        assert store.ingest(hazard) is IngestResult.ACCEPTED
    live = store.live_reports()
    assert len(live) == MAX_REPORTS == 300
    assert any(r.kind is ReportKind.SOS for r in live)


def test_reports_are_ordered_sos_first_then_hazard_by_severity_then_safe():
    """Swift: reportsAreOrderedSOSFirstThenHazardBySeverityThenSafe."""
    store = ReportStore(Clock())
    a1, a2 = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    safe = make_report(ReportKind.SAFE, created_at=BASE_MS + 5000, key=a1)
    low = make_report(severity=ReportSeverity.LOW, created_at=BASE_MS + 4000, key=a1)
    high = make_report(severity=ReportSeverity.HIGH, created_at=BASE_MS + 1000, key=a2)
    sos = make_report(ReportKind.SOS, created_at=BASE_MS, key=a2)
    for report in (safe, low, high, sos):
        store.ingest(report)
    assert [r.report_id for r in store.live_reports()] == [r.report_id for r in (sos, high, low, safe)]


def test_expired_reports_are_swept():
    """Swift: expiredReportsAreSwept."""
    clock = Clock()
    store = ReportStore(clock)
    short = make_report(ReportKind.SOS, lifetime_ms=HOUR_MS)
    long = make_report(lifetime_ms=24 * HOUR_MS)
    store.ingest(short)
    store.ingest(long)
    assert len(store.live_reports()) == 2
    clock.now_ms = BASE_MS + 2 * HOUR_MS
    assert [r.report_id for r in store.live_reports()] == [long.report_id]
    assert len(store.sync_candidates()) == 1


def test_wipe_clears_everything():
    """Swift: wipeClearsMemoryAndDisk (memory part)."""
    store = ReportStore(Clock())
    store.ingest(make_report())
    store.wipe()
    assert store.live_reports() == [] and store.sync_candidates() == []


def test_author_signed_reports_flow_through_the_store():
    """ReportAuthor (step 3.4) and the store agree: SOS, then "I'm safe", leaves one record."""
    clock = Clock()
    store = ReportStore(clock)
    tim = reports.ReportAuthor("tim")
    assert store.ingest_payload(reports.encode(tim.sos("r7hg2bc", "help", BASE_MS))) is IngestResult.ACCEPTED
    assert store.ingest_payload(reports.encode(tim.safe(None, "", BASE_MS))) is IngestResult.ACCEPTED
    assert [r.kind for r in store.live_reports()] == [ReportKind.SAFE]
