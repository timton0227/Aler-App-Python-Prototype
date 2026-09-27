"""Official warning format: build, sign-check and read warnings and cancellations.

Ported from: ../alert-mesh/AlertMesh/AlertMesh/Protocols/AlertPackets.swift
Contract:    ../alert-mesh/docs/ALERT-WIRE-FORMAT.md
Pinned key:  ../alert-mesh/AlertMesh/AlertMesh/Protocols/AlertPublisherKey.swift

Bytes produced here must match the Swift app exactly. A difference of one byte means
no warning ever verifies, and nothing says why. The tests check this module against
the frozen vectors from the app's own test suite.

This is free and unencumbered software released into the public domain.
"""
from enum import IntEnum

# --- Constants (AlertWireConstants) -------------------------------------------

ALERT_ID_LENGTH = 16
SIGNATURE_LENGTH = 64
HEADLINE_MAX_BYTES = 100
ACTION_TEXT_MAX_BYTES = 100
AREA_GEOHASH_MIN_LENGTH = 2
AREA_GEOHASH_MAX_LENGTH = 8
MAX_AREA_CELLS = 4
# One BLE frame: 469-byte fragment minus 14 header + 8 senderID + 64 packet signature.
BLE_FRAGMENT_SIZE = 469
PACKET_OVERHEAD = 14 + 8 + 64
MAX_ENCODED_BYTES = BLE_FRAGMENT_SIZE - PACKET_OVERHEAD
MAX_LIFETIME_MS = 7 * 24 * 60 * 60 * 1000
ALERT_SIGNING_CONTEXT = "alertmesh-official-v1"
CANCELLATION_SIGNING_CONTEXT = "alertmesh-cancel-v1"
GEOHASH_ALPHABET = frozenset("0123456789bcdefghjkmnpqrstuvwxyz")

# The key phones trust. Like a Swift DEBUG build, this pins the DEVELOPMENT key,
# whose private half is public in docs/ALERT-WIRE-FORMAT.md. Anyone can sign with it,
# so it must never be trusted by a real deployment.
PINNED_PUBLIC_KEY = bytes.fromhex("365182c9ee5be834763d712e7f0a26b0b6bbe77ed7e5c405e82b340acfdcf043")


class HazardType(IntEnum):
    """What kind of emergency. Wire values are frozen: add at the end, never renumber."""

    FLOOD = 0x01
    BUSHFIRE = 0x02
    STORM = 0x03
    FIRE_WEATHER = 0x04
    CYCLONE = 0x05
    HEATWAVE = 0x06


class Severity(IntEnum):
    """Australian warning levels, ordered so rules can say "at least Watch and Act".

    Wire values are frozen. An unknown severity rejects the whole warning.
    """

    ADVICE = 0x01
    WATCH_AND_ACT = 0x02
    EMERGENCY_WARNING = 0x03


class TLVType(IntEnum):
    """Field type bytes. 0x06 was the publisher key: retired, never reuse it."""

    KIND = 0x01
    ALERT_ID = 0x02
    AREA_GEOHASH = 0x03
    HEADLINE = 0x04
    ACTION_TEXT = 0x05
    ISSUED_AT = 0x07
    EXPIRES_AT = 0x08
    HAZARD_TYPE = 0x09
    SEVERITY = 0x0A
    SIGNATURE = 0x0B


class WireKind(IntEnum):
    ALERT = 0x01
    CANCELLATION = 0x02
