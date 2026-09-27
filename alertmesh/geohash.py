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
