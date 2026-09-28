"""The warning console: the operator plays the Bureau or a government agency.

Ported from:
- alert-mesh/AlertMesh/AlertMesh/Services/OfficialAlertIssuer.swift (issue, update,
  resend, cancel, and the outcome line)
- alert-mesh/AlertMesh/AlertMesh/Views/WarningAreaMapView.swift (WarningAreaPicker:
  sizes, toggle, corners)
- alert-mesh/AlertMesh/AlertMesh/Views/IssueWarningView.swift (English strings)

Like the Swift issuer, the console does not know about Bluetooth or the internet
itself: it is handed a `broadcast` function and a `publish` function. The Streamlit
page wires those to the simulated mesh; the tests wire them to a recorder. It can also
be handed a `share` function, which the warning app wires to real phone apps on the
local network (`NetworkShare`).

This is free and unencumbered software released into the public domain.
"""
import time
from dataclasses import dataclass
from enum import Enum, IntEnum

from alertmesh import geohash, wire
from alertmesh.signer import (
    DURATION_RANGE, HOUR_MS, OfficialAlertSigner, Problem, WarningDraft, new_alert_id, next_issued_at,
)
from alertmesh.wire import AlertCancellation, OfficialAlert

# --- Picking the area ---------------------------------------------------------


class AreaSize(IntEnum):
    """How big each picked cell is: the geohash length (WarningAreaPicker.Size)."""

    REGION = 3    # ~150 km
    DISTRICT = 4  # ~40 km
    TOWN = 5      # ~5 km
    STREET = 6    # ~1 km


AREA_SIZE_NAMES = {
    AreaSize.REGION: "Region (~150 km)",
    AreaSize.DISTRICT: "District (~40 km)",
    AreaSize.TOWN: "Town (~5 km)",
    AreaSize.STREET: "Suburb (~1 km)",
}

# A spot is located at the finest area precision before it is sized.
CLICK_PRECISION = wire.AREA_GEOHASH_MAX_LENGTH


def toggle_area(latitude: float, longitude: float, size: AreaSize, cells: list[str]) -> list[str]:
    """Pick or un-pick the area around a spot.

    A spot inside a picked cell removes that cell. A spot elsewhere adds the cell of
    `size` around it, replacing any smaller picked cells inside it so the area never
    lists the same ground twice, unless that would pass the 4-cell limit.
    """
    point = geohash.encode(latitude, longitude, CLICK_PRECISION)
    for i, cell in enumerate(cells):
        if point.startswith(cell):
            return cells[:i] + cells[i + 1:]
    cell = point[: int(size)]
    kept = [c for c in cells if not c.startswith(cell)]
    if len(kept) >= wire.MAX_AREA_CELLS:
        return cells
    return kept + [cell]


def corners(cell: str) -> list[tuple[float, float]]:
    """The four corners of a cell as (lat, lon), for drawing it."""
    lat_min, lat_max, lon_min, lon_max = geohash.decode_bounds(cell)
    return [(lat_min, lon_min), (lat_max, lon_min), (lat_max, lon_max), (lat_min, lon_max)]


# --- Sending ------------------------------------------------------------------


class Action(Enum):
    ISSUED = "issued"
    UPDATED = "updated"
    RESENT = "resent"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Outcome:
    """What the last send did, for the line under the Send button."""

    action: Action
    headline: str
    nearby_devices: int
    posted_online: bool
    # Sent to real phone apps on the local network: True, False (it failed), or None
    # when the console has no network share.
    shared: bool | None = None


class IssueError(Exception):
    """The draft has a problem, so nothing was signed or sent (IssueError.invalidDraft).
    The Swift `noKey` and `signingFailed` cases cannot happen here: the prototype always
    signs with the development key."""


class Console:
    """Signs warnings and sends each one both ways: over Bluetooth to nearby devices,
    and to the internet.

    - `broadcast(payload)`: hand the signed bytes to the mesh.
    - `publish(payload, area, expires_at) -> bool`: post them online; False when
      there is no internet (the warning still went out over Bluetooth).
    - `connected_peer_count()`: devices in Bluetooth range, for the outcome line.
    - `now_ms()`: the clock that stamps each version.
    - `share(item) -> bool`: optional; also send the warning or cancellation to real
      phone apps (see `NetworkShare`).
    """

    def __init__(self, broadcast, publish, connected_peer_count, now_ms,
                 signer: OfficialAlertSigner | None = None, make_alert_id=new_alert_id, share=None):
        self._broadcast = broadcast
        self._share = share
        self._publish = publish
        self._connected_peer_count = connected_peer_count
        self._now_ms = now_ms
        self._signer = signer or OfficialAlertSigner()
        self._make_alert_id = make_alert_id
        self.last_outcome: Outcome | None = None

    def issue(self, draft: WarningDraft) -> OfficialAlert:
        """A new warning: a new event ID, version = now."""
        alert = self._sign(draft, self._make_alert_id(), None)
        self._send(alert, alert.area_cells, alert.expires_at, Action.ISSUED, alert.headline)
        return alert

    def update(self, alert: OfficialAlert, draft: WarningDraft) -> OfficialAlert:
        """The same event with a later version, so phones replace the warning rather
        than show two, even within the same millisecond."""
        updated = self._sign(draft, alert.alert_id, alert.issued_at)
        self._send(updated, updated.area_cells, updated.expires_at, Action.UPDATED, updated.headline)
        return updated

    def resend(self, alert: OfficialAlert) -> None:
        """The same signed bytes again, for devices that missed it."""
        self._send(alert, alert.area_cells, alert.expires_at, Action.RESENT, alert.headline)

    def cancel(self, alert: OfficialAlert) -> AlertCancellation:
        """Withdraw the warning everywhere. The cancellation carries the warning's area
        and end time, so it goes online to the same places."""
        cancellation = self._signer.cancel(alert.alert_id, next_issued_at(self._now_ms(), alert.issued_at))
        self._send(cancellation, alert.area_cells, alert.expires_at, Action.CANCELLED, alert.headline)
        return cancellation

    def _sign(self, draft: WarningDraft, alert_id: bytes, previous: int | None) -> OfficialAlert:
        if draft.problems:
            raise IssueError(draft.problems)
        alert = self._signer.sign(draft, alert_id, next_issued_at(self._now_ms(), previous))
        if alert is None:
            raise IssueError(draft.problems)
        return alert

    def _send(self, item, area, expires_at: int, action: Action, headline: str) -> None:
        # Counted before sending, as in Swift: the devices connected when it went out.
        nearby = self._connected_peer_count()
        payload = wire.encode(item)
        self._broadcast(payload)
        online = self._publish(payload, tuple(area), expires_at)
        shared = self._share(item) if self._share else None
        self.last_outcome = Outcome(action, headline, nearby, online, shared)


