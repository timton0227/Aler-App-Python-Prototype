"""The internet link: warnings and calls for help over Nostr, as the iPhone app sends them.

Ported from: alert-mesh/AlertMesh/AlertMesh/Services/OfficialAlertBridge.swift
             (publish: the warning app's side; refreshSubscription and receive: the
             phone app's side), CommunityReportBridge.swift (the phone app's calls for
             help, both ways)
         and alert-mesh/AlertMesh/App/AppRuntime.swift (which relays each side uses).

Everything sent this way goes to public relays that anyone can read. The apps turn the
link on only when asked (a switch), and the tests name their own relays
(ALERTMESH_NOSTR_RELAYS), so they never reach the real ones.

This is free and unencumbered software released into the public domain.
"""
import os
import threading

from alertmesh import georelays, geohash, nostr, reports, wire
from alertmesh.reports import SOS_MAX_LIFETIME_MS


class RelayChoice:
    """Which relays to use, as the iPhone app picks them:
    - a warning goes to the built-in relays and the geo relays of each area cell;
    - a call for help goes to the geo relays of its 4-character cell.
    With ALERTMESH_NOSTR_RELAYS set, only those relays are used, for everything."""

    def __init__(self, built_in, directory: georelays.Directory | None):
        self.built_in = list(built_in)
        self.directory = directory

    @classmethod
    def from_environment(cls) -> "RelayChoice":
        if os.environ.get(nostr.RELAYS_VARIABLE) is not None:
            return cls(nostr.relay_urls(), None)
        return cls(nostr.BUILT_IN_RELAYS, georelays.Directory())

    def geo(self, cell: str) -> list[str]:
        """The relays nearest a cell of at most 4 characters."""
        if self.directory is None:
            return list(self.built_in)
        return self.directory.relays_for(cell[:nostr.MAX_TAG_PRECISION].lower())

    def for_warning(self, area) -> list[str]:
        relays = set()
        for cell in area:
            if len(cell) >= nostr.MIN_TAG_PRECISION:
                relays.update(self.built_in)
                relays.update(self.geo(cell))
        return sorted(relays)

    def refresh(self) -> None:
        """Download a newer relay list when one is due (at most daily)."""
        if self.directory is not None:
            self.directory.refresh_if_due()


class WarningSender:
    """The warning app's side of the link. `send(payload)` takes the same signed bytes
    as the local network sender and publishes them while `enabled`.

    A cancellation carries no area, so the sender keeps each warning's area and expiry
    to tag its cancellation with (the Swift console passes them in)."""

    def __init__(self, pool, choice: RelayChoice):
        self.pool = pool
        self.choice = choice
        self.enabled = False
        self.last_event: nostr.Event | None = None
        self.last_relays: list[str] = []
        self._areas: dict[bytes, tuple[tuple[str, ...], int]] = {}  # alert id -> (area, expires_at)
        self._lock = threading.Lock()

    def send(self, payload: bytes) -> bool:
        """Publish a warning or cancellation. False when off, or when nothing is known
        of the warning a cancellation ends, or when there is no relay."""
        item = wire.decode(payload)
        if item is None:
            return False
        with self._lock:
            if isinstance(item, wire.OfficialAlert):
                self._areas[item.alert_id] = (tuple(item.area_cells), item.expires_at)
            known = self._areas.get(item.alert_id)
        if not self.enabled or known is None:
            return False
        area, expires_at = known
        relays = self.choice.for_warning(area)
        if not relays:
            return False
        event = nostr.alert_event(payload, area, expires_at)
        self.pool.publish(event, relays)
        with self._lock:
            self.last_event, self.last_relays = event, relays
        return True

    def status(self) -> tuple[int, int] | None:
        """(relays that took the last warning, relays it went to), or None before any."""
        with self._lock:
            event, relays = self.last_event, self.last_relays
        if event is None:
            return None
        results = self.pool.results(event.id)
        return sum(1 for accepted, _ in results.values() if accepted), len(relays)


