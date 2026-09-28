"""Geohash: turns a latitude and longitude into a short area code, and back.

Ported from: alert-mesh/AlertMesh/Protocols/Geohash.swift (enum Geohash).

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


def decode_bounds(geohash: str) -> tuple[float, float, float, float]:
    """The cell's box as (lat_min, lat_max, lon_min, lon_max).

    Characters outside the alphabet are skipped, like the Swift `decodeBounds`.
    """
    lat_lo, lat_hi = -90.0, 90.0
    lon_lo, lon_hi = -180.0, 180.0
    is_even = True
    for c in geohash.lower():
        cd = _BASE32_MAP.get(c)
        if cd is None:
            continue
        for mask in (16, 8, 4, 2, 1):
            if is_even:
                mid = (lon_lo + lon_hi) / 2
                if cd & mask:
                    lon_lo = mid
                else:
                    lon_hi = mid
            else:
                mid = (lat_lo + lat_hi) / 2
                if cd & mask:
                    lat_lo = mid
                else:
                    lat_hi = mid
            is_even = not is_even
    return lat_lo, lat_hi, lon_lo, lon_hi


def decode_center(geohash: str) -> tuple[float, float]:
    """The centre of the cell's box, as (lat, lon)."""
    lat_lo, lat_hi, lon_lo, lon_hi = decode_bounds(geohash)
    return (lat_lo + lat_hi) / 2, (lon_lo + lon_hi) / 2


def neighbors(geohash: str) -> list[str]:
    """The cells around this one, at the same precision, in N, NE, E, SE, S, SW, W, NW order.

    Longitude wraps at ±180. A neighbour past a pole is left out, so a cell near a
    pole has fewer than 8 neighbours, like the Swift `neighbors(of:)`.
    """
    if not geohash:
        return []
    precision = len(geohash)
    lat_lo, lat_hi, lon_lo, lon_hi = decode_bounds(geohash)
    lat, lon = decode_center(geohash)
    height = lat_hi - lat_lo
    width = lon_hi - lon_lo

    def wrap(value: float) -> float:
        while value > 180.0:
            value -= 360.0
        while value < -180.0:
            value += 360.0
        return value

    centres = [
        (lat + height, lon),          # N
        (lat + height, lon + width),  # NE
        (lat, lon + width),           # E
        (lat - height, lon + width),  # SE
        (lat - height, lon),          # S
        (lat - height, lon - width),  # SW
        (lat, lon - width),           # W
        (lat + height, lon - width),  # NW
    ]
    return [
        encode(max(-90.0, min(90.0, n_lat)), wrap(n_lon), precision)
        for n_lat, n_lon in centres
        if -90.0 <= n_lat <= 90.0
    ]
