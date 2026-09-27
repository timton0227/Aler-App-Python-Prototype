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
from alertmesh.wire import OfficialAlert


class IngestResult(Enum):
    ACCEPTED = "accepted"    # new: keep it and pass it on
    DUPLICATE = "duplicate"  # already held: nothing to do
    REJECTED = "rejected"    # forged, stale or out of range: never pass it on


def _system_clock_ms() -> int:
    return int(time.time() * 1000)


# How far ahead of this phone's clock a sender's clock may be (1 hour).
CLOCK_SKEW_MS = 60 * 60 * 1000


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

    # --- Ingest ---

    def ingest(self, item) -> IngestResult:
        """Take a decoded warning. Verifies the signature first."""
        if self.publisher_key is None or not wire.verify(item, self.publisher_key):
            return IngestResult.REJECTED
        if isinstance(item, OfficialAlert):
            return self._ingest_alert(item, wire.encode(item))
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

    # --- Reads ---

    def live_alerts(self) -> list[OfficialAlert]:
        """Most severe first, then most recently issued: the order someone glancing
        at a screen in an evacuation centre needs."""
        self._prune(self.clock())
        alerts = [a for a, _ in self._alerts.values()]
        return sorted(alerts, key=lambda a: (-int(a.severity), -a.issued_at))

    def sync_candidates(self) -> list[bytes]:
        """Wire payloads this phone offers to other phones."""
        self._prune(self.clock())
        return [payload for _, payload in self._alerts.values()]

    # --- Internals ---

    def _prune(self, now: int) -> None:
        self._alerts = {k: v for k, v in self._alerts.items() if v[0].expires_at > now}
