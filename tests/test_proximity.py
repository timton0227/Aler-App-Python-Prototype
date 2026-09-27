"""Tests for alertmesh.proximity.

Swift reference: ../alert-mesh/AlertMeshTests/AlertMesh/Services/AlertProximityTests.swift.
Cells are real cells around Fitzroy Crossing, WA (r7hg...), as in the Swift tests.
"""
import pytest

from alertmesh import geohash, proximity
from alertmesh.proximity import Match

DEVICE = "r7hg5x2k"  # a building-level location inside r7hg


@pytest.mark.parametrize("place, cells, expected", [
    ("r7hg5x2k", ["r7hg"], Match.INSIDE),        # precision 4 area
    ("r7hg5x2k", ["r7hg5x"], Match.INSIDE),      # precision 6 area
    ("r7hg5x2k", ["r7hg5x2k"], Match.INSIDE),    # exact building
    ("r7hg5x2k", ["r7"], Match.INSIDE),          # whole region
    ("r7hg5x2k", ["r7hu"], Match.ELSEWHERE),     # different cell, coarse: no adjacency at 4
    ("r7hg5x2k", ["9q8y"], Match.ELSEWHERE),     # other side of the world
    ("r7hg5x2k", ["r7hu", "r7hg"], Match.INSIDE),  # strongest across cells wins
])
def test_match_containment_by_prefix(place, cells, expected):
    """Swift: containmentByPrefix."""
    assert proximity.match(place, cells)[0] == expected


def test_match_coarse_place_containing_the_warning_is_adjacent_not_inside():
    """Swift: coarsePlaceContainingTheWarningIsAdjacentNotInside."""
    assert proximity.match("r7hg5", ["r7hg5x"]) == (Match.ADJACENT, "r7hg5x")


def test_match_neighbouring_cell_at_precision_five_is_adjacent():
    """Swift: neighbouringCellAtPrecisionFiveIsAdjacent."""
    cell = "r7hg5"
    place = geohash.neighbors(cell)[0] + "abc"
    assert proximity.match(place, [cell]) == (Match.ADJACENT, cell)


def test_match_neighbouring_cell_at_precision_four_is_not_adjacent():
    """Swift: neighbouringCellAtPrecisionFourIsNotAdjacent."""
    cell = "r7hg"
    place = geohash.neighbors(cell)[0] + "5x2k"
    assert proximity.match(place, [cell])[0] == Match.ELSEWHERE
    assert proximity.MINIMUM_PRECISION_FOR_ADJACENCY == 5


def test_match_precision_four_alert_against_precision_eight_device():
    """Swift: precisionFourAlertAgainstPrecisionEightDevice."""
    assert proximity.match("r7hg5x2k", ["r7hg"])[0] == Match.INSIDE
    assert proximity.match("r7hu5x2k", ["r7hg"])[0] == Match.ELSEWHERE


def test_match_place_coarser_than_cell():
    """Swift: placeCoarserThanCellCannotBeAdjacent."""
    cell = "r7hg5x"
    coarse = geohash.neighbors(cell)[0][:4]  # "r7hg", which IS a prefix of the cell
    assert proximity.match(coarse, [cell])[0] == Match.ADJACENT
    assert proximity.match("r7hu", [cell])[0] == Match.ELSEWHERE


def test_match_empty_place_or_cells_is_elsewhere():
    assert proximity.match("", ["r7hg"]) == (Match.ELSEWHERE, None)
    assert proximity.match("r7hg", []) == (Match.ELSEWHERE, None)
