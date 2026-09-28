"""The internet link: warnings and calls for help over Nostr, as the iPhone app sends them.

Ported from: ../alert-mesh/AlertMesh/AlertMesh/Services/OfficialAlertBridge.swift
             (publish: the warning app's side)
         and ../alert-mesh/AlertMesh/App/AppRuntime.swift (which relays each side uses).

Everything sent this way goes to public relays that anyone can read. The apps turn the
link on only when asked (a switch), and the tests name their own relays
(ALERTMESH_NOSTR_RELAYS), so they never reach the real ones.

This is free and unencumbered software released into the public domain.
"""
import os
import threading

from alertmesh import georelays, nostr, wire


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
