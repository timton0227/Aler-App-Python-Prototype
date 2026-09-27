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

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

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


# --- Encode -------------------------------------------------------------------


def encode_alert(alert: OfficialAlert) -> bytes:
    """The warning as wire bytes, fields in the same order as the Swift encoder."""
    out = put_tlv(TLVType.KIND, bytes([WireKind.ALERT]))
    out += put_tlv(TLVType.ALERT_ID, alert.alert_id)
    for cell in alert.area_cells:
        out += put_tlv(TLVType.AREA_GEOHASH, cell.encode())
    out += put_tlv(TLVType.HEADLINE, alert.headline.encode())
    out += put_tlv(TLVType.ACTION_TEXT, alert.action_text.encode())
    out += put_tlv(TLVType.ISSUED_AT, _u64(alert.issued_at))
    out += put_tlv(TLVType.EXPIRES_AT, _u64(alert.expires_at))
    out += put_tlv(TLVType.HAZARD_TYPE, bytes([alert.hazard_code]))
    out += put_tlv(TLVType.SEVERITY, bytes([int(alert.severity)]))
    out += put_tlv(TLVType.SIGNATURE, alert.signature)
    return out


# --- Cancellation (kind 0x02) ------------------------------------------------


@dataclass(frozen=True)
class AlertCancellation:
    """A signed withdrawal of a warning (Swift: `AlertCancellationPacket`).

    Signed under its own context, so a warning's signature can never make a valid
    cancellation, nor the reverse. `issued_at` must be later than the version it
    withdraws; a later warning version with the same ID reinstates it.
    """

    alert_id: bytes
    issued_at: int
    signature: bytes


def cancellation_signing_bytes(alert_id: bytes, issued_at: int) -> bytes:
    return _context(CANCELLATION_SIGNING_CONTEXT) + alert_id + _u64(issued_at)


def encode_cancellation(cancellation: AlertCancellation) -> bytes:
    out = put_tlv(TLVType.KIND, bytes([WireKind.CANCELLATION]))
    out += put_tlv(TLVType.ALERT_ID, cancellation.alert_id)
    out += put_tlv(TLVType.ISSUED_AT, _u64(cancellation.issued_at))
    out += put_tlv(TLVType.SIGNATURE, cancellation.signature)
    return out


def encode(item) -> bytes:
    """Wire bytes for a warning or a cancellation."""
    if isinstance(item, AlertCancellation):
        return encode_cancellation(item)
    return encode_alert(item)


# --- Decode and verify --------------------------------------------------------

_KNOWN_TYPES = {t.value for t in TLVType}
_REPEATABLE = frozenset({TLVType.AREA_GEOHASH.value})


def _u64_from(value: bytes) -> int | None:
    return int.from_bytes(value, "big") if len(value) == 8 else None


def _utf8(value: bytes) -> str | None:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return None


def decode(data: bytes):
    """Read a payload. Returns an `OfficialAlert`, an `AlertCancellation`, or None.

    Structure only: a successful decode says NOTHING about who made it. Call
    `verify_pinned()` before storing, showing or passing it on.
    """
    fields = read_tlvs(data, _KNOWN_TYPES, _REPEATABLE)
    if fields is None:
        return None
    kind = alert_id = headline = action_text = issued_at = expires_at = None
    hazard_code = severity = signature = None
    headline_bytes = 0
    area_cells: list[str] = []
    for t, v in fields:
        if t == TLVType.KIND:
            if len(v) != 1:
                return None
            kind = v[0] if v[0] in (WireKind.ALERT, WireKind.CANCELLATION) else None
        elif t == TLVType.ALERT_ID:
            if len(v) != ALERT_ID_LENGTH:
                return None
            alert_id = v
        elif t == TLVType.AREA_GEOHASH:
            # Checked as it arrives, so thousands of cells are refused early.
            cell = _utf8(v)
            if len(area_cells) >= MAX_AREA_CELLS or cell is None or not is_valid_area_cell(cell):
                return None
            area_cells.append(cell)
        elif t == TLVType.HEADLINE:
            if len(v) > HEADLINE_MAX_BYTES:
                return None
            headline_bytes = len(v)
            headline = _utf8(v)
        elif t == TLVType.ACTION_TEXT:
            if len(v) > ACTION_TEXT_MAX_BYTES:
                return None
            action_text = _utf8(v)
        elif t == TLVType.ISSUED_AT:
            issued_at = _u64_from(v)
        elif t == TLVType.EXPIRES_AT:
            expires_at = _u64_from(v)
        elif t == TLVType.HAZARD_TYPE:
            if len(v) != 1:
                return None
            hazard_code = v[0]  # any byte is accepted; see OfficialAlert.hazard_code
        elif t == TLVType.SEVERITY:
            if len(v) != 1:
                return None
            severity = Severity(v[0]) if v[0] in Severity._value2member_map_ else None
        elif t == TLVType.SIGNATURE:
            if len(v) != SIGNATURE_LENGTH:
                return None
            signature = v
        # Unknown types: skipped, for forward compatibility.

    if kind == WireKind.ALERT:
        # An unknown severity decoded to None above and is rejected here, never
        # defaulted: guessing could show an Emergency Warning as an Advice.
        required = (alert_id, headline, action_text, issued_at, expires_at, hazard_code, severity, signature)
        if any(x is None for x in required):
            return None
        if not alert_fields_are_valid(
            area_cells, headline_bytes, len(action_text.encode()), issued_at, expires_at
        ):
            return None
        return OfficialAlert(
            alert_id, hazard_code, severity, tuple(area_cells), headline, action_text,
            issued_at, expires_at, signature,
        )
    if kind == WireKind.CANCELLATION:
        # Any other fields are ignored: the cancellation signature does not cover
        # them, so nothing may be read from them.
        if alert_id is None or issued_at is None or signature is None:
            return None
        return AlertCancellation(alert_id, issued_at, signature)
    return None


def _ed25519_ok(signature: bytes, message: bytes, public_key: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
        return True
    except (InvalidSignature, ValueError):
        return False


def verify(item, public_key: bytes) -> bool:
    """Signature check against a given key. Tests use this with a throwaway key.

    Real code wants `verify_pinned()`: checking against a key that arrived with the
    packet proves nothing, because anyone can sign their own forgery.
    """
    if isinstance(item, OfficialAlert):
        return _ed25519_ok(item.signature, signing_bytes_of(item), public_key)
    if isinstance(item, AlertCancellation):
        return _ed25519_ok(item.signature, cancellation_signing_bytes(item.alert_id, item.issued_at), public_key)
    return False


def verify_pinned(item) -> bool:
    """The only check that makes a warning official."""
    return verify(item, PINNED_PUBLIC_KEY)


def severity_peek(data: bytes) -> Severity | None:
    """Fast look at the first severity field, for relay priority, without a full decode.

    None for garbage or an unknown value. None must be treated as "not urgent": an
    unverified peek must never RAISE a packet's priority.
    """
    off = 0
    while off + 3 <= len(data):
        t = data[off]
        length = (data[off + 1] << 8) | data[off + 2]
        off += 3
        if off + length > len(data):
            return None
        if t == TLVType.SEVERITY and length == 1:
            return Severity(data[off]) if data[off] in Severity._value2member_map_ else None
        off += length
    return None
