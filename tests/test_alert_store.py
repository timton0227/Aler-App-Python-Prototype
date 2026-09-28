"""Tests for alertmesh.alert_store.

Swift reference: alert-mesh/AlertMeshTests/AlertMesh/Services/OfficialAlertStoreTests.swift.
"""
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from alertmesh import wire
from alertmesh.alert_store import (
    CLOCK_SKEW_MS, MAX_ALERTS, MAX_ORPHAN_CANCELLATIONS, AlertStore, IngestResult,
)
from alertmesh.wire import HazardType, OfficialAlert, Severity

PUBLISHER = Ed25519PrivateKey.generate()
BASE_MS = 1_700_000_000_000
HOUR_MS = 60 * 60 * 1000


class Clock:
    """Swift: MutableClock."""

    def __init__(self, now_ms=BASE_MS):
        self.now_ms = now_ms

    def __call__(self):
        return self.now_ms


def make_store(clock=None, publisher_key=None):
    return AlertStore(publisher_key or PUBLISHER.public_key().public_bytes_raw(), clock or Clock())


def make_alert(alert_id=None, severity=Severity.WATCH_AND_ACT, issued_at=BASE_MS, lifetime_ms=24 * HOUR_MS, key=None):
    """Swift: makeAlert. Built directly, so the store's own checks are tested, not the decoder's."""
    alert_id = alert_id or os.urandom(16)
    expires_at = issued_at + lifetime_ms
    args = (alert_id, HazardType.FLOOD, severity, ("r7hg",), "Flooding at Fitzroy Crossing",
            "Move to higher ground.", issued_at, expires_at)
    signature = (key or PUBLISHER).sign(wire.alert_signing_bytes(*args))
    return OfficialAlert(alert_id, int(HazardType.FLOOD), severity, ("r7hg",), args[4], args[5],
                         issued_at, expires_at, signature)


def make_cancellation(alert_id, issued_at, key=None):
    signature = (key or PUBLISHER).sign(wire.cancellation_signing_bytes(alert_id, issued_at))
    return wire.AlertCancellation(alert_id, issued_at, signature)


# --- Versions (step 5.1)


def test_versions_alert_signed_by_another_key_is_rejected_and_not_stored():
    """Swift: alertSignedByAnotherKeyIsRejectedAndNotStored."""
    store = make_store()
    forged = make_alert(severity=Severity.EMERGENCY_WARNING, key=Ed25519PrivateKey.generate())
    assert store.ingest(forged) is IngestResult.REJECTED
    assert store.live_alerts() == []
    assert store.sync_candidates() == []


def test_versions_store_without_a_publisher_key_accepts_nothing():
    """Swift: storeWithoutAPublisherKeyAcceptsNothing. Fail closed, never open."""
    store = AlertStore(publisher_key=None, clock=Clock())
    assert store.ingest(make_alert()) is IngestResult.REJECTED
    assert store.live_alerts() == []


def test_versions_ingest_stores_and_deduplicates():
    """Swift: ingestStoresAndDeduplicates, sameVersionFromDifferentPacketIsDuplicate."""
    store = make_store()
    alert = make_alert()
    assert store.ingest(alert) is IngestResult.ACCEPTED
    assert store.ingest(alert) is IngestResult.DUPLICATE
    assert store.ingest_payload(wire.encode(alert)) is IngestResult.DUPLICATE  # carried by another phone
    assert len(store.live_alerts()) == 1
    assert len(store.sync_candidates()) == 1


def test_versions_newer_version_of_same_event_replaces_stored_alert():
    """Swift: newerVersionOfSameEventReplacesStoredAlert."""
    clock = Clock()
    store = make_store(clock)
    alert_id = os.urandom(16)
    advice = make_alert(alert_id, Severity.ADVICE, BASE_MS)
    emergency = make_alert(alert_id, Severity.EMERGENCY_WARNING, BASE_MS + HOUR_MS)
    assert store.ingest(advice) is IngestResult.ACCEPTED
    clock.now_ms = BASE_MS + HOUR_MS
    assert store.ingest(emergency) is IngestResult.ACCEPTED
    alerts = store.live_alerts()
    assert len(alerts) == 1 and alerts[0].severity is Severity.EMERGENCY_WARNING
    assert store.sync_candidates() == [wire.encode(emergency)]


def test_versions_older_version_arriving_later_is_rejected():
    """Swift: olderVersionArrivingLaterIsRejected."""
    store = make_store(Clock(BASE_MS + HOUR_MS))
    alert_id = os.urandom(16)
    advice = make_alert(alert_id, Severity.ADVICE, BASE_MS)
    emergency = make_alert(alert_id, Severity.EMERGENCY_WARNING, BASE_MS + HOUR_MS)
    assert store.ingest(emergency) is IngestResult.ACCEPTED
    assert store.ingest(advice) is IngestResult.REJECTED
    assert store.live_alerts()[0].severity is Severity.EMERGENCY_WARNING


