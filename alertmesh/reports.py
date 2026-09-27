"""Community reports: hazard reports, SOS calls for help and "I'm safe" check-ins.

Ported from: ../alert-mesh/AlertMesh/AlertMesh/Protocols/CommunityReportPackets.swift
Contract:    ../alert-mesh/docs/ALERT-WIRE-FORMAT.md ("Community reports")

A report is something an ORDINARY PERSON says, signed with their own key. It is the
mirror image of an official warning: the author's key travels with the report, and
a valid signature proves only "whoever holds this key said this", never that it is
true. A report must never be shown as an official warning.

This is free and unencumbered software released into the public domain.
"""
import os
from dataclasses import dataclass
from enum import IntEnum

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from alertmesh.wire import (
    GEOHASH_ALPHABET, HazardType, _context, _ed25519_ok, _len16, _u64, _u64_from, _utf8, put_tlv, read_tlvs,
)

# --- Constants (CommunityReportWireConstants) ---------------------------------

REPORT_ID_LENGTH = 16
SIGNING_KEY_LENGTH = 32
SIGNATURE_LENGTH = 64
NOTE_MAX_BYTES = 140
NICKNAME_MAX_BYTES = 32
GEOHASH_MIN_LENGTH = 2
GEOHASH_MAX_LENGTH = 8
# SOS and "safe" stop at precision 7 (about 150 m): enough to be found, not enough
# to pinpoint a home. Enforced when reading, so a modified sender cannot go finer.
SOS_GEOHASH_MAX_LENGTH = 7
HAZARD_MAX_LIFETIME_MS = 24 * 60 * 60 * 1000
SOS_MAX_LIFETIME_MS = 6 * 60 * 60 * 1000
SIGNING_CONTEXT = "alertmesh-report-v1"
# The mesh message type that carries reports (Swift: MessageType.communityReport).
MESSAGE_TYPE = 0x2E


class ReportKind(IntEnum):
    """Wire values are frozen. Never renumber."""

    HAZARD = 0x01  # "There is a hazard here."
    SOS = 0x02     # "I need help."
    SAFE = 0x03    # "I'm safe." With an SOS's report ID, it answers that SOS.


class ReportSeverity(IntEnum):
    """How serious the AUTHOR thinks a hazard is.

    Deliberately not the official levels, and deliberately different words, so a
    report can never borrow the weight or colours of an official warning.
    Wire values are frozen.
    """

    LOW = 0x01
    MODERATE = 0x02
    HIGH = 0x03


class ReportTLVType(IntEnum):
    KIND = 0x01
    REPORT_ID = 0x02
    GEOHASH = 0x03
    HAZARD_TYPE = 0x04
    SEVERITY = 0x05
    NOTE = 0x06
    AUTHOR_SIGNING_KEY = 0x07
    AUTHOR_NICKNAME = 0x08
    CREATED_AT = 0x09
    EXPIRES_AT = 0x0A
    SIGNATURE = 0x0B


# --- The report ---------------------------------------------------------------


@dataclass(frozen=True)
class CommunityReport:
    """A user-signed hazard report, SOS or check-in (Swift: `CommunityReportPacket`).

    Times are milliseconds since 1970. A later report with the same `report_id` AND
    the same author replaces the earlier one; that is how "I'm safe" answers an SOS.
    """

    kind: ReportKind
    report_id: bytes
    geohash: str
    # Hazard byte as it arrived; 0 when the report carries none. Kept raw, like
    # OfficialAlert.hazard_code, so an unknown hazard survives and still verifies.
    hazard_code: int
    # Present on hazard reports; None on SOS and "safe".
    severity: ReportSeverity | None
    note: str
    author_signing_key: bytes
    author_nickname: str
    created_at: int
    expires_at: int
    signature: bytes

    @property
    def hazard(self) -> HazardType | None:
        try:
            return HazardType(self.hazard_code)
        except ValueError:
            return None


def report_signing_bytes(
    kind: int,
    report_id: bytes,
    geohash: str,
    hazard_code: int,
    severity: int | None,
    note: str,
    author_signing_key: bytes,
    author_nickname: str,
    created_at: int,
    expires_at: int,
) -> bytes:
    """The canonical bytes a report's signature covers.

    Unlike an official warning, the KIND is signed: one context covers all three
    kinds, so without it a captured SOS could be replayed as "I'm safe" by
    flipping one byte. A missing severity is signed as 0x00.
    """
    out = _context(SIGNING_CONTEXT) + bytes([int(kind)]) + report_id
    out += _len16(geohash.encode())
    out += bytes([hazard_code, 0 if severity is None else int(severity)])
    out += _len16(note.encode()) + author_signing_key + _len16(author_nickname.encode())
    return out + _u64(created_at) + _u64(expires_at)


