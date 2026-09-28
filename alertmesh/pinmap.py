"""Dropping a pin: the clickable cells on the phone app's map, and typed coordinates.

New: the iPhone app has GPS and no pin. On a laptop without a position of its own (no
Location Services, Wi-Fi off, permission refused) the person shows where they are.

Streamlit's map tells the app which shape was clicked, not which spot, so the map is
covered in geohash cells and the person clicks one, in two steps:
1. cells of about 1.2 x 0.6 km (6 characters) over some 15 km around the current guess;
2. inside the one clicked and its neighbours, cells of about 150 m (7 characters), the
   precision a call for help is sent with.

Town names are drawn on the map too, so it can be read when the background map does
not load (it comes from the internet). Coordinates typed or pasted (for example from a
map app on a phone) work fully offline.

This is free and unencumbered software released into the public domain.
"""
import math
import re

from alertmesh import geohash, places

COARSE_LENGTH, FINE_LENGTH = 6, 7
COARSE_LAYER, FINE_LAYER = "coarse", "fine"
# How far round the map's middle town names are looked for, in degrees (about 30 km).
TOWN_MARGIN_DEG = 0.3


def children(cell: str) -> list[str]:
    """The 32 cells one character longer inside `cell`."""
    return [cell + c for c in geohash.BASE32]


def block(cell: str) -> list[str]:
    """The cell and its neighbours."""
    return [cell, *geohash.neighbors(cell)]


def coarse_cells(guess: str) -> list[str]:
    """Step 1: the ~1.2 km cells in the ~5 km cell of the guess and its 8 neighbours (288)."""
    return [child for cell in block(guess[:COARSE_LENGTH - 1]) for child in children(cell)]


def fine_cells(cell: str) -> list[str]:
    """Step 2: the ~150 m cells in a ~1.2 km cell and its 8 neighbours (288)."""
    return [child for near in block(cell[:FINE_LENGTH - 1]) for child in children(near)]


def outline(cell: str) -> list[list[float]]:
    """The cell's corners as [longitude, latitude] (the map's order), closed."""
    lat_lo, lat_hi, lon_lo, lon_hi = geohash.decode_bounds(cell)
    return [[lon_lo, lat_lo], [lon_hi, lat_lo], [lon_hi, lat_hi], [lon_lo, lat_hi], [lon_lo, lat_lo]]


def rows(cells: list[str], chosen: str | None = None) -> list[dict]:
    """One row per cell for the map layer; the chosen one is marked."""
    return [{"cell": cell, "outline": outline(cell), "chosen": cell == chosen} for cell in cells]


def bounds(cells: list[str]) -> tuple[float, float, float, float]:
    """(lat_min, lat_max, lon_min, lon_max) round all the cells."""
    boxes = [geohash.decode_bounds(cell) for cell in cells]
    return (min(b[0] for b in boxes), max(b[1] for b in boxes),
            min(b[2] for b in boxes), max(b[3] for b in boxes))


def view(cells: list[str], width_px: int = 640, height_px: int = 420) -> tuple[float, float, float]:
    """(latitude, longitude, zoom) that fit the cells in a map of this size."""
    lat_lo, lat_hi, lon_lo, lon_hi = bounds(cells)
    lat, lon = (lat_lo + lat_hi) / 2, (lon_lo + lon_hi) / 2
    # Web maps are 256 px wide at zoom 0 for 360 degrees; latitude is stretched by 1/cos.
    zoom_x = math.log2(width_px * 360 / (256 * (lon_hi - lon_lo)))
    zoom_y = math.log2(height_px * 360 / (256 * (lat_hi - lat_lo) / math.cos(math.radians(lat))))
    return lat, lon, round(min(zoom_x, zoom_y), 2)


def nearby_towns(cells: list[str]) -> list[dict]:
    """Towns on or near the map, as {"name", "position": [lon, lat]}, for name labels."""
    lat_lo, lat_hi, lon_lo, lon_hi = bounds(cells)
    return [{"name": t.name, "position": [t.longitude, t.latitude]} for t in places.towns()
            if lat_lo - TOWN_MARGIN_DEG <= t.latitude <= lat_hi + TOWN_MARGIN_DEG
            and lon_lo - TOWN_MARGIN_DEG <= t.longitude <= lon_hi + TOWN_MARGIN_DEG]


def picked(selection, layer: str) -> str | None:
    """The cell clicked on the map, from Streamlit's selection:
    {"indices": {layer: [i]}, "objects": {layer: [row]}}."""
    try:
        cell = selection["objects"][layer][0]["cell"]
    except (KeyError, IndexError, TypeError):
        return None
    return cell if isinstance(cell, str) and geohash.is_valid(cell) else None


_NUMBER = r"([-+]?\d+(?:\.\d+)?)\s*°?\s*([NSEWnsew])?"
_PAIR = re.compile(rf"^\s*{_NUMBER}\s*[,; ]\s*{_NUMBER}\s*$")


def parse_coordinates(text: str) -> tuple[float, float] | None:
    """(latitude, longitude) from "-14.465, 132.263" (a map app's "copy coordinates"),
    "-14.465 132.263" or "14.465° S, 132.263° E"; None if it is not such a pair."""
    match = _PAIR.match(text or "")
    if not match:
        return None
    lat, lat_side, lon, lon_side = float(match[1]), (match[2] or "").upper(), float(match[3]), (match[4] or "").upper()
    if lat_side in ("E", "W") or lon_side in ("N", "S"):
        return None
    if lat_side == "S":
        lat = -abs(lat)
    if lon_side == "W":
        lon = -abs(lon)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def cell_at(latitude: float, longitude: float) -> str:
    """The pin's cell for a point."""
    return geohash.encode(latitude, longitude, FINE_LENGTH)
