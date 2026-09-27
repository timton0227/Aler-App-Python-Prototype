"""Words and colours the screens use, so the page says what the app says.

Ported from (English default strings and light-theme colours):
- ../alert-mesh/AlertMesh/AlertMesh/Services/AlertNotificationContent.swift (Strings.severity, Strings.hazard)
- ../alert-mesh/AlertMesh/AlertMesh/Views/AlertsView.swift (Strings.proximity, until text)
- ../alert-mesh/AlertMesh/AlertMesh/Views/AlertSeverityStyle.swift, ../alert-mesh/AlertMesh/Utils/Theme.swift
- ../alert-mesh/AlertMesh/AlertMesh/Views/CommunityReportStyle.swift (report kinds and severities)

This is free and unencumbered software released into the public domain.
"""
from datetime import datetime

from alertmesh.proximity import Decision, ReasonKind
from alertmesh.reports import ReportKind, ReportSeverity
from alertmesh.wire import HazardType, Severity

SEVERITY_NAMES = {
    Severity.ADVICE: "Advice",
    Severity.WATCH_AND_ACT: "Watch and Act",
    Severity.EMERGENCY_WARNING: "Emergency Warning",
}

HAZARD_NAMES = {
    HazardType.FLOOD: "Flood",
    HazardType.BUSHFIRE: "Bushfire",
    HazardType.STORM: "Storm",
    HazardType.FIRE_WEATHER: "Fire weather",
    HazardType.CYCLONE: "Cyclone",
    HazardType.HEATWAVE: "Heatwave",
}
# A hazard code this version does not know still shows as a warning (Swift: nil hazard).
UNKNOWN_HAZARD = "Official warning"

# The level as a fill: Advice yellow, Watch and Act orange, Emergency Warning red
# (ThemePalette.severityColor, light theme). Red is reserved for Emergency Warnings.
SEVERITY_FILL = {
    Severity.ADVICE: "#B88A00",
    Severity.WATCH_AND_ACT: "#D16600",
    Severity.EMERGENCY_WARNING: "#BF1A1A",
}
# What to draw on the fill (AlertSeverity.onFillColor): only the red is dark enough for white.
SEVERITY_ON_FILL = {
    Severity.ADVICE: "#000000",
    Severity.WATCH_AND_ACT: "#000000",
    Severity.EMERGENCY_WARNING: "#FFFFFF",
}
# The level as text on a plain background (ThemePalette.severityTextColor, light theme).
SEVERITY_TEXT = {
    Severity.ADVICE: "#8A6200",
    Severity.WATCH_AND_ACT: "#9A3D00",
    Severity.EMERGENCY_WARNING: "#B01414",
}

REPORT_KIND_NAMES = {
    ReportKind.HAZARD: "Hazard",
    ReportKind.SOS: "Needs help",
    ReportKind.SAFE: "Safe",
}

# Deliberately not the official level names, so a report never borrows their weight.
REPORT_SEVERITY_NAMES = {
    ReportSeverity.LOW: "Minor",
    ReportSeverity.MODERATE: "Serious",
    ReportSeverity.HIGH: "Dangerous",
}


def hazard_name(hazard: HazardType | None) -> str:
    return HAZARD_NAMES.get(hazard, UNKNOWN_HAZARD)


def title(alert) -> str:
    """ "Emergency Warning · Bushfire", as a notification title and alert card show it."""
    return f"{SEVERITY_NAMES[alert.severity]} · {hazard_name(alert.hazard)}"


def proximity(decision: Decision) -> str:
    """The short line on a warning saying how close it is (AlertsView.Strings.proximity)."""
    kind = decision.reason.kind
    if kind in (ReasonKind.INSIDE_AREA, ReasonKind.WATCHED_PLACE_INSIDE_AREA):
        return "You are in this area"
    # A remembered area is only ever "near": the person may have moved.
    if kind in (ReasonKind.ADJACENT_TO_AREA, ReasonKind.WATCHED_PLACE_NEAR_AREA, ReasonKind.LAST_KNOWN_AREA):
        return "Near you"
    if kind is ReasonKind.OUTSIDE_AREA:
        return "Another area"
    return "Location unknown"


def clock(ms: int) -> str:
    """A time of day, as the hub board's clock shows it. Uses this computer's time zone."""
    return datetime.fromtimestamp(ms / 1000).strftime("%H:%M")


def until(expires_at: int, now_ms: int) -> str:
    """ "Until 14:30" on the same day, with the date on a later day (AlertsView.untilText)."""
    end, now = datetime.fromtimestamp(expires_at / 1000), datetime.fromtimestamp(now_ms / 1000)
    return "Until " + (end.strftime("%H:%M") if end.date() == now.date() else end.strftime("%d %b %H:%M"))
