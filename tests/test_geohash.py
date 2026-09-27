"""Tests for alertmesh.geohash.

Swift reference: ../alert-mesh/AlertMesh/Protocols/Geohash.swift and
../alert-mesh/AlertMeshTests/LocationChannelsTests.swift.
"""
from alertmesh import geohash


def test_valid_alphabet_has_no_a_i_l_o():
    assert len(geohash.BASE32) == 32
    for letter in "ailo":
        assert letter not in geohash.BASE32


def test_valid_accepts_cells_of_1_to_12_characters():
    assert geohash.is_valid("r")
    assert geohash.is_valid("r7hg")
    assert geohash.is_valid("R7HG")  # case-insensitive, like Swift
    assert geohash.is_valid("r7hgr7hgr7hg")


def test_valid_rejects_empty_too_long_and_bad_characters():
    assert not geohash.is_valid("")
    assert not geohash.is_valid("r7hgr7hgr7hgr")  # 13 characters
    assert not geohash.is_valid("r7ha")  # "a" is not in the alphabet
    assert not geohash.is_valid("r7h ")