def test_versions_malformed_payload_is_rejected():
    assert make_store().ingest_payload(b"\x01\x00") is IngestResult.REJECTED


# --- Time rules (step 5.2)


def test_time_rejects_already_expired_alert():
    """Swift: rejectsAlreadyExpiredAlert."""
    store = make_store()
    assert store.ingest(make_alert(issued_at=BASE_MS - 2 * HOUR_MS, lifetime_ms=HOUR_MS)) is IngestResult.REJECTED
    assert store.live_alerts() == []


def test_time_rejects_alert_issued_beyond_clock_skew():
    """Swift: rejectsAlertIssuedBeyondClockSkew."""
    store = make_store()
    assert store.ingest(make_alert(issued_at=BASE_MS + CLOCK_SKEW_MS + 60_000)) is IngestResult.REJECTED
    assert store.live_alerts() == []


def test_time_accepts_alert_issued_within_clock_skew():
    """Swift: acceptsAlertIssuedWithinClockSkew."""
    store = make_store()
    assert store.ingest(make_alert(issued_at=BASE_MS + CLOCK_SKEW_MS - 60_000)) is IngestResult.ACCEPTED
    assert len(store.live_alerts()) == 1


def test_time_rejects_alert_expiring_too_far_in_the_future():
    """Swift: rejectsAlertExpiringTooFarInTheFuture. Built directly, bypassing the decoder's span check."""
    store = make_store()
    assert store.ingest(make_alert(lifetime_ms=30 * 24 * HOUR_MS)) is IngestResult.REJECTED
    assert store.live_alerts() == []


def test_time_expired_alerts_are_swept():
    """Swift: expiredAlertsAreSwept."""
    clock = Clock()
    store = make_store(clock)
    short = make_alert(lifetime_ms=HOUR_MS)
    long = make_alert(lifetime_ms=24 * HOUR_MS)
    store.ingest(short)
    store.ingest(long)
    assert len(store.live_alerts()) == 2
    clock.now_ms = BASE_MS + 2 * HOUR_MS
    remaining = store.live_alerts()
    assert [a.alert_id for a in remaining] == [long.alert_id]
    assert len(store.sync_candidates()) == 1


def test_time_clock_skew_is_one_hour():
    assert CLOCK_SKEW_MS == HOUR_MS


# --- Cancellations (step 5.3)


def test_cancel_signed_by_another_key_is_rejected():
    """Swift: cancellationSignedByAnotherKeyIsRejected."""
    store = make_store()
    alert = make_alert()
    store.ingest(alert)
    forged = make_cancellation(alert.alert_id, BASE_MS + 1000, key=Ed25519PrivateKey.generate())
    assert store.ingest(forged) is IngestResult.REJECTED
    assert len(store.live_alerts()) == 1


def test_cancel_removes_alert_and_propagates_until_original_expiry():
    """Swift: cancellationRemovesAlertAndPropagatesUntilOriginalExpiry."""
    clock = Clock()
    store = make_store(clock)
    alert = make_alert(lifetime_ms=24 * HOUR_MS)
    store.ingest(alert)
    assert store.ingest(make_cancellation(alert.alert_id, BASE_MS + 1000)) is IngestResult.ACCEPTED
    assert store.live_alerts() == []
    assert len(store.sync_candidates()) == 1  # the withdrawal still spreads
    assert store.ingest(alert) is IngestResult.REJECTED  # a replayed copy is refused
    clock.now_ms = BASE_MS + 25 * HOUR_MS
    assert store.sync_candidates() == []


def test_cancel_arriving_before_alert_suppresses_it():
    """Swift: cancellationArrivingBeforeAlertSuppressesIt."""
    store = make_store()
    alert = make_alert()
    assert store.ingest(make_cancellation(alert.alert_id, BASE_MS + 1000)) is IngestResult.ACCEPTED
    assert store.ingest(alert) is IngestResult.REJECTED
    assert store.live_alerts() == []


def test_cancel_reissue_after_cancellation_is_accepted_and_supersedes_it():
    """Swift: reissueAfterCancellationIsAcceptedAndSupersedesIt."""
    store = make_store()
    alert_id = os.urandom(16)
    store.ingest(make_alert(alert_id, issued_at=BASE_MS))
    store.ingest(make_cancellation(alert_id, BASE_MS + 1000))
    assert store.live_alerts() == []
    reissued = make_alert(alert_id, Severity.EMERGENCY_WARNING, BASE_MS + 2000)
    assert store.ingest(reissued) is IngestResult.ACCEPTED
    assert len(store.live_alerts()) == 1
    assert store.sync_candidates() == [wire.encode(reissued)]


