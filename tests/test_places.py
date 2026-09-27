"""Tests for alertmesh.places.

Swift reference: ../alert-mesh/AlertMeshTests/AlertMesh/Utils/AustralianPlacesTests.swift.
"""
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
