"""What notifications say.

Ported from:
- ../alert-mesh/AlertMeshTests/AlertMesh/Services/AlertNotificationContentTests.swift
  (all but the notification identifier, which the prototype has no use for)
- the content tests in ../alert-mesh/AlertMeshTests/AlertMesh/Services/SOSNotificationsModelTests.swift
"""
import pytest

from alertmesh import labels
from alertmesh.notifications import (SEVERITY_EMOJI, Level, Whereabouts, alert_content, sos_content,
                                     whereabouts)
from alertmesh.proximity import ReasonKind, Urgency
from alertmesh.reports import CommunityReport, ReportKind
from alertmesh.wire import HazardType, OfficialAlert, Severity


def alert(severity=Severity.WATCH_AND_ACT, hazard_code=HazardType.BUSHFIRE,
          headline="Bushfire at Mount Barker - leave now", action_text="Travel north on Highway 1.",
          issued_at=1_700_000_000_000) -> OfficialAlert:
    return OfficialAlert(bytes([0xAB]) * 16, int(hazard_code), severity, ("r7hg",), headline, action_text,
                         issued_at, issued_at + 3_600_000, bytes(64))


def test_full_content_names_level_hazard_headline_and_action():
    content = alert_content(alert(), Urgency.QUIET, Whereabouts.YOUR_AREA)
    assert content.title == "🟠 Watch and Act · Bushfire"
    assert content.body == "Bushfire at Mount Barker - leave now\nTravel north on Highway 1."
    assert content.level is Level.ACTIVE
    assert not content.overrides_privacy


def test_empty_action_text_leaves_just_the_headline():
    assert alert_content(alert(action_text=""), Urgency.QUIET, Whereabouts.YOUR_AREA).body == \
        "Bushfire at Mount Barker - leave now"


def test_loud_asks_for_time_sensitive():
    assert alert_content(alert(), Urgency.LOUD, Whereabouts.YOUR_AREA).level is Level.TIME_SENSITIVE


@pytest.mark.parametrize("severity", [Severity.ADVICE, Severity.WATCH_AND_ACT])
def test_lower_severities_honour_hidden_previews(severity):
    content = alert_content(alert(severity), Urgency.LOUD, Whereabouts.YOUR_AREA, hide_previews=True)
    assert content.title == "⚠️ Official warning for your area"
    assert content.body == "Open the app for details"
    assert "Mount Barker" not in content.body and "Bushfire" not in content.title
    assert not content.overrides_privacy


def test_another_area_leads_the_body_and_keeps_the_title():
    content = alert_content(alert(), Urgency.QUIET, Whereabouts.ANOTHER_AREA)
    assert content.title == "🟠 Watch and Act · Bushfire"
    assert content.body == "For another area\nBushfire at Mount Barker - leave now\nTravel north on Highway 1."


def test_far_away_emergency_warning_overrides_privacy_but_says_it_is_elsewhere():
    content = alert_content(alert(Severity.EMERGENCY_WARNING), Urgency.QUIET, Whereabouts.ANOTHER_AREA,
                            hide_previews=True)
    assert content.overrides_privacy
    assert content.body.startswith("For another area\n")


def test_hidden_titles_never_claim_your_area_for_somewhere_else():
    elsewhere = alert_content(alert(Severity.ADVICE), Urgency.QUIET, Whereabouts.ANOTHER_AREA, hide_previews=True)
    unknown = alert_content(alert(Severity.ADVICE), Urgency.QUIET, Whereabouts.UNKNOWN, hide_previews=True)
    assert elsewhere.title == "⚠️ Official warning for another area"
    assert unknown.title == "⚠️ Official warning"
    assert elsewhere.body == "Open the app for details"


def test_whereabouts_follow_the_proximity_reason():
    your_area = [ReasonKind.INSIDE_AREA, ReasonKind.ADJACENT_TO_AREA, ReasonKind.WATCHED_PLACE_INSIDE_AREA,
                 ReasonKind.WATCHED_PLACE_NEAR_AREA, ReasonKind.LAST_KNOWN_AREA]
    for kind in your_area:
        assert whereabouts(kind) is Whereabouts.YOUR_AREA
    assert whereabouts(ReasonKind.OUTSIDE_AREA) is Whereabouts.ANOTHER_AREA
    assert whereabouts(ReasonKind.LOCATION_UNKNOWN) is Whereabouts.UNKNOWN


def test_emergency_warning_overrides_hidden_previews():
    content = alert_content(alert(Severity.EMERGENCY_WARNING), Urgency.LOUD, Whereabouts.YOUR_AREA,
                            hide_previews=True)
    assert content.title == "🔴 Emergency Warning · Bushfire"
    assert "Mount Barker" in content.body
    assert content.overrides_privacy


def test_emergency_warning_with_previews_shown_is_not_an_override():
    content = alert_content(alert(Severity.EMERGENCY_WARNING), Urgency.LOUD, Whereabouts.YOUR_AREA)
    assert not content.overrides_privacy


def test_unknown_hazard_is_shown_generically():
    content = alert_content(alert(hazard_code=0x7E), Urgency.QUIET, Whereabouts.YOUR_AREA)
    assert content.title == "🟠 Watch and Act · Official warning"


def test_red_is_reserved_for_emergency_warning():
    assert SEVERITY_EMOJI[Severity.EMERGENCY_WARNING] == "🔴"
    assert "🔴" not in (SEVERITY_EMOJI[Severity.WATCH_AND_ACT], SEVERITY_EMOJI[Severity.ADVICE])


# --- Someone else's call for help ---


def report(kind=ReportKind.SOS, nickname="sam", note="Trapped on roof at 12 Smith St") -> CommunityReport:
    return CommunityReport(kind, bytes(16), "r7hg5x2", 0, None, note, bytes(32), nickname, 1, 2, bytes(64))


def test_hidden_previews_never_show_who_or_what():
    hidden = sos_content(report(), Urgency.LOUD, hide_previews=True)
    shown = sos_content(report(), Urgency.LOUD)
    assert "sam" not in hidden.title and "Smith" not in hidden.body
    assert "sam" in shown.title and "Smith" in shown.body
    assert hidden.level is Level.TIME_SENSITIVE


def test_safe_says_who_is_safe_and_is_never_time_sensitive():
    safe = sos_content(report(ReportKind.SAFE, note=""), Urgency.LOUD)
    assert safe.title == "sam is safe"
    assert safe.body == "They sent “I’m safe”."
    assert safe.level is Level.ACTIVE
    assert sos_content(report(ReportKind.SAFE, nickname=" "), Urgency.QUIET).title == \
        "Someone who asked for help is safe"


def test_wording_never_borrows_official_warning_levels():
    """A neighbour's call for help must never read as an official warning."""
    sos = sos_content(report(), Urgency.LOUD)
    for level in labels.SEVERITY_NAMES.values():
        assert level not in sos.title and level not in sos.body
    for symbol in ["🔴", "🟠", "🟡", "⚠️"]:
        assert symbol not in sos.title
