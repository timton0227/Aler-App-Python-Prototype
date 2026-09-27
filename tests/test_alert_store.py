"""Tests for alertmesh.alert_store.

Swift reference: ../alert-mesh/AlertMeshTests/AlertMesh/Services/OfficialAlertStoreTests.swift.
"""
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from alertmesh import wire
from alertmesh.alert_store import AlertStore, IngestResult
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