class PhoneLink:
    """The phone app's side of the link, while `enabled`:

    - every warning, wherever it is, from the built-in relays and the geo relays around
      this phone's town; each is checked against the development key, then taken by the
      node, which passes it on over Bluetooth (OfficialAlertBridge.receive);
    - calls for help and "I'm safe" in the 4-character cells around the town, from the
      geo relays of those cells, taken and passed on the same way;
    - every call for help or "I'm safe" the node takes, this phone's own or one heard
      over Bluetooth, put online once, on the geo relays of its cell. So the first
      laptop with internet along the way puts it online for people who have none
      (CommunityReportBridge.publishIfNew).

    Nothing is sent back to where it came from: a version handed on is remembered.
    `node` needs `take_official`, `take_report`, `reports.live_reports()` and `_lock`."""

    ALERTS = "alertmesh-official-alerts"
    REPORTS = "alertmesh-community-reports"

    def __init__(self, pool, choice: RelayChoice, node, places, clock):
        self.pool = pool
        self.choice = choice
        self.node = node
        self.places = places  # () -> this phone's place cells (geohashes)
        self.clock = clock  # milliseconds since 1970
        self.enabled = False
        self._seen_alerts: set[str] = set()
        self._seen_reports: set[str] = set()
        self._lock = threading.Lock()

    # --- On and off ---

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        if not on:
            self.pool.unsubscribe(self.ALERTS)
            self.pool.unsubscribe(self.REPORTS)
            return
        self.refresh()
        with self.node._lock:
            live = self.node.reports.live_reports()
        for report in live:  # CommunityReportBridge.publishPending
            self._publish_report(report)
        threading.Thread(target=self._update_relay_list, name="relay-list", daemon=True).start()

    def _update_relay_list(self) -> None:
        self.choice.refresh()
        if self.enabled:
            self.refresh()  # the nearest relays may have changed

    def refresh(self) -> None:
        """Subscribe for this phone's place. Call when the town changes."""
        if not self.enabled:
            return
        now_s = self.clock() // 1000
        places = [p for p in self.places() if p]

        alert_relays = set(self.choice.built_in)
        for place in places:
            if len(place) >= nostr.MAX_TAG_PRECISION:
                cell = place[:nostr.MAX_TAG_PRECISION].lower()
                for nearby in [cell, *geohash.neighbors(cell)]:
                    alert_relays.update(self.choice.geo(nearby))
        since = now_s - wire.MAX_LIFETIME_MS // 1000
        self.pool.subscribe(self.ALERTS, nostr.official_alerts_filter(since), sorted(alert_relays), self.take_alert)

        cells = nostr.report_cells(places)
        report_relays = sorted({url for cell in cells for url in self.choice.geo(cell)})
        if not cells or not report_relays:
            self.pool.unsubscribe(self.REPORTS)
            return
        since = now_s - SOS_MAX_LIFETIME_MS // 1000
        self.pool.subscribe(self.REPORTS, nostr.community_reports_filter(cells, since), report_relays,
                            self.take_report)

    # --- In ---

    def take_alert(self, event: nostr.Event) -> None:
        payload = nostr.payload_of(event, nostr.KIND_OFFICIAL_ALERT)
        item = wire.decode(payload) if payload else None
        # Checked before it is marked seen: a forged copy must not block the genuine one.
        if item is None or not wire.verify_pinned(item):
            return
        key = nostr.alert_version_key(item)
        with self._lock:
            if key in self._seen_alerts:
                return
            self._seen_alerts.add(key)
        self.node.take_official(payload)

    def take_report(self, event: nostr.Event) -> None:
        payload = nostr.payload_of(event, nostr.KIND_COMMUNITY_REPORT)
        report = reports.decode(payload) if payload else None
        if report is None or not nostr.is_bridged(report.kind):
            return
        key = nostr.report_version_key(report)
        with self._lock:
            if key in self._seen_reports:
                return
            # Marked before the node takes it: its arrival must not publish it straight back.
            self._seen_reports.add(key)
        self.node.take_report(payload)

    # --- Out ---

    def report_arrived(self, payload: bytes) -> None:
        """The node took a report (the node's `on_report`)."""
        report = reports.decode(payload)
        if report is not None:
            self._publish_report(report)

    def _publish_report(self, report: reports.CommunityReport) -> None:
        if not self.enabled or not nostr.is_bridged(report.kind):
            return
        key = nostr.report_version_key(report)
        relays = self.choice.geo(nostr.report_cell(report.geohash))
        with self._lock:
            # No relay yet: left unseen, so it goes out when the link is next switched on.
            if key in self._seen_reports or not relays:
                return
            self._seen_reports.add(key)
        self.pool.publish(nostr.report_event(report), relays)
