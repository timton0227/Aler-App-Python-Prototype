"""What a notification says: the title and body a phone shows.

Ported from:
- ../alert-mesh/AlertMesh/AlertMesh/Services/AlertNotificationContent.swift
  (make, Whereabouts, severity emoji)
- ../alert-mesh/AlertMesh/AlertMesh/Services/SOSNotificationContent.swift (make)

When a notification is shown, and how loud, is decided elsewhere (`proximity` and
`mesh_sim.Phone.evaluate`). This module only says what it reads.

This is free and unencumbered software released into the public domain.
"""
from dataclasses import dataclass
from enum import Enum

from alertmesh import labels
from alertmesh.proximity import ReasonKind, Urgency
from alertmesh.reports import CommunityReport, ReportKind
from alertmesh.wire import OfficialAlert, Severity


class Whereabouts(Enum):
    """Where the warning is, as far as the words on a notification go."""

    YOUR_AREA = "yourArea"
    ANOTHER_AREA = "anotherArea"
    UNKNOWN = "unknown"


def whereabouts(kind: ReasonKind) -> Whereabouts:
    if kind is ReasonKind.OUTSIDE_AREA:
        return Whereabouts.ANOTHER_AREA
    if kind is ReasonKind.LOCATION_UNKNOWN:
        return Whereabouts.UNKNOWN
    # Inside, next to, a watched place, or the remembered area: all "your area".
    return Whereabouts.YOUR_AREA


class Level(Enum):
    """How hard the notification asks for attention (UNNotificationInterruptionLevel).
    Time-sensitive is what "loud" asks for; iOS may still downgrade it."""

    ACTIVE = "active"
    TIME_SENSITIVE = "timeSensitive"


@dataclass(frozen=True)
class Content:
    title: str
    body: str
    level: Level
    # True only when an Emergency Warning shows in full although previews are hidden.
    overrides_privacy: bool = False


# Red is reserved for the Emergency Warning.
SEVERITY_EMOJI = {
    Severity.ADVICE: "🟡",
    Severity.WATCH_AND_ACT: "🟠",
    Severity.EMERGENCY_WARNING: "🔴",
}

ANOTHER_AREA = "For another area"
_REDACTED_TITLE = {
    Whereabouts.YOUR_AREA: "⚠️ Official warning for your area",
    Whereabouts.ANOTHER_AREA: "⚠️ Official warning for another area",
    Whereabouts.UNKNOWN: "⚠️ Official warning",
}
_REDACTED_BODY = "Open the app for details"


def alert_content(alert: OfficialAlert, urgency: Urgency, where: Whereabouts,
                  hide_previews: bool = False) -> Content:
    """An official warning's notification. With previews hidden, only an Emergency
    Warning still shows its words: the deliberate, narrow exception."""
    level = Level.TIME_SENSITIVE if urgency is Urgency.LOUD else Level.ACTIVE
    if hide_previews and alert.severity is not Severity.EMERGENCY_WARNING:
        return Content(_REDACTED_TITLE[where], _REDACTED_BODY, level)
    lines = [alert.headline]
    if alert.action_text:
        lines.append(alert.action_text)
    if where is Whereabouts.ANOTHER_AREA:
        lines.insert(0, ANOTHER_AREA)
    title = f"{SEVERITY_EMOJI[alert.severity]} {labels.title(alert)}"
    return Content(title, "\n".join(lines), level, overrides_privacy=hide_previews)


def sos_content(report: CommunityReport, urgency: Urgency, hide_previews: bool = False) -> Content:
    """Someone else's call for help, or their "I'm safe". Plain words: a neighbour's
    call for help must never read like an official warning."""
    level = Level.TIME_SENSITIVE if urgency is Urgency.LOUD else Level.ACTIVE
    nickname = report.author_nickname.strip()
    note = report.note.strip()
    shows_detail = not hide_previews and bool(nickname)
    body_note = note if not hide_previews and note else None
    if report.kind is ReportKind.SAFE:
        title = f"{nickname} is safe" if shows_detail else "Someone who asked for help is safe"
        return Content(title, body_note or "They sent “I’m safe”.", Level.ACTIVE)
    title = f"{nickname} needs help nearby" if shows_detail else "Someone nearby needs help"
    return Content(title, body_note or "Tap to see where. If you can reach 000, call them first.", level)
