"""Official warning format: build, sign-check and read warnings and cancellations.

Ported from: ../alert-mesh/AlertMesh/AlertMesh/Protocols/AlertPackets.swift
Contract:    ../alert-mesh/docs/ALERT-WIRE-FORMAT.md
Pinned key:  ../alert-mesh/AlertMesh/AlertMesh/Protocols/AlertPublisherKey.swift

Bytes produced here must match the Swift app exactly. A difference of one byte means
no warning ever verifies, and nothing says why. The tests check this module against
the frozen vectors from the app's own test suite.

This is free and unencumbered software released into the public domain.
"""
from dataclasses import dataclass
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


# --- TLV fields: type (1 byte) | length (2 bytes, big-endian) | value ----------


def put_tlv(tlv_type: int, value: bytes) -> bytes:
    """One field, ready to append to a payload."""
    return bytes([tlv_type]) + len(value).to_bytes(2, "big") + value


def read_tlvs(
    data: bytes, known_types: set[int], repeatable: frozenset[int] = frozenset()
) -> list[tuple[int, bytes]] | None:
    """Split a payload into (type, value) fields, or None if it is malformed.

    Follows the Swift decode loop exactly:
    - a field whose length runs past the end rejects the payload;
    - one or two stray bytes at the very end are ignored (too short to be a field);
    - a known type that appears twice rejects the payload, except the `repeatable`
      ones. Last-wins would let the fast relay-path severity peek (first copy) and
      the full decode (last copy) disagree, and buy a forged warning extra hops;
    - unknown types are returned too; callers skip them (forward compatibility).
    """
    fields = []
    seen = set()
    off = 0
    while off + 3 <= len(data):
        t = data[off]
        length = (data[off + 1] << 8) | data[off + 2]
        off += 3
        if off + length > len(data):
            return None
        if t in known_types and t not in repeatable:
            if t in seen:
                return None
            seen.add(t)
        fields.append((t, bytes(data[off : off + length])))
        off += length
    return fields


# --- Official warning ---------------------------------------------------------


@dataclass(frozen=True)
class OfficialAlert:
    """A warning signed by the publisher (Swift: `OfficialAlertPacket`).

    `alert_id` names the EVENT; `issued_at` is the version. An update to the same
    warning keeps the ID and has a later `issued_at`. Times are milliseconds since
    1970, as on the wire.
    """

    alert_id: bytes
    # The hazard byte exactly as it arrived. Kept raw because the signature covers
    # it, and because a warning for a hazard this version does not know must still
    # be shown. Read `hazard` for the typed view; None means "show generically".
    hazard_code: int
    severity: Severity
    area_cells: tuple[str, ...]
    headline: str
    action_text: str
    issued_at: int
    expires_at: int
    signature: bytes

    @property
    def hazard(self) -> HazardType | None:
        try:
            return HazardType(self.hazard_code)
        except ValueError:
            return None


def is_valid_area_cell(cell: str) -> bool:
    """2 to 8 characters, all from the lowercase geohash alphabet.

    Unlike the general geohash check, upper case is NOT accepted: the signature
    covers the exact bytes, so the app only accepts the canonical lowercase form.
    """
    return (
        AREA_GEOHASH_MIN_LENGTH <= len(cell) <= AREA_GEOHASH_MAX_LENGTH
        and all(c in GEOHASH_ALPHABET for c in cell)
    )


def alert_fields_are_valid(
    area_cells, headline_bytes: int, action_bytes: int, issued_at: int, expires_at: int
) -> bool:
    """The receipt rules from `AlertWire.decode`, apart from the signature.

    - 1 to 4 area cells, each valid;
    - headline 1 to 100 bytes, action text 0 to 100 bytes;
    - expires after it is issued, and lives at most 7 days.
    """
    return (
        1 <= len(area_cells) <= MAX_AREA_CELLS
        and all(is_valid_area_cell(c) for c in area_cells)
        and 1 <= headline_bytes <= HEADLINE_MAX_BYTES
        and 0 <= action_bytes <= ACTION_TEXT_MAX_BYTES
        and expires_at > issued_at
        and expires_at - issued_at <= MAX_LIFETIME_MS
    )


# --- Signing bytes (what the Ed25519 signature covers) -------------------------


def _context(name: str) -> bytes:
    """Length byte, then the UTF-8 context (Swift: `BoardWireEncoding.appendContext`)."""
    raw = name.encode()[:255]
    return bytes([len(raw)]) + raw


def _len16(value: bytes) -> bytes:
    """2-byte big-endian length, then the value (Swift: `appendLengthPrefixed`)."""
    value = value[:0xFFFF]
    return len(value).to_bytes(2, "big") + value


def _u64(value: int) -> bytes:
    return value.to_bytes(8, "big")


def alert_signing_bytes(
    alert_id: bytes,
    hazard_code: int,
    severity: int,
    area_cells,
    headline: str,
    action_text: str,
    issued_at: int,
    expires_at: int,
) -> bytes:
    """The canonical bytes a warning's signature covers. NOT the TLV encoding.

    Every variable field is length-prefixed and the cell list is count-prefixed,
    so nobody can move bytes between headline and action, or add an area cell,
    and keep the signature valid.
    """
    out = _context(ALERT_SIGNING_CONTEXT) + alert_id
    out += bytes([hazard_code, int(severity), min(len(area_cells), 255)])
    for cell in area_cells:
        out += _len16(cell.encode())
    out += _len16(headline.encode()) + _len16(action_text.encode())
    return out + _u64(issued_at) + _u64(expires_at)


def signing_bytes_of(alert: OfficialAlert) -> bytes:
    return alert_signing_bytes(
        alert.alert_id, alert.hazard_code, alert.severity, alert.area_cells,
        alert.headline, alert.action_text, alert.issued_at, alert.expires_at,
    )
