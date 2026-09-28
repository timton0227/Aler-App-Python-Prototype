"""Tests for alertmesh.geohash.

Swift reference: alert-mesh/AlertMesh/Protocols/Geohash.swift and
alert-mesh/AlertMeshTests/LocationChannelsTests.swift.
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


def test_encode_known_cell():
    # The standard example from the geohash literature (Wikipedia, "Geohash").
    assert geohash.encode(57.64911, 10.40744, 11) == "u4pruydqqvj"


def test_encode_precisions_are_prefixes_of_each_other():
    # Swift: LocationChannelsTests.geohashEncoderPrecisionMapping (Statue of Liberty).
    lat, lon = 40.6892, -74.0445
    cells = [geohash.encode(lat, lon, p) for p in (7, 6, 5, 4, 2)]
    assert [len(c) for c in cells] == [7, 6, 5, 4, 2]
    for longer, shorter in zip(cells, cells[1:]):
        assert longer.startswith(shorter)


def test_encode_zero_precision_is_empty_and_out_of_range_is_clamped():
    assert geohash.encode(10, 10, 0) == ""
    assert geohash.encode(95, 200, 4) == geohash.encode(90, 180, 4)


def test_decode_bounds_contain_the_encoded_point():
    lat, lon = -35.0735, 138.8566  # Mount Barker, SA
    for precision in range(1, 10):
        lat_lo, lat_hi, lon_lo, lon_hi = geohash.decode_bounds(geohash.encode(lat, lon, precision))
        assert lat_lo <= lat <= lat_hi
        assert lon_lo <= lon <= lon_hi


def test_decode_center_re_encodes_to_the_same_cell():
    for cell in ("r7hg", "r7hu", "u4pruydqqvj", "qd66hr"):
        lat, lon = geohash.decode_center(cell)
        assert geohash.encode(lat, lon, len(cell)) == cell


def test_decode_empty_is_the_whole_world():
    assert geohash.decode_bounds("") == (-90.0, 90.0, -180.0, 180.0)


def test_neighbors_are_eight_distinct_cells_touching_the_cell():
    cell = "r7hgu"
    around = geohash.neighbors(cell)
    assert len(around) == 8
    assert len(set(around)) == 8
    assert cell not in around
    assert all(len(n) == len(cell) for n in around)
    # Each neighbour sits exactly one cell-height / cell-width away, in the
    # documented N, NE, E, SE, S, SW, W, NW order.
    lat_lo, lat_hi, lon_lo, lon_hi = geohash.decode_bounds(cell)
    height, width = lat_hi - lat_lo, lon_hi - lon_lo
    lat, lon = geohash.decode_center(cell)
    steps = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
    for n, (dlat, dlon) in zip(around, steps):
        n_lat, n_lon = geohash.decode_center(n)
        assert abs(n_lat - (lat + dlat * height)) < 1e-9
        assert abs(n_lon - (lon + dlon * width)) < 1e-9


def test_neighbors_near_pole_skip_out_of_bounds_cells():
    # Swift: LocationChannelsTests.geohashNeighborsNearPoleSkipOutOfBoundsCells.
    near_pole = geohash.encode(89.9999, 0.0, 8)
    around = geohash.neighbors(near_pole)
    assert around
    assert len(around) < 8


def test_neighbors_wrap_at_the_date_line():
    east_edge = geohash.encode(0.0, 179.9999, 5)
    around = geohash.neighbors(east_edge)
    east = around[2]
    _, _, lon_lo, _ = geohash.decode_bounds(east)
    assert lon_lo < -179  # the eastern neighbour is on the far west side


def test_neighbors_of_empty_is_empty():
    assert geohash.neighbors("") == []
