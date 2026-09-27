"""Australian towns and places, read straight from the app's built-in list.

Ported from: ../alert-mesh/AlertMesh/AlertMesh/Utils/AustralianPlaces.swift
Data:        ../alert-mesh/AlertMesh/AlertMesh/Utils/AustralianPlacesData.swift

The data is NOT copied into this folder: it is read from the Swift file, so the
prototype and the app always use the same list.

Place names and coordinates © GeoNames (https://www.geonames.org), licensed under
Creative Commons Attribution 4.0. The licence asks for credit: show `CREDIT`.
The code in this file is public domain.
"""
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from alertmesh import geohash

# The licence (CC BY 4.0) asks for this credit wherever the names are shown.
CREDIT = "Place names: GeoNames (geonames.org), CC BY 4.0"

DATA_FILE = (
    Path(__file__).resolve().parents[2]
    / "alert-mesh" / "AlertMesh" / "AlertMesh" / "Utils" / "AustralianPlacesData.swift"
)


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
    if not DATA_FILE.exists():
        raise FileNotFoundError(
            f"{DATA_FILE} not found. The prototype reads the town list from the Swift app, "
            "so keep python-prototype/ next to alert-mesh/."
        )
    source = DATA_FILE.read_text(encoding="utf-8")
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
