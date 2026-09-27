"""Community reports: hazard reports, SOS calls for help and "I'm safe" check-ins.

Ported from: ../alert-mesh/AlertMesh/AlertMesh/Protocols/CommunityReportPackets.swift
Contract:    ../alert-mesh/docs/ALERT-WIRE-FORMAT.md ("Community reports")

A report is something an ORDINARY PERSON says, signed with their own key. It is the
mirror image of an official warning: the author's key travels with the report, and
a valid signature proves only "whoever holds this key said this", never that it is
true. A report must never be shown as an official warning.

This is free and unencumbered software released into the public domain.
"""
from enum import IntEnum

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
