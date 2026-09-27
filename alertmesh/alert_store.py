"""What one phone keeps: the newest verified version of each official warning.

Ported from: ../alert-mesh/AlertMesh/AlertMesh/Services/OfficialAlertStore.swift

`alert_id` names the EVENT and `issued_at` is the VERSION. The store keeps one
version per event: a newer one replaces it, the same one is a duplicate, and an
older one is refused. Every warning is checked against the publisher key before it
is kept, and only what the store accepts may be passed on to other phones.

This is free and unencumbered software released into the public domain.
"""
import time
from enum import Enum

from alertmesh import wire
from alertmesh.wire import AlertCancellation, OfficialAlert


class IngestResult(Enum):
    ACCEPTED = "accepted"    # new: keep it and pass it on
    DUPLICATE = "duplicate"  # already held: nothing to do
    REJECTED = "rejected"    # forged, stale or out of range: never pass it on


def _system_clock_ms() -> int:
    return int(time.time() * 1000)


# How far ahead of this phone's clock a sender's clock may be (1 hour).
CLOCK_SKEW_MS = 60 * 60 * 1000
# A cancellation whose warning this phone never saw ("orphan") is kept at most as
# long as any warning could live, and at most this many are kept.
ORPHAN_CANCELLATION_LIFETIME_MS = wire.MAX_LIFETIME_MS
MAX_ORPHAN_CANCELLATIONS = 100


class AlertStore:
    """One phone's official warnings.

    `clock` returns "now" in milliseconds. The simulation passes its own clock.
    """

    def __init__(self, publisher_key: bytes | None = wire.PINNED_PUBLIC_KEY, clock=_system_clock_ms):
        # None means nothing verifies and the store stays empty: a build with no
        # key shows no warnings rather than unverified ones.
        self.publisher_key = publisher_key
        self.clock = clock
        self._alerts: dict[bytes, tuple[OfficialAlert, bytes]] = {}  # alert_id -> (alert, payload)
        # alert_id -> (cancellation, payload, retain_until, is_orphan), oldest first
        self._cancellations: dict[bytes, tuple[AlertCancellation, bytes, int, bool]] = {}

    # --- Ingest ---

    def ingest(self, item) -> IngestResult:
        """Take a decoded warning. Verifies the signature first."""
        if self.publisher_key is None or not wire.verify(item, self.publisher_key):
            return IngestResult.REJECTED
        if isinstance(item, OfficialAlert):
            return self._ingest_alert(item, wire.encode(item))
        if isinstance(item, AlertCancellation):
            return self._ingest_cancellation(item, wire.encode(item))
        return IngestResult.REJECTED

    def ingest_payload(self, payload: bytes) -> IngestResult:
        """Decode wire bytes, then ingest. Malformed bytes are rejected."""
        item = wire.decode(payload)
        return IngestResult.REJECTED if item is None else self.ingest(item)

    def _ingest_alert(self, alert: OfficialAlert, payload: bytes) -> IngestResult:
        now = self.clock()
        self._prune(now)
        if alert.expires_at <= now:
            return IngestResult.REJECTED
        # Receive-time sanity. A forged far-future issued_at would otherwise be "the
        # newest version" of its event forever and sort to the top of every list.
        if alert.issued_at > now + CLOCK_SKEW_MS or alert.expires_at > now + wire.MAX_LIFETIME_MS + CLOCK_SKEW_MS:
            return IngestResult.REJECTED
        cancelled = self._cancellations.get(alert.alert_id)
        if cancelled is not None:
            # Cancelled at or after this version was issued: stays cancelled.
            # Issued after the cancellation: the warning was reinstated, and the
            # new version replaces the withdrawal.
            if alert.issued_at <= cancelled[0].issued_at:
                return IngestResult.REJECTED
            del self._cancellations[alert.alert_id]
        held = self._alerts.get(alert.alert_id)
        if held is not None:
            stored = held[0]
            if alert.issued_at == stored.issued_at:
                return IngestResult.DUPLICATE
            # A stale version arriving after a newer one (a phone that missed the
            # escalation) is not worth passing on; the newer one will spread.
            if alert.issued_at < stored.issued_at:
                return IngestResult.REJECTED
        self._alerts[alert.alert_id] = (alert, payload)
        return IngestResult.ACCEPTED

    def _ingest_cancellation(self, cancellation: AlertCancellation, payload: bytes) -> IngestResult:
        now = self.clock()
        self._prune(now)
        if cancellation.issued_at > now + CLOCK_SKEW_MS:
            return IngestResult.REJECTED
        existing = self._cancellations.get(cancellation.alert_id)
        if existing is not None and existing[0].issued_at >= cancellation.issued_at:
            return IngestResult.DUPLICATE
        # Capped by both the claimed issue time and the receive time, so a far-future
        # stamp cannot keep a cancellation longer than any real warning could live.
        max_retain = min(
            cancellation.issued_at + ORPHAN_CANCELLATION_LIFETIME_MS,
            now + ORPHAN_CANCELLATION_LIFETIME_MS + CLOCK_SKEW_MS,
        )
        held = self._alerts.get(cancellation.alert_id)
        if held is not None:
            target = held[0]
            # Older than the version held: a reissue already overtook it.
            # Withdrawing the newer warning on its strength would silence a live one.
            if cancellation.issued_at < target.issued_at:
                return IngestResult.REJECTED
            # Kept until the warning's own expiry, so the withdrawal keeps
            # outrunning stale copies still travelling on the mesh.
            retain_until, is_orphan = target.expires_at, False
            del self._alerts[cancellation.alert_id]
        else:
            # Warning not seen yet (the cancellation raced ahead). Keep it, so the
            # warning is suppressed if it arrives later.
            retain_until, is_orphan = max_retain, True
        if retain_until <= now:
            return IngestResult.REJECTED

        self._cancellations.pop(cancellation.alert_id, None)
        self._cancellations[cancellation.alert_id] = (cancellation, payload, retain_until, is_orphan)
        if is_orphan:
            orphans = [k for k, v in self._cancellations.items() if v[3]]
            for k in orphans[: max(0, len(orphans) - MAX_ORPHAN_CANCELLATIONS)]:
                del self._cancellations[k]
        return IngestResult.ACCEPTED

    # --- Reads ---

    def live_alerts(self) -> list[OfficialAlert]:
        """Most severe first, then most recently issued: the order someone glancing
        at a screen in an evacuation centre needs."""
        self._prune(self.clock())
        alerts = [a for a, _ in self._alerts.values()]
        return sorted(alerts, key=lambda a: (-int(a.severity), -a.issued_at))

    def sync_candidates(self) -> list[bytes]:
        """Wire payloads this phone offers to other phones: live warnings, then
        live cancellations (so a withdrawal keeps spreading)."""
        self._prune(self.clock())
        return [p for _, p in self._alerts.values()] + [c[1] for c in self._cancellations.values()]

    # --- Internals ---

    def _prune(self, now: int) -> None:
        self._alerts = {k: v for k, v in self._alerts.items() if v[0].expires_at > now}
        self._cancellations = {k: v for k, v in self._cancellations.items() if v[2] > now}
