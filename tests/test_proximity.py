"""Tests for alertmesh.proximity.

Swift reference: ../alert-mesh/AlertMeshTests/AlertMesh/Services/AlertProximityTests.swift.
Cells are real cells around Fitzroy Crossing, WA (r7hg...), as in the Swift tests.
"""
import pytest

from alertmesh import geohash, proximity
from alertmesh.proximity import Match, Reason, ReasonKind, Urgency
from alertmesh.wire import Severity

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


# --- decide (step 4.2)


@pytest.mark.parametrize("severity, expected", [
    (Severity.EMERGENCY_WARNING, Urgency.LOUD),
    (Severity.WATCH_AND_ACT, Urgency.LOUD),
    (Severity.ADVICE, Urgency.QUIET),
])
def test_decide_inside_maps_by_severity(severity, expected):
    """Swift: insideMapsBySeverity."""
    d = proximity.decide(severity, ["r7hg"], DEVICE)
    assert d.urgency == expected
    assert d.match == Match.INSIDE
    assert d.reason == Reason(ReasonKind.INSIDE_AREA, "r7hg")


@pytest.mark.parametrize("severity", list(Severity))
def test_decide_adjacent_is_always_quiet(severity):
    """Swift: adjacentIsAlwaysQuiet."""
    cell = "r7hg5"
    d = proximity.decide(severity, [cell], geohash.neighbors(cell)[0] + "abc")
    assert d.urgency == Urgency.QUIET
    assert d.reason == Reason(ReasonKind.ADJACENT_TO_AREA, cell)


@pytest.mark.parametrize("severity", list(Severity))
def test_decide_elsewhere_is_quiet_when_location_is_known(severity):
    """Swift: elsewhereIsQuietWhenLocationIsKnown. Everyone hears about every warning, gently."""
    d = proximity.decide(severity, ["9q8y"], DEVICE)
    assert d.urgency == Urgency.QUIET
    assert d.reason == Reason(ReasonKind.OUTSIDE_AREA)


def test_decide_bookmark_inside_area_is_loud_without_any_device_location():
    """Swift: bookmarkInsideAreaIsLoudWithoutAnyDeviceLocation."""
    d = proximity.decide(Severity.EMERGENCY_WARNING, ["r7hg"], None, bookmarks=["9q8yy", "r7hg5"])
    assert d.urgency == Urgency.LOUD
    assert d.reason == Reason(ReasonKind.WATCHED_PLACE_INSIDE_AREA, "r7hg", "r7hg5")


def test_decide_bookmark_elsewhere_with_no_device_location_is_outside():
    """Swift: bookmarkElsewhereWithNoDeviceLocationIsNotLocationUnknown."""
    d = proximity.decide(Severity.ADVICE, ["r7hg"], None, bookmarks=["9q8yy"])
    assert d.urgency == Urgency.QUIET
    assert d.reason == Reason(ReasonKind.OUTSIDE_AREA)


def test_decide_device_outranks_a_weaker_bookmark_and_vice_versa():
    """Swift: deviceLocationOutranksAWeakerBookmarkMatchAndViceVersa."""
    cell = "r7hg5"
    neighbour = geohash.neighbors(cell)[0]
    bookmark_wins = proximity.decide(Severity.ADVICE, [cell], neighbour + "abc", bookmarks=[cell + "xyz"])
    assert bookmark_wins.match == Match.INSIDE
    assert bookmark_wins.reason == Reason(ReasonKind.WATCHED_PLACE_INSIDE_AREA, cell, cell + "xyz")
    device_wins = proximity.decide(Severity.ADVICE, [cell], cell + "abc", bookmarks=[neighbour + "xyz"])
    assert device_wins.reason == Reason(ReasonKind.INSIDE_AREA, cell)


def test_decide_watched_place_near_area():
    cell = "r7hg5"
    d = proximity.decide(Severity.EMERGENCY_WARNING, [cell], None, bookmarks=[geohash.neighbors(cell)[0]])
    assert d.urgency == Urgency.QUIET
    assert d.reason.kind == ReasonKind.WATCHED_PLACE_NEAR_AREA


# --- No location and remembered area (step 4.3)