def signing_bytes_of(report: CommunityReport) -> bytes:
    return report_signing_bytes(
        report.kind, report.report_id, report.geohash, report.hazard_code, report.severity,
        report.note, report.author_signing_key, report.author_nickname,
        report.created_at, report.expires_at,
    )


# --- Encode, decode, validate -------------------------------------------------

_KNOWN_TYPES = {t.value for t in ReportTLVType}


def encode(report: CommunityReport) -> bytes:
    """Wire bytes, fields in the Swift order. No hazard field when the code is 0;
    no severity field when there is none."""
    out = put_tlv(ReportTLVType.KIND, bytes([int(report.kind)]))
    out += put_tlv(ReportTLVType.REPORT_ID, report.report_id)
    out += put_tlv(ReportTLVType.GEOHASH, report.geohash.encode())
    if report.hazard_code != 0:
        out += put_tlv(ReportTLVType.HAZARD_TYPE, bytes([report.hazard_code]))
    if report.severity is not None:
        out += put_tlv(ReportTLVType.SEVERITY, bytes([int(report.severity)]))
    out += put_tlv(ReportTLVType.NOTE, report.note.encode())
    out += put_tlv(ReportTLVType.AUTHOR_SIGNING_KEY, report.author_signing_key)
    out += put_tlv(ReportTLVType.AUTHOR_NICKNAME, report.author_nickname.encode())
    out += put_tlv(ReportTLVType.CREATED_AT, _u64(report.created_at))
    out += put_tlv(ReportTLVType.EXPIRES_AT, _u64(report.expires_at))
    out += put_tlv(ReportTLVType.SIGNATURE, report.signature)
    return out


def is_valid_geohash(geohash: str) -> bool:
    """2 to 8 characters of the lowercase geohash alphabet. A report must say where."""
    return (
        GEOHASH_MIN_LENGTH <= len(geohash) <= GEOHASH_MAX_LENGTH
        and all(c in GEOHASH_ALPHABET for c in geohash)
    )


def decode(data: bytes) -> CommunityReport | None:
    """Read a report payload, or None if malformed.

    Structure only: call `verify()` before storing, showing or passing it on.
    """
    # No field may repeat, so the fast `kind_peek` (first copy) and this decoder
    # can never disagree.
    fields = read_tlvs(data, _KNOWN_TYPES)
    if fields is None:
        return None
    kind = report_id = geohash = note = key = nickname = created_at = expires_at = signature = None
    hazard_code = 0
    severity = None
    severity_seen = False
    for t, v in fields:
        if t == ReportTLVType.KIND:
            if len(v) != 1:
                return None
            kind = ReportKind(v[0]) if v[0] in ReportKind._value2member_map_ else None
        elif t == ReportTLVType.REPORT_ID:
            if len(v) != REPORT_ID_LENGTH:
                return None
            report_id = v
        elif t == ReportTLVType.GEOHASH:
            cell = _utf8(v)
            if len(v) > GEOHASH_MAX_LENGTH or cell is None or not is_valid_geohash(cell):
                return None
            geohash = cell
        elif t == ReportTLVType.HAZARD_TYPE:
            if len(v) != 1:
                return None
            hazard_code = v[0]  # any byte accepted, like official warnings
        elif t == ReportTLVType.SEVERITY:
            if len(v) != 1:
                return None
            severity_seen = True
            severity = ReportSeverity(v[0]) if v[0] in ReportSeverity._value2member_map_ else None
        elif t == ReportTLVType.NOTE:
            if len(v) > NOTE_MAX_BYTES:
                return None
            note = _utf8(v)
        elif t == ReportTLVType.AUTHOR_SIGNING_KEY:
            if len(v) != SIGNING_KEY_LENGTH:
                return None
            key = v
        elif t == ReportTLVType.AUTHOR_NICKNAME:
            if len(v) > NICKNAME_MAX_BYTES:
                return None
            nickname = _utf8(v)
        elif t == ReportTLVType.CREATED_AT:
            created_at = _u64_from(v)
        elif t == ReportTLVType.EXPIRES_AT:
            expires_at = _u64_from(v)
        elif t == ReportTLVType.SIGNATURE:
            if len(v) != SIGNATURE_LENGTH:
                return None
            signature = v
        # Unknown types: skipped, for forward compatibility.

    required = (kind, report_id, geohash, note, key, nickname, created_at, expires_at, signature)
    if any(x is None for x in required) or expires_at <= created_at:
        return None
    # A severity byte that names no known level is rejected, never guessed.
    # A severity that never arrived is fine for SOS and "safe".
    if severity_seen and severity is None:
        return None
    lifetime = expires_at - created_at
    if kind == ReportKind.HAZARD:
        if severity is None or lifetime > HAZARD_MAX_LIFETIME_MS:
            return None
    elif len(geohash) > SOS_GEOHASH_MAX_LENGTH or lifetime > SOS_MAX_LIFETIME_MS:
        # SOS and "safe": the precision cap is a privacy rule of the format itself.
        return None
    return CommunityReport(
        kind, report_id, geohash, hazard_code, severity, note, key, nickname,
        created_at, expires_at, signature,
    )


