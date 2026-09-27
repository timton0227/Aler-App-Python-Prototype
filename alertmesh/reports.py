"""Community reports: hazard reports, SOS calls for help and "I'm safe" check-ins.

Ported from: ../alert-mesh/AlertMesh/AlertMesh/Protocols/CommunityReportPackets.swift
Contract:    ../alert-mesh/docs/ALERT-WIRE-FORMAT.md ("Community reports")

A report is something an ORDINARY PERSON says, signed with their own key. It is the
mirror image of an official warning: the author's key travels with the report, and
a valid signature proves only "whoever holds this key said this", never that it is
true. A report must never be shown as an official warning.

This is free and unencumbered software released into the public domain.
"""
from dataclasses import dataclass
from enum import IntEnum

from alertmesh.wire import HazardType, _context, _len16, _u64

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