def test_unknown_location_keeps_emergency_warnings_quiet_not_silent():
    """Swift: unknownLocationKeepsEmergencyWarningsQuietNotSilent."""
    d = proximity.decide(Severity.EMERGENCY_WARNING, ["r7hg"], None)
    assert d.urgency == Urgency.QUIET
    assert d.reason == Reason(ReasonKind.LOCATION_UNKNOWN)


@pytest.mark.parametrize("severity", [Severity.ADVICE, Severity.WATCH_AND_ACT])
def test_unknown_location_keeps_lower_severities_quiet_too(severity):
    """Swift: unknownLocationKeepsLowerSeveritiesQuietToo. An empty string is unknown too."""
    assert proximity.decide(severity, ["r7hg"], None).reason == Reason(ReasonKind.LOCATION_UNKNOWN)
    assert proximity.decide(severity, ["r7hg"], "").reason == Reason(ReasonKind.LOCATION_UNKNOWN)
    assert proximity.decide(severity, ["r7hg"], None).urgency == Urgency.QUIET


def test_remembered_area_warning_inside_it_is_loud():
    """Swift: aWarningInsideTheRememberedAreaIsLoud."""
    d = proximity.decide(Severity.WATCH_AND_ACT, ["r7hg5x"], None, remembered_cell="r7hg")
    assert d.urgency == Urgency.LOUD
    assert d.match == Match.INSIDE
    assert d.reason == Reason(ReasonKind.LAST_KNOWN_AREA, "r7hg5x")


def test_remembered_area_warning_covering_it_is_loud():
    """Swift: aWarningCoveringTheRememberedAreaIsLoud."""
    d = proximity.decide(Severity.EMERGENCY_WARNING, ["9q8y", "r7"], None, remembered_cell="r7hg")
    assert d.urgency == Urgency.LOUD
    assert d.reason == Reason(ReasonKind.LAST_KNOWN_AREA, "r7")


def test_remembered_area_advice_stays_quiet():
    """Swift: adviceInTheRememberedAreaStaysQuiet."""
    assert proximity.decide(Severity.ADVICE, ["r7hg5x"], None, remembered_cell="r7hg").urgency == Urgency.QUIET


def test_remembered_area_a_live_fix_wins():
    """Swift: aLiveFixWinsOverTheRememberedArea."""
    d = proximity.decide(Severity.WATCH_AND_ACT, ["r7hg5x"], "9q8yy5x2", remembered_cell="r7hg")
    assert d.urgency == Urgency.QUIET
    assert d.reason == Reason(ReasonKind.OUTSIDE_AREA)


def test_remembered_area_that_does_not_match_is_still_location_unknown():
    """Swift: aRememberedAreaThatDoesNotMatchIsStillLocationUnknown."""
    d = proximity.decide(Severity.WATCH_AND_ACT, ["9q8y"], None, remembered_cell="r7hg")
    assert d.urgency == Urgency.QUIET
    assert d.reason == Reason(ReasonKind.LOCATION_UNKNOWN)


def test_no_rule_ever_returns_silent():
    """Warn everyone (Swift Task 8.38): across every case above, never SILENT."""
    cases = [(DEVICE, ()), (None, ()), ("", ()), (None, ("9q8yy",)), ("9q8yy5x2", ("r7hg5",))]
    for severity in Severity:
        for cells in (["r7hg"], ["9q8y"], ["r7hg5x", "r7hu"]):
            for device, bookmarks in cases:
                for remembered in (None, "r7hg", "9q8y"):
                    d = proximity.decide(severity, cells, device, bookmarks, remembered)
                    assert d.urgency != Urgency.SILENT


# --- SOS proximity (step 7.7; Swift: SOSProximity in SOSNotificationsModel.swift)


def test_sos_near_this_phone_or_a_watched_place_is_loud():
    assert proximity.sos_urgency("r7hg5x2", DEVICE) == Urgency.LOUD          # same 5-char cell
    near = geohash.neighbors("r7hg5")[0]
    assert proximity.sos_urgency(near + "zz", DEVICE) == Urgency.LOUD        # neighbouring cell
    assert proximity.sos_urgency("9q8yy5x", DEVICE) == Urgency.QUIET         # far away
    assert proximity.sos_urgency("r7hg5x2", None, ["r7hg5"]) == Urgency.LOUD  # watched place
    assert proximity.sos_urgency("r7hg5x2", None) == Urgency.QUIET           # no location: still notifies