def kind_peek(data: bytes) -> ReportKind | None:
    """Fast look at the first kind field, so relays can favour an SOS without a full
    decode. None for garbage or an unknown kind; None must mean "not urgent"."""
    off = 0
    while off + 3 <= len(data):
        t = data[off]
        length = (data[off + 1] << 8) | data[off + 2]
        off += 3
        if off + length > len(data):
            return None
        if t == ReportTLVType.KIND and length == 1:
            return ReportKind(data[off]) if data[off] in ReportKind._value2member_map_ else None
        off += length
    return None


# --- Verify and supersede -----------------------------------------------------


def verify(report: CommunityReport) -> bool:
    """Does the signature match the key the report names as its author?

    The only check a report gets. It proves who said it, not that it is true.
    """
    return _ed25519_ok(report.signature, signing_bytes_of(report), report.author_signing_key)


def supersedes(new: CommunityReport, old: CommunityReport) -> bool:
    """True when `new` replaces `old`: same report ID, same author, strictly later.

    The author check is what makes "I'm safe" unforgeable: a stranger reusing your
    report ID is a different record, not a newer version of yours. Equal times do
    not supersede, so two copies of one report never fight.
    """
    return (
        new.report_id == old.report_id
        and new.author_signing_key == old.author_signing_key
        and new.created_at > old.created_at
    )


# --- Author: sign your own reports --------------------------------------------


class ReportAuthor:
    """One person's phone: holds their key and signs their reports.

    Ported from the signing part of CommunityReportManager.swift (`send`,
    `sendHazard`, `sendSOS`, `markSafe`). One person keeps ONE check-in record:
    a new SOS or "I'm safe" is a new version of their last one.
    """

    def __init__(self, nickname: str = "", private_key: bytes | None = None):
        self._key = Ed25519PrivateKey.from_private_bytes(private_key) if private_key else Ed25519PrivateKey.generate()
        self.nickname = nickname
        self.last_check_in: CommunityReport | None = None

    @property
    def public_key(self) -> bytes:
        return self._key.public_key().public_bytes_raw()

    def hazard(self, hazard: HazardType, severity: ReportSeverity, geohash: str, note: str, now_ms: int):
        return self._sign(ReportKind.HAZARD, None, geohash, int(hazard), severity, note, now_ms, HAZARD_MAX_LIFETIME_MS)

    def sos(self, geohash: str, note: str, now_ms: int):
        report = self._sign(ReportKind.SOS, self.last_check_in, geohash, 0, None, note, now_ms, SOS_MAX_LIFETIME_MS)
        if report:
            self.last_check_in = report
        return report

    def safe(self, geohash: str | None, note: str, now_ms: int):
        """With no location, answering an SOS falls back to where the SOS was sent from:
        being unable to call off your own call for help is far worse."""
        sos = self.last_check_in if self.last_check_in and self.last_check_in.kind == ReportKind.SOS else None
        place = geohash or (sos.geohash if sos else None)
        if place is None:
            return None
        report = self._sign(ReportKind.SAFE, self.last_check_in, place, 0, None, note, now_ms, SOS_MAX_LIFETIME_MS)
        if report:
            self.last_check_in = report
        return report

    def _sign(self, kind, replaces, geohash, hazard_code, severity, note, now_ms, lifetime_ms):
        note = note.strip()
        if len(note.encode()) > NOTE_MAX_BYTES:
            return None
        # SOS and "safe" are cut to precision 7 here so our own packets stay valid;
        # the decoder enforces the same cap as the real guarantee.
        cell = geohash[: GEOHASH_MAX_LENGTH if kind == ReportKind.HAZARD else SOS_GEOHASH_MAX_LENGTH]
        if len(cell) < GEOHASH_MIN_LENGTH:
            return None
        nickname = self.nickname
        while len(nickname.encode()) > NICKNAME_MAX_BYTES:
            nickname = nickname[:-1]
        report_id = replaces.report_id if replaces else os.urandom(REPORT_ID_LENGTH)
        # Supersession needs a STRICTLY later time. Step past the replaced version
        # rather than trust the millisecond clock to have moved.
        created_at = max(now_ms, replaces.created_at + 1) if replaces else now_ms
        expires_at = created_at + lifetime_ms
        key = self.public_key
        signature = self._key.sign(report_signing_bytes(
            kind, report_id, cell, hazard_code, severity, note, key, nickname, created_at, expires_at
        ))
        return CommunityReport(
            kind, report_id, cell, hazard_code, severity, note, key, nickname, created_at, expires_at, signature
        )
