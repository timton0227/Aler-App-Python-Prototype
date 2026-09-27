"""Tests for alertmesh.places.

Swift reference: ../alert-mesh/AlertMeshTests/AlertMesh/Utils/AustralianPlacesTests.swift.
"""
import math

import pytest

from alertmesh import geohash, places


def test_load_towns_and_places_from_the_swift_file():
    """Swift: theListParsesAndStaysInAustralia. Counts from the data file's own header."""
    everything = places.all_places()
    assert len(places.towns()) == 996
    assert len(everything) - len(places.towns()) == 3396
    for place in everything:
        assert place.name
        assert -44.0 <= place.latitude <= -9.0, place
        assert 112.0 <= place.longitude <= 160.0, place


def test_load_converts_thousandths_to_degrees():
    sydney = next(p for p in places.towns() if p.name == "Sydney")
    assert (sydney.latitude, sydney.longitude) == (-33.868, 151.207)
    assert places.all_places()[0].name == "Sydney"  # towns come first, in file order


def test_load_skips_malformed_lines():
    parsed = places._parse("Good|-1000|2000\nno bars\nBad|x|1\nToo|1|2|3", is_town=False)
    assert parsed == [places.Place("Good", -1.0, 2.0, False)]



def test_lookup_known_towns_give_the_expected_geohash():
    # Sydney's geohash r3gx2f is widely published; the others are checked by
    # decoding: the cell's box must contain the town.
    assert places.geohash_of(places.find("Sydney"), 6) == "r3gx2f"
    for name in ("Darwin", "Katherine", "Alice Springs", "Tennant Creek", "Fitzroy Crossing"):
        town = places.find(name)
        assert town is not None and town.is_town, name
        lat_lo, lat_hi, lon_lo, lon_hi = geohash.decode_bounds(places.geohash_of(town))
        assert lat_lo <= town.latitude <= lat_hi and lon_lo <= town.longitude <= lon_hi


def test_lookup_is_case_insensitive_and_prefers_the_largest_town():
    assert places.find("  darwin ") == places.find("Darwin")
    barkers = places.find_all("Mount Barker")
    assert len(barkers) == 2
    assert places.find("Mount Barker") == barkers[0]
    assert barkers[0].latitude == -35.067  # the SA town, listed first (larger)


def test_lookup_unknown_name_is_none():
    assert places.find("Atlantis") is None
    assert places.find_all("Atlantis") == []


def test_lookup_default_precision_is_the_sos_precision():
    assert len(places.geohash_of(places.find("Katherine"))) == 7


def test_lookup_credit_names_geonames_and_the_licence():
    """Swift: AustralianPlaces.Strings.credit."""
    for part in ("GeoNames", "geonames.org", "CC BY 4.0"):
        assert part in places.CREDIT


# --- Rough place in words (step 6.3). Mirrors the Swift tests' made-up "Bigtown".

BIGTOWN = places.Place("Bigtown", -14.0, 132.0, True)


def small(name, lat, lon):
    return places.Place(name, lat, lon, False)


def offset(km, bearing):
    """km from Bigtown along a bearing (flat-earth, fine at these distances)."""
    r = math.radians(bearing)
    return (BIGTOWN.latitude + km * math.cos(r) / 111.195,
            BIGTOWN.longitude + km * math.sin(r) / (111.195 * math.cos(math.radians(BIGTOWN.latitude))))


def test_a_nearby_town_beats_a_closer_small_place():
    """Swift: aNearbyTownBeatsACloserSmallPlace."""
    assert places.describe(-14.0, 132.045, [BIGTOWN, small("Smallplace", -14.0, 132.05)]) == places.Near("Bigtown")


def test_a_small_place_names_the_spot_when_no_town_is_near():
    """Swift: aSmallPlaceNamesTheSpotWhenNoTownIsNear."""
    assert places.describe(-14.0, 132.33, [BIGTOWN, small("Smallplace", -14.0, 132.3)]) == places.Near("Smallplace")


@pytest.mark.parametrize("bearing, direction", [(0, "north"), (45, "north-east"), (90, "east"), (180, "south"), (270, "west")])
def test_further_out_it_says_how_far_and_which_way(bearing, direction):
    """Swift: furtherOutItSaysHowFarAndWhichWay."""
    assert places.describe(*offset(60, bearing), [BIGTOWN]) == places.Away(60, direction, "Bigtown")


def test_a_town_is_the_landmark_unless_a_small_place_is_much_closer():
    """Swift: aTownIsTheLandmarkUnlessASmallPlaceIsMuchCloser."""
    lat, lon = offset(60, 180)
    tiny = small("Tinyplace", lat + 50 / 111.195, lon)
    assert places.describe(lat, lon, [BIGTOWN, tiny]) == places.Away(60, "south", "Bigtown")


def test_a_much_closer_small_place_is_the_landmark():
    """Swift: aMuchCloserSmallPlaceIsTheLandmark."""
    lat, lon = offset(90, 180)
    near = small("Smallplace", lat + 20 / 111.195, lon)
    assert places.describe(lat, lon, [BIGTOWN, near]) == places.Away(20, "south", "Smallplace")


def test_distances_are_rounded():
    """Swift: distancesAreRounded. Plus halves round up, like Swift."""
    assert (places.rounded_km(7.4), places.rounded_km(23), places.rounded_km(147)) == (7, 25, 150)
    assert (places.rounded_km(2.5), places.rounded_km(22.5), places.rounded_km(125)) == (3, 25, 130)


def test_nothing_within_300_km_says_nothing():
    """Swift: nothingWithin300KilometresSaysNothing."""
    assert places.describe(*offset(400, 180), [BIGTOWN]) is None


def test_a_coarse_cell_gets_no_name():
    """Swift: aCoarseCellGetsNoName."""
    darwin = geohash.encode(-12.4634, 130.8456, 7)
    assert places.label(darwin[:4]) is None
    assert places.label(darwin) is not None


def test_words_carry_the_name_and_the_distance():
    """Swift: wordsCarryTheNameAndTheDistance."""
    assert places.text(places.Near("Katherine")) == "Near Katherine"
    assert places.text(places.Away(60, "south", "Katherine")) == "About 60 km south of Katherine"


@pytest.mark.parametrize("name, lat, lon", [
    ("Darwin", -12.4634, 130.8456), ("Katherine", -14.4652, 132.2635),
    ("Alice Springs", -23.6980, 133.8807), ("Tennant Creek", -19.6497, 134.1915),
])
def test_territory_towns_read_as_themselves(name, lat, lon):
    """Swift: territoryTownsReadAsThemselves (real list)."""
    assert places.describe(lat, lon) == places.Near(name)


def test_the_desert_gets_a_distance_and_direction():
    """Swift: theDesertGetsADistanceAndDirection (Tanami)."""
    rough = places.describe(-20.0, 130.0)
    assert isinstance(rough, places.Away) and rough.km > 5


def test_outside_australia_says_nothing():
    """Swift: outsideAustraliaSaysNothing (London)."""
    assert places.describe(51.5074, -0.1278) is None
