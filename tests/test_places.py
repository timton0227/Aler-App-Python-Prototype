"""Tests for alertmesh.places.

Swift reference: ../alert-mesh/AlertMeshTests/AlertMesh/Utils/AustralianPlacesTests.swift.
"""
from alertmesh import places


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