def _real_clock_ms() -> int:
    return int(time.time() * 1000)


class NetworkShare:
    """Sends each console action to real phone apps too (the warning app's Wi-Fi link).

    The simulated town keeps its own clock, which only moves when the operator lets
    time pass, and it starts in 2023. Real phone apps check warnings against the real
    clock, so each warning is signed again for them with the real time: the same event
    ID, words, area and length. An update gets a later version, a cancellation cancels
    the real copy, and "send again" repeats the same real bytes.

    `send(payload) -> bool` puts the signed bytes on the network (`lan.Broadcaster.send`).
    """

    def __init__(self, send, now_ms=_real_clock_ms, signer: OfficialAlertSigner | None = None):
        self._send = send
        self._now_ms = now_ms
        self._signer = signer or OfficialAlertSigner()
        self._real: dict[bytes, OfficialAlert] = {}  # event ID -> the real copy last sent
        self._simulated_version: dict[bytes, int] = {}  # event ID -> the town's version it copies

    def __call__(self, item) -> bool:
        if isinstance(item, AlertCancellation):
            real = self._real.pop(item.alert_id, None)
            self._simulated_version.pop(item.alert_id, None)
            return real is not None and self._cancel(real)
        held = self._real.get(item.alert_id)
        if held is not None and self._simulated_version.get(item.alert_id) == item.issued_at:
            return self._send(wire.encode(held))  # the same version again
        hours = round((item.expires_at - item.issued_at) / HOUR_MS)
        draft = WarningDraft(wire.HazardType(item.hazard_code), item.severity, item.headline, item.action_text,
                             min(max(hours, DURATION_RANGE.start), DURATION_RANGE.stop - 1), list(item.area_cells))
        real = self._signer.sign(draft, item.alert_id,
                                 next_issued_at(self._now_ms(), held.issued_at if held else None))
        self._real[item.alert_id] = real
        self._simulated_version[item.alert_id] = item.issued_at
        return self._send(wire.encode(real))

    def withdraw_all(self) -> None:
        """Cancel every real copy still out: the town they belonged to is gone."""
        for real in self._real.values():
            self._cancel(real)
        self._real.clear()
        self._simulated_version.clear()

    def _cancel(self, real: OfficialAlert) -> bool:
        cancellation = self._signer.cancel(real.alert_id, next_issued_at(self._now_ms(), real.issued_at))
        return self._send(wire.encode(cancellation))


# --- Words (IssueWarningView.Strings, English) --------------------------------

PROBLEM_TEXT = {
    Problem.NO_HEADLINE: "Write a headline.",
    Problem.NO_ACTION: "Say what people should do.",
    Problem.HEADLINE_TOO_LONG: "Shorten the headline.",
    Problem.ACTION_TOO_LONG: "Shorten what to do.",
    # Swift: "Pick an area on the map." The page picks areas from a list of places.
    Problem.NO_AREA: "Pick an area.",
    Problem.TOO_MANY_CELLS: "Pick at most 4 areas.",
    Problem.DURATION_OUT_OF_RANGE: "A warning lasts 1 hour to 7 days.",
}

_ACTION_TEXT = {
    Action.ISSUED: "Sent",
    Action.UPDATED: "Update sent",
    Action.RESENT: "Sent again",
    Action.CANCELLED: "Cancellation sent",
}


def outcome_text(outcome: Outcome) -> str:
    """ "Sent: <headline> — 3 devices connected over Bluetooth, handed to internet relays"."""
    # Swift always says "devices"; one device reads better as "device".
    devices = "device" if outcome.nearby_devices == 1 else "devices"
    nearby = f"{outcome.nearby_devices} {devices} connected over Bluetooth"
    online = "handed to internet relays" if outcome.posted_online else "not online: no relay"
    text = f"{_ACTION_TEXT[outcome.action]}: {outcome.headline} — {nearby}, {online}"
    if outcome.shared is not None:
        text += (", sent to phone apps on the local network" if outcome.shared
                 else ", not sent to the local network")
    return text
