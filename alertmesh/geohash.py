"""Geohash: turns a latitude and longitude into a short area code, and back.

Ported from: ../alert-mesh/AlertMesh/Protocols/Geohash.swift (enum Geohash).

A geohash is a string of base-32 characters. Each extra character narrows the area,
so a longer code is a smaller box, and a code that starts with another code lies
inside it ("r7hg" is inside "r7h").

This is free and unencumbered software released into the public domain.
"""

# The geohash alphabet. It has no "a", "i", "l" or "o".
BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
_BASE32_MAP = {c: i for i, c in enumerate(BASE32)}


def is_valid(geohash: str) -> bool:
    """True for a non-empty geohash of at most 12 characters from the alphabet.

    Case-insensitive, like the Swift `isValidGeohash`.
    """
    if not 1 <= len(geohash) <= 12:
        return False
    return all(c in _BASE32_MAP for c in geohash.lower())


def encode(latitude: float, longitude: float, precision: int) -> str:
    """The geohash of length `precision` that contains the point.

    Latitude is clamped to -90..90 and longitude to -180..180. A precision of 0 or
    less gives an empty string, like the Swift `encode`.
    """
    if precision <= 0:
        return ""
    lat_lo, lat_hi = -90.0, 90.0
    lon_lo, lon_hi = -180.0, 180.0
    lat = max(-90.0, min(90.0, latitude))
    lon = max(-180.0, min(180.0, longitude))

    out = []
    is_even = True  # even bits split longitude, odd bits split latitude
    bit = 0
    ch = 0
    while len(out) < precision:
        if is_even:
            mid = (lon_lo + lon_hi) / 2
            if lon >= mid:
                ch |= 1 << (4 - bit)
                lon_lo = mid
            else:
                lon_hi = mid
        else:
            mid = (lat_lo + lat_hi) / 2
            if lat >= mid:
                ch |= 1 << (4 - bit)
                lat_lo = mid
            else:
                lat_hi = mid
        is_even = not is_even
        if bit < 4:
            bit += 1
        else:
            out.append(BASE32[ch])
            bit = 0
            ch = 0
    return "".join(out)
