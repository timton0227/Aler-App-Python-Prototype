"""Where the person is: a pin they dropped, this Mac's own location, or their town.

Based on: ../alert-mesh/AlertMesh/AlertMesh/Services/LocationStateManager.swift (one
coarse fix at a time, turned into geohashes) and CommunityReportManager.swift (calls
for help and "I'm safe" to 7 characters, about 150 m).

The iPhone app always has GPS. A laptop may not have a position at all, so the phone
app takes the first of these that it has:
1. a pin the person dropped on a map. It is deliberate (often a correction of a poor
   fix), so it stays until they clear it;
2. this Mac's fix from Location Services, while it is under an hour old;
3. the centre of the town picked in Settings, as before this phase.

Like the app, only a geohash is kept and sent, never raw coordinates, and it is only as
exact as the fix: a Wi-Fi fix good to 1 km must not claim a 19 m cell.

This is free and unencumbered software released into the public domain.
"""
from dataclasses import dataclass

from alertmesh import geohash, places

MAC, PIN, TOWN = "mac", "pin", "town"

# A fix older than this is not used: a laptop may have been carried elsewhere since.
FIX_FRESH_MS = 60 * 60 * 1000
# A pin is picked from cells of this length (about 150 m), and a town's centre has
# always stood in at this length.
PIN_PRECISION = TOWN_PRECISION = 7
# (the most a fix may be off by, in metres; the geohash length that is still honest).
# A cell of 8 characters is about 38 x 19 m, 7 about 150 m, 6 about 1.2 x 0.6 km.
PRECISION_BY_ACCURACY = ((40, 8), (150, 7), (1200, 6))
COARSEST_PRECISION = 5


def precision_for(accuracy_m: float) -> int:
    """The longest geohash a fix this exact can honestly give."""
    for limit, precision in PRECISION_BY_ACCURACY:
        if accuracy_m <= limit:
            return precision
    return COARSEST_PRECISION


@dataclass(frozen=True)
class Fix:
    """A position from this Mac's Location Services, already turned into a geohash."""

    cell: str
    accuracy_m: float
    at_ms: int

    @classmethod
    def from_point(cls, latitude: float, longitude: float, accuracy_m: float, at_ms: int) -> "Fix | None":
        """None for a reading macOS marks as invalid (a negative accuracy)."""
        if not accuracy_m >= 0:  # also catches NaN
            return None
        return cls(geohash.encode(latitude, longitude, precision_for(accuracy_m)), accuracy_m, at_ms)

    def is_fresh(self, now_ms: int) -> bool:
        return now_ms - self.at_ms <= FIX_FRESH_MS


@dataclass(frozen=True)
class Where:
    """The position in use: its geohash, where it came from, and a detail for the words
    (the town's name, or how far off the Mac's fix may be)."""

    geohash: str
    source: str
    detail: str | float | None = None


def choose(pin: str | None, fix: Fix | None, town: places.Place | None, now_ms: int) -> Where | None:
    """The pin, else a fresh fix, else the town's centre; None when there is none."""
    if pin and geohash.is_valid(pin):
        return Where(pin.lower()[:PIN_PRECISION], PIN)
    if fix is not None and fix.is_fresh(now_ms):
        return Where(fix.cell, MAC, fix.accuracy_m)
    if town is not None:
        return Where(places.geohash_of(town, TOWN_PRECISION), TOWN, town.name)
    return None


def distance_words(metres: float) -> str:
    """"about 60 m", "about 1.5 km": no more exact than the fix itself."""
    if metres < 1000:
        return f"about {max(10, round(metres / 10) * 10)} m"
    return f"about {metres / 1000:.1f} km".replace(".0 km", " km")


def words(where: Where) -> str:
    """Where the position came from, to finish "It says you are …" or "Sent from …"."""
    if where.source == MAC:
        return f"at this Mac's location ({distance_words(where.detail)})"
    if where.source == PIN:
        return "at the pin you dropped"
    return f"at the centre of {where.detail}, the town in Settings"