def test_cancel_stale_cancellation_does_not_remove_newer_version():
    """Swift: staleCancellationDoesNotRemoveNewerVersion."""
    store = make_store()
    alert_id = os.urandom(16)
    store.ingest(make_alert(alert_id, issued_at=BASE_MS + 2000))
    assert store.ingest(make_cancellation(alert_id, BASE_MS + 1000)) is IngestResult.REJECTED
    assert len(store.live_alerts()) == 1


def test_cancel_duplicate_cancellation_is_duplicate():
    """Swift: duplicateCancellationIsDuplicate."""
    store = make_store()
    cancellation = make_cancellation(os.urandom(16), BASE_MS)
    assert store.ingest(cancellation) is IngestResult.ACCEPTED
    assert store.ingest(cancellation) is IngestResult.DUPLICATE
    assert len(store.sync_candidates()) == 1


def test_cancel_orphan_retention_is_bounded_by_receive_time():
    """Swift: orphanCancellationRetentionIsBoundedByReceiveTime."""
    clock = Clock()
    store = make_store(clock)
    assert store.ingest(make_cancellation(os.urandom(16), BASE_MS + CLOCK_SKEW_MS)) is IngestResult.ACCEPTED
    assert len(store.sync_candidates()) == 1
    clock.now_ms = BASE_MS + 8 * 24 * HOUR_MS
    assert store.sync_candidates() == []


def test_cancel_orphan_cap_evicts_oldest():
    """Swift: orphanCancellationCapEvictsOldest."""
    store = make_store()
    unseen = []
    for index in range(MAX_ORPHAN_CANCELLATIONS + 1):
        alert = make_alert(issued_at=BASE_MS + index)
        unseen.append(alert)
        assert store.ingest(make_cancellation(alert.alert_id, BASE_MS + 1000)) is IngestResult.ACCEPTED
    assert len(store.sync_candidates()) == MAX_ORPHAN_CANCELLATIONS
    assert store.ingest(unseen[0]) is IngestResult.ACCEPTED  # its orphan was evicted
    assert store.ingest(unseen[1]) is IngestResult.REJECTED  # the rest still suppress


def test_cancel_matched_cancellations_are_exempt_from_orphan_cap():
    """Swift: matchedCancellationsAreExemptFromOrphanCap."""
    store = make_store()
    cycles = MAX_ORPHAN_CANCELLATIONS + 2
    for index in range(cycles):
        alert = make_alert(issued_at=BASE_MS + index * 1000)
        assert store.ingest(alert) is IngestResult.ACCEPTED
        assert store.ingest(make_cancellation(alert.alert_id, BASE_MS + index * 1000 + 1)) is IngestResult.ACCEPTED
    assert store.live_alerts() == []
    assert len(store.sync_candidates()) == cycles


def test_cancel_issued_beyond_clock_skew_is_rejected():
    assert make_store().ingest(make_cancellation(os.urandom(16), BASE_MS + CLOCK_SKEW_MS + 1)) is IngestResult.REJECTED


# --- Cap, ordering, wipe (step 5.4)


def test_global_cap_evicts_oldest_issued():
    """Swift: globalCapEvictsOldestIssued."""
    store = make_store()
    oldest = None
    for index in range(MAX_ALERTS + 1):
        alert = make_alert(issued_at=BASE_MS + index * 1000)
        oldest = oldest or alert.alert_id
        assert store.ingest(alert) is IngestResult.ACCEPTED
    alerts = store.live_alerts()
    assert len(alerts) == MAX_ALERTS == 500
    assert oldest not in {a.alert_id for a in alerts}


def test_alerts_are_ordered_by_severity_then_recency():
    """Swift: alertsAreOrderedBySeverityThenRecency."""
    store = make_store()
    old_emergency = make_alert(severity=Severity.EMERGENCY_WARNING, issued_at=BASE_MS - 3000)
    advice = make_alert(severity=Severity.ADVICE, issued_at=BASE_MS - 1000)
    new_watch = make_alert(severity=Severity.WATCH_AND_ACT, issued_at=BASE_MS)
    old_watch = make_alert(severity=Severity.WATCH_AND_ACT, issued_at=BASE_MS - 2000)
    for alert in (advice, old_watch, new_watch, old_emergency):
        store.ingest(alert)
    expected = [old_emergency, new_watch, old_watch, advice]
    assert [a.alert_id for a in store.live_alerts()] == [a.alert_id for a in expected]


def test_wipe_clears_everything():
    """Swift: wipeClearsMemoryAndDisk (memory part)."""
    store = make_store()
    store.ingest(make_alert())
    store.ingest(make_cancellation(os.urandom(16), BASE_MS))
    store.wipe()
    assert store.live_alerts() == [] and store.sync_candidates() == []
