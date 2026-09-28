"""The warning console's signer: check a draft warning, then sign it.

Ported from: alert-mesh/AlertMesh/AlertMesh/Services/OfficialAlertSigning.swift
             (WarningDraft, OfficialAlertSigner)
and the version helper from OfficialAlertIssuer.swift (nextIssuedAt).

This is free and unencumbered software released into the public domain.
"""
import os
from dataclasses import dataclass, field
from enum import Enum

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from alertmesh import wire
from alertmesh.wire import AlertCancellation, HazardType, OfficialAlert, Severity

# DEVELOPMENT KEY ONLY. Its private half is published in docs/ALERT-WIRE-FORMAT.md on
# purpose, so anyone can reproduce the test vectors. Anyone can therefore forge a
# warning with it: it must never sign a real warning.
DEV_PRIVATE_KEY = bytes.fromhex("9077bd3b4bf110ba5c9bc7375e7e771d11597918ffa4a9ddc7a2f089a291f8cc")

HOUR_MS = 3_600_000
DURATION_RANGE = range(1, wire.MAX_LIFETIME_MS // HOUR_MS + 1)  # 1 to 168 hours


class Problem(Enum):
    """What stops a draft from being signed. Listed in the order the Swift code checks."""

    NO_HEADLINE = "noHeadline"
    HEADLINE_TOO_LONG = "headlineTooLong"
    NO_ACTION = "noAction"
    ACTION_TOO_LONG = "actionTooLong"
    NO_AREA = "noArea"
    TOO_MANY_CELLS = "tooManyCells"
    DURATION_OUT_OF_RANGE = "durationOutOfRange"


@dataclass
class WarningDraft:
    """A warning being written in the console, before it is signed."""

    hazard: HazardType = HazardType.FLOOD
    severity: Severity = Severity.WATCH_AND_ACT
    headline: str = ""
    action_text: str = ""
    duration_hours: int = 6
    area_cells: list[str] = field(default_factory=list)

    @classmethod
    def updating(cls, alert: OfficialAlert, now_ms: int) -> "WarningDraft":
        """A draft that starts from a live warning, for an update.

        The duration is what is left of the warning, rounded up to whole hours.
        """
        remaining = alert.expires_at - now_ms if alert.expires_at > now_ms else 0
        hours = (remaining + HOUR_MS - 1) // HOUR_MS
        return cls(
            hazard=alert.hazard or HazardType.FLOOD,
            severity=alert.severity,
            headline=alert.headline,
            action_text=alert.action_text,
            duration_hours=min(max(hours, DURATION_RANGE.start), DURATION_RANGE.stop - 1),
            area_cells=list(alert.area_cells),
        )

    @property
    def problems(self) -> list[Problem]:
        """Empty means ready to sign. Text limits count UTF-8 bytes, not letters."""
        headline = self.headline.strip()
        action = self.action_text.strip()
        problems = []
        if not headline:
            problems.append(Problem.NO_HEADLINE)
        if len(headline.encode()) > wire.HEADLINE_MAX_BYTES:
            problems.append(Problem.HEADLINE_TOO_LONG)
        if not action:
            problems.append(Problem.NO_ACTION)
        if len(action.encode()) > wire.ACTION_TEXT_MAX_BYTES:
            problems.append(Problem.ACTION_TOO_LONG)
        if not self.area_cells:
            problems.append(Problem.NO_AREA)
        if len(self.area_cells) > wire.MAX_AREA_CELLS:
            problems.append(Problem.TOO_MANY_CELLS)
        if self.duration_hours not in DURATION_RANGE:
            problems.append(Problem.DURATION_OUT_OF_RANGE)
        return problems


def new_alert_id() -> bytes:
    """A fresh 16-byte event ID, random like the Swift issuer's."""
    return os.urandom(wire.ALERT_ID_LENGTH)


def next_issued_at(now_ms: int, previous: int | None = None) -> int:
    """Now, but always later than `previous`: an equal stamp would be dropped as a duplicate."""
    return now_ms if previous is None else max(now_ms, previous + 1)


class OfficialAlertSigner:
    """Signs warnings and cancellations in the exact format phones verify."""

    def __init__(self, private_key: bytes = DEV_PRIVATE_KEY):
        self._key = Ed25519PrivateKey.from_private_bytes(private_key)

    @property
    def public_key(self) -> bytes:
        return self._key.public_key().public_bytes_raw()

    def sign(self, draft: WarningDraft, alert_id: bytes, issued_at: int) -> OfficialAlert | None:
        """Version `issued_at` of event `alert_id`. None when the draft has a problem:
        an unsigned draft can never leave."""
        if draft.problems:
            return None
        headline = draft.headline.strip()
        action = draft.action_text.strip()
        cells = tuple(c.lower() for c in draft.area_cells)
        expires_at = issued_at + draft.duration_hours * HOUR_MS
        signature = self._key.sign(
            wire.alert_signing_bytes(alert_id, draft.hazard, draft.severity, cells, headline, action, issued_at, expires_at)
        )
        return OfficialAlert(alert_id, int(draft.hazard), draft.severity, cells, headline, action, issued_at, expires_at, signature)

    def cancel(self, alert_id: bytes, issued_at: int) -> AlertCancellation:
        signature = self._key.sign(wire.cancellation_signing_bytes(alert_id, issued_at))
        return AlertCancellation(alert_id, issued_at, signature)
