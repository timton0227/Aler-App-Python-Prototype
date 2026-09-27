"""The loud-or-quiet rule: how close is this phone to a warning, and how loud should it be?

Ported from: ../alert-mesh/AlertMesh/AlertMesh/Services/AlertProximity.swift

Uses area codes (geohashes) only, never raw coordinates, like the app. A place is
INSIDE a warning when its code starts with one of the warning's cells, and ADJACENT
when it sits in a neighbouring cell (only for cells of 5 characters or more).

This is free and unencumbered software released into the public domain.
"""
from enum import IntEnum

from alertmesh import geohash


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
