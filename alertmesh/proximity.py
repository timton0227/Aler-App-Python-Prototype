"""The loud-or-quiet rule: how close is this phone to a warning, and how loud should it be?

Ported from: ../alert-mesh/AlertMesh/AlertMesh/Services/AlertProximity.swift

Uses area codes (geohashes) only, never raw coordinates, like the app. A place is
INSIDE a warning when its code starts with one of the warning's cells, and ADJACENT
when it sits in a neighbouring cell (only for cells of 5 characters or more).

This is free and unencumbered software released into the public domain.
"""
from dataclasses import dataclass
from enum import Enum, IntEnum

from alertmesh import geohash
from alertmesh.wire import Severity


class Match(IntEnum):
    """How close a place is to a warning area. Ordered weakest to strongest, so the
    strongest of several matches is `max`."""

    ELSEWHERE = 0
    # Borders the area, or the place is coarser than the warning and contains it:
    # close enough to know about, not close enough to be sure.
    ADJACENT = 1
    INSIDE = 2


# Below this length a cell is 20 km or more across, and its ring of neighbours covers
# thousands of square kilometres: "adjacent" there is noise, not proximity.
MINIMUM_PRECISION_FOR_ADJACENCY = 5


def _match_one(place: str, cell: str) -> Match:
    if not place or not cell:
        return Match.ELSEWHERE
    if place.startswith(cell):
        return Match.INSIDE
    # The place is coarser than the warning and contains it. The person may well be
    # inside, but a 3-character place is ~150 km across, so this is only ever "near".
    if cell.startswith(place):
        return Match.ADJACENT
    if len(cell) < MINIMUM_PRECISION_FOR_ADJACENCY or len(place) < len(cell):
        return Match.ELSEWHERE
    return Match.ADJACENT if place[: len(cell)] in geohash.neighbors(cell) else Match.ELSEWHERE


def match(place: str, area_cells) -> tuple[Match, str | None]:
    """The strongest match between one place and a warning's cells, and the cell that gave it."""
    best, best_cell = Match.ELSEWHERE, None
    for cell in area_cells:
        m = _match_one(place, cell)
        if m > best:
            best, best_cell = m, cell
            if m == Match.INSIDE:
                break
    return best, best_cell


# --- The decision -------------------------------------------------------------


class Urgency(IntEnum):
    """What the phone should do about a warning, right now."""

    # No notification. Only the starting point: since "warn everyone" (Swift Task
    # 8.38) the rule never returns it; every warning is at least quiet.
    SILENT = 0
    # A normal notification. Also the level for a warning somewhere else.
    QUIET = 1
    # As much attention as the phone allows.
    LOUD = 2


class ReasonKind(Enum):
    """Why the rule decided what it did, so the screen can explain itself.
    Values are the Swift case names."""

    INSIDE_AREA = "insideArea"
    ADJACENT_TO_AREA = "adjacentToArea"
    WATCHED_PLACE_INSIDE_AREA = "watchedPlaceInsideArea"
    WATCHED_PLACE_NEAR_AREA = "watchedPlaceNearArea"
    OUTSIDE_AREA = "outsideArea"
    LOCATION_UNKNOWN = "locationUnknown"
    LAST_KNOWN_AREA = "lastKnownArea"


@dataclass(frozen=True)
class Reason:
    kind: ReasonKind
    cell: str | None = None       # the warning cell that matched
    bookmark: str | None = None   # the watched place that matched


@dataclass(frozen=True)
class Decision:
    urgency: Urgency
    match: Match
    reason: Reason


def decide(severity: Severity, area_cells, device_geohash: str | None, bookmarks=()) -> Decision:
    """The decision for one warning, given what this phone knows.

    - `device_geohash`: the phone's current building-level area code, or None.
    - `bookmarks`: places the person chose to watch ("watch my suburb"), for people
      who will not share their location.

    Only a warning that covers the person, at Watch and Act or above, is loud.
    """
    best, reason = Match.ELSEWHERE, Reason(ReasonKind.OUTSIDE_AREA)
    if device_geohash:
        m, cell = match(device_geohash, area_cells)
        if cell is not None and m > best:
            kind = ReasonKind.INSIDE_AREA if m == Match.INSIDE else ReasonKind.ADJACENT_TO_AREA
            best, reason = m, Reason(kind, cell)
    for bookmark in bookmarks:
        m, cell = match(bookmark, area_cells)
        if cell is not None and m > best:
            kind = ReasonKind.WATCHED_PLACE_INSIDE_AREA if m == Match.INSIDE else ReasonKind.WATCHED_PLACE_NEAR_AREA
            best, reason = m, Reason(kind, cell, bookmark)

    if best == Match.INSIDE:
        urgency = Urgency.LOUD if severity >= Severity.WATCH_AND_ACT else Urgency.QUIET
    else:
        urgency = Urgency.QUIET
    return Decision(urgency, best, reason)
