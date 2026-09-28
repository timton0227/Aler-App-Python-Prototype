"""Australian towns and places, read straight from the app's built-in list.

Ported from: alert-mesh/AlertMesh/AlertMesh/Utils/AustralianPlaces.swift
Data:        alert-mesh/AlertMesh/AlertMesh/Utils/AustralianPlacesData.swift

The data is the Swift file itself, copied unchanged into alertmesh/data/ (see
alertmesh/swift_app.py; tools/copy_from_swift.py refreshes it), so the prototype and
the app use the same list.

Place names and coordinates © GeoNames (https://www.geonames.org), licensed under
Creative Commons Attribution 4.0. The licence asks for credit: show `CREDIT`.
The code in this file is public domain.
"""
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from alertmesh import geohash

# The licence (CC BY 4.0) asks for this credit wherever the names are shown.
CREDIT = "Place names: GeoNames (geonames.org), CC BY 4.0"

DATA_FILE_NAME = "AustralianPlacesData.swift"
# Where the list is looked for: alertmesh/data/, here and inside the desktop apps.
DATA_FILE_CANDIDATES = (
    Path(__file__).resolve().parent / "data" / DATA_FILE_NAME,
)


def data_file(candidates=DATA_FILE_CANDIDATES) -> Path:
    """The first place the list exists; the first place when none does."""
    return next((path for path in candidates if path.exists()), candidates[0])


DATA_FILE = data_file()


@dataclass(frozen=True)
class Place:
    """A named place (Swift: `AustralianPlace`). Coordinates in degrees."""

    name: str
    latitude: float
    longitude: float
    # A town people know: 1,000 people or more, or a capital or local seat.
    is_town: bool


def _section(source: str, name: str) -> str:
    """The text of one `static let <name> = #\"\"\" ... \"\"\"#` block."""
    match = re.search(rf'static let {name} = #"""\n(.*?)\n"""#', source, re.S)
    if match is None:
        raise ValueError(f"no '{name}' list in {DATA_FILE}")
    return match.group(1)


def _parse(raw: str, is_town: bool) -> list[Place]:
    """One place per line: `name|latitude|longitude`, coordinates in thousandths of a
    degree. Malformed lines are skipped, like the Swift parser."""
    out = []
    for line in raw.split("\n"):
        fields = line.split("|")
        if len(fields) != 3:
            continue
        try:
            lat, lon = int(fields[1]), int(fields[2])
        except ValueError:
            continue
        out.append(Place(fields[0], lat / 1000, lon / 1000, is_town))
    return out


@lru_cache(maxsize=1)
def all_places() -> tuple[Place, ...]:
    """Towns first, then smaller places. Read once, on first use."""
    return _load(DATA_FILE_CANDIDATES)


def _load(candidates) -> tuple[Place, ...]:
    path = data_file(candidates)
    if not path.exists():
        raise FileNotFoundError(
            "The town list was not found (python3 tools/copy_from_swift.py copies it from the Swift "
            "app). Looked in: " + "; ".join(str(c) for c in candidates)
        )
    source = path.read_text(encoding="utf-8")
    return tuple(_parse(_section(source, "towns"), True) + _parse(_section(source, "places"), False))


def towns() -> list[Place]:
    return [p for p in all_places() if p.is_town]


# --- Lookup -------------------------------------------------------------------


def find_all(name: str) -> list[Place]:
    """Every place with this name, case-insensitive. Towns come first, largest first
    (the file lists towns by size). Some names repeat: Mount Barker is in SA and WA."""
    wanted = name.strip().casefold()
    return [p for p in all_places() if p.name.casefold() == wanted]


def find(name: str) -> Place | None:
    """The first place with this name: the largest town, if any town has it."""
    matches = find_all(name)
    return matches[0] if matches else None


def geohash_of(place: Place, precision: int = 7) -> str:
    """The place's area code. 7 characters is about 150 m, the SOS precision."""
    return geohash.encode(place.latitude, place.longitude, precision)


