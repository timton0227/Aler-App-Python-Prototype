"""Tests for alertmesh.pinmap: the clickable cells of the pin map, and typed coordinates.

New: the iPhone app has no pin (it always has GPS).
"""
import pytest

from alertmesh import geohash, pinmap

KATHERINE_CELL = "qvqj0cm"


def test_children_are_the_32_cells_inside():
    kids = pinmap.children("qvqj0")
    assert len(kids) == len(set(kids)) == 32
    assert all(k.startswith("qvqj0") and len(k) == 6 for k in kids)


def test_step_one_is_288_cells_of_about_a_km_round_the_guess():
    cells = pinmap.coarse_cells(KATHERINE_CELL)
    assert len(cells) == len(set(cells)) == 288
    assert all(len(c) == pinmap.COARSE_LENGTH for c in cells)
    assert KATHERINE_CELL[:6] in cells


def test_step_two_is_288_cells_of_about_150_m_round_the_click():
    cells = pinmap.fine_cells("qvqj0c")
    assert len(cells) == len(set(cells)) == 288
    assert all(len(c) == pinmap.FINE_LENGTH for c in cells)
    assert KATHERINE_CELL in cells
    assert pinmap.fine_cells("qvqj0cz9") == pinmap.fine_cells("qvqj0c")  # longer input is cut


def test_outline_is_the_cell_box_closed_in_map_order():
    lat_lo, lat_hi, lon_lo, lon_hi = geohash.decode_bounds(KATHERINE_CELL)
    ring = pinmap.outline(KATHERINE_CELL)
    assert ring[0] == ring[-1] == [lon_lo, lat_lo]
    assert [lon_hi, lat_hi] in ring


def test_rows_mark_the_chosen_cell():
    rows = pinmap.rows(["qvqj0cm", "qvqj0ct"], chosen="qvqj0ct")
    assert [(r["cell"], r["chosen"]) for r in rows] == [("qvqj0cm", False), ("qvqj0ct", True)]


def test_the_view_fits_the_cells():
    lat, lon, zoom = pinmap.view(pinmap.coarse_cells(KATHERINE_CELL))
    lat_lo, lat_hi, lon_lo, lon_hi = pinmap.bounds(pinmap.coarse_cells(KATHERINE_CELL))
    assert lat_lo < lat < lat_hi and lon_lo < lon < lon_hi
    fine_zoom = pinmap.view(pinmap.fine_cells(KATHERINE_CELL))[2]
    assert 10 < zoom < 13 and 12 < fine_zoom < 16 and fine_zoom > zoom


def test_town_names_near_the_map():
    names = [t["name"] for t in pinmap.nearby_towns(pinmap.coarse_cells(KATHERINE_CELL))]
    assert "Katherine" in names and "Darwin" not in names


@pytest.mark.parametrize("selection, cell", [
    ({"indices": {"fine": [3]}, "objects": {"fine": [{"cell": "qvqj0cm", "chosen": False}]}}, "qvqj0cm"),
    ({"indices": {}, "objects": {}}, None),
    ({"objects": {"coarse": [{"cell": "qvqj0c"}]}}, None),  # another layer
    ({"objects": {"fine": [{"cell": "not a cell!"}]}}, None),
    (None, None),
])
def test_the_clicked_cell_from_streamlits_selection(selection, cell):
    assert pinmap.picked(selection, pinmap.FINE_LAYER) == cell


@pytest.mark.parametrize("text, point", [
    ("-14.465, 132.263", (-14.465, 132.263)),
    ("  -14.465 132.263 ", (-14.465, 132.263)),
    ("-14.465;132.263", (-14.465, 132.263)),
    ("14.465° S, 132.263° E", (-14.465, 132.263)),
    ("14.465S 132.263E", (-14.465, 132.263)),
    ("51.5, -0.12", (51.5, -0.12)),
    ("0.12 W, 51.5 N", None),  # longitude first is not taken as latitude
    ("95, 132", None),
    ("-14.465", None),
    ("Katherine", None),
    ("", None),
])
def test_typed_or_pasted_coordinates(text, point):
    assert pinmap.parse_coordinates(text) == point


def test_the_pin_for_a_point_is_about_150_m():
    assert pinmap.cell_at(-14.465, 132.263) == geohash.encode(-14.465, 132.263, 7)