# --- Rough place in words ("Near Katherine", "About 60 km south of Katherine") --
#
# Offline on purpose: a call for help mostly travels where there is no internet.
# The words are a rough guide beside the map pin, never a replacement for it.

TOWN_NEAR_KM = 15.0        # a town this close names the spot outright ("Near Darwin")
PLACE_NEAR_KM = 5.0        # any listed place this close names the spot
TOWN_LANDMARK_FACTOR = 2.0 # further out, a town is the landmark unless a smaller place is under half its distance
MAX_AWAY_KM = 300.0        # further than this from every place: say nothing (outside Australia)
MIN_GEOHASH_LENGTH = 5     # a shorter cell is ~40 km or more: too coarse to be "near" anything

COMPASS_POINTS = ("north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west")


@dataclass(frozen=True)
class Near:
    name: str


@dataclass(frozen=True)
class Away:
    km: int
    direction: str  # one of COMPASS_POINTS
    name: str


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine), Earth radius 6371 km."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi, d_lambda = phi2 - phi1, math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 6371 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def compass_point(lat1: float, lon1: float, lat2: float, lon2: float) -> str:
    """The initial bearing from the first point to the second, as one of 8 points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lambda = math.radians(lon2 - lon1)
    y = math.sin(d_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    degrees = (math.degrees(math.atan2(y, x)) + 360) % 360
    return COMPASS_POINTS[int((degrees + 22.5) / 45) % 8]


def _round_half_up(x: float) -> int:
    # Swift's rounded() rounds halves away from zero; Python's round() does not.
    return math.floor(x + 0.5)


def rounded_km(km: float) -> int:
    """Whole km below 20, then fives up to 100, then tens: never more precise than the list."""
    if km < 20:
        return _round_half_up(km)
    if km < 100:
        return _round_half_up(km / 5) * 5
    return _round_half_up(km / 10) * 10


def describe(latitude: float, longitude: float, candidates=None) -> Near | Away | None:
    """The rough place of a point, or None when no listed place is within 300 km."""
    candidates = all_places() if candidates is None else candidates
    # Rank by squared flat-earth distance: no trigonometry per place, and the right
    # order at these scales. Only the winners get an exact distance.
    cos_lat = math.cos(math.radians(latitude))
    nearest = nearest_town = None
    best = best_town = math.inf
    for place in candidates:
        d_lat = place.latitude - latitude
        d_lon = (place.longitude - longitude) * cos_lat
        rank = d_lat * d_lat + d_lon * d_lon
        if rank < best:
            nearest, best = place, rank
        if place.is_town and rank < best_town:
            nearest_town, best_town = place, rank

    if nearest_town and distance_km(nearest_town.latitude, nearest_town.longitude, latitude, longitude) <= TOWN_NEAR_KM:
        return Near(nearest_town.name)
    if nearest is None:
        return None
    km = distance_km(nearest.latitude, nearest.longitude, latitude, longitude)
    if km <= PLACE_NEAR_KM:
        return Near(nearest.name)
    if km > MAX_AWAY_KM:
        return None

    landmark, landmark_km = nearest, km
    if nearest_town and nearest_town != nearest:
        town_km = distance_km(nearest_town.latitude, nearest_town.longitude, latitude, longitude)
        if town_km <= km * TOWN_LANDMARK_FACTOR and town_km <= MAX_AWAY_KM:
            landmark, landmark_km = nearest_town, town_km
    return Away(
        rounded_km(landmark_km),
        compass_point(landmark.latitude, landmark.longitude, latitude, longitude),
        landmark.name,
    )


def text(rough: Near | Away) -> str:
    """English wording, as the Swift default strings."""
    if isinstance(rough, Near):
        return f"Near {rough.name}"
    return f"About {rough.km} km {rough.direction} of {rough.name}"


def label(cell: str) -> str | None:
    """Words for a report's area code, or None when there are none to give."""
    if len(cell) < MIN_GEOHASH_LENGTH or not geohash.is_valid(cell):
        return None
    rough = describe(*geohash.decode_center(cell))
    return None if rough is None else text(rough)
