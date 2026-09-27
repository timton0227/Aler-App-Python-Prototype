"""The Streamlit page, run headless with Streamlit's own test runner (no browser).

These check that each tab runs and that its buttons do what they say. How the page
looks is checked by eye in a browser (see PROGRESS.md, Phase 10).
"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from alertmesh import reports, wire
from alertmesh.wire import HazardType, Severity

TIMEOUT = 30
# An absolute path: newer Streamlit resolves a relative one against this test file,
# older Streamlit against the current folder.
APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.run()
    assert not at.exception
    return at


def button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def fill_warning(at: AppTest) -> None:
    at.selectbox(key="c_hazard").set_value(HazardType.BUSHFIRE)
    at.radio(key="c_level").set_value(Severity.EMERGENCY_WARNING)
    at.text_input(key="c_headline").input("Bushfire near Katherine - leave now")
    at.text_area(key="c_action").input("Go to the evacuation centre on Giles Street.")
    at.run()
    button(at, "Cover the simulated town").click().run()


def send(at: AppTest, first: str = "Send warning…", confirm: str = "Send warning") -> None:
    button(at, first).click().run()
    button(at, confirm).click().run()
    assert not at.exception


# --- Console ---


def test_the_page_opens_on_the_console(app):
    assert [t.label for t in app.tabs][0] == "Warning console"
    assert app.session_state.world.minutes == 0
    assert button(app, "Send warning…").disabled  # an empty draft cannot be sent
    assert any("Write a headline." in m.value for m in app.markdown)


def test_writing_and_sending_a_warning(app):
    fill_warning(app)
    assert not button(app, "Send warning…").disabled
    send(app)

    world = app.session_state.world
    [alert] = world.live_warnings()
    assert alert.headline == "Bushfire near Katherine - leave now"
    assert alert.severity is Severity.EMERGENCY_WARNING
    assert list(alert.area_cells) == world.town_cells()
    assert wire.verify_pinned(alert)
    assert app.info[0].value.startswith("Sent: Bushfire near Katherine - leave now")
    assert app.session_state.c_headline == ""  # the form is cleared for the next warning


def test_back_does_not_send(app):
    fill_warning(app)
    button(app, "Send warning…").click().run()
    button(app, "Back").click().run()
    assert app.session_state.world.live_warnings() == []


def test_updating_a_live_warning(app):
    fill_warning(app)
    send(app)
    button(app, "Update…").click().run()
    assert app.session_state.c_headline == "Bushfire near Katherine - leave now"
    app.text_input(key="c_headline").input("Bushfire at Katherine - too late to leave").run()
    send(app, "Send update…", "Send update")

    [alert] = app.session_state.world.live_warnings()
    assert alert.headline == "Bushfire at Katherine - too late to leave"
    assert app.info[0].value.startswith("Update sent")


def test_cancelling_a_live_warning(app):
    fill_warning(app)
    send(app)
    button(app, "Cancel warning").click().run()
    button(app, "Keep it").click().run()
    assert len(app.session_state.world.live_warnings()) == 1
    button(app, "Cancel warning").click().run()
    next(b for b in app.button if (b.key or "").startswith("cancel_yes_")).click().run()
    assert app.session_state.world.live_warnings() == []
    assert app.info[0].value.startswith("Cancellation sent")


def test_offline_the_console_says_so(app):
    fill_warning(app)
    app.toggle(key="c_online").set_value(False).run()
    send(app)
    assert "not online: no relay" in app.info[0].value
    assert app.session_state.world.mesh.internet_feed == []


def test_time_passes_only_when_asked(app):
    button(app, "+5").click().run()
    assert app.session_state.world.minutes == 5


# --- Map ---


def test_the_map_waits_for_a_warning(app):
    assert [t.label for t in app.tabs][:2] == ["Warning console", "Map"]
    assert any("No warning yet" in i.value for i in app.info)


def test_the_map_shows_how_far_a_warning_has_got_and_plays_minutes(app):
    fill_warning(app)
    send(app)
    world = app.session_state.world
    [alert] = world.live_warnings()
    assert app.selectbox(key="m_alert").value == alert.alert_id
    phones = int(next(m for m in app.metric if m.label.startswith("Warned")).value)
    assert 0 < phones <= world.scenario.n_phones

    button(app, "Let 10 minutes pass and record them").click().run()
    assert not app.exception
    assert world.minutes == 10
    played_id, frames, _ = app.session_state.m_played
    assert played_id == alert.alert_id
    assert sorted(frames["minute"].unique()) == list(range(11))
    assert int(next(m for m in app.metric if m.label.startswith("Warned")).value) > phones


# --- Phone view ---


def chosen_phone(at: AppTest):
    return at.session_state.world.mesh.phones[at.selectbox(key="p_phone").value]


def test_the_phone_view_starts_on_a_phone_without_internet(app):
    assert "Phone view" in [t.label for t in app.tabs]
    assert not chosen_phone(app).has_internet
    assert any(m.value == "**No current warnings**" for m in app.markdown)


def test_a_phone_shows_the_warning_why_and_its_notification(app):
    fill_warning(app)
    send(app)
    button(app, "+5").click().run()
    phone = chosen_phone(app)
    assert phone.alert_store.live_alerts(), "the chosen phone should have heard it within 5 minutes"
    text = " ".join(m.value for m in app.markdown)
    assert "You are in this area" in text
    assert "**Loud now:** You are inside the warning area." in text
    assert "🔴 Emergency Warning · Bushfire" in text  # the notification it showed


def test_location_off_keeps_the_remembered_area(app):
    phone = chosen_phone(app)
    app.toggle(key=f"p_loc_{phone.id}").set_value(False).run()
    assert not phone.location_on and phone.geohash() is None
    assert phone.remembered_cell  # still loud for its own area
    assert any("Turn on location first" in c.value for c in app.caption)


def test_call_for_help_then_safe(app):
    phone = chosen_phone(app)
    app.text_input(key="p_sos_note").input("Car stuck at the causeway").run()
    button(app, "Send call for help").click().run()
    assert not app.exception
    [sos] = [r for r in phone.report_store.live_reports() if r.kind is reports.ReportKind.SOS]
    assert sos.note == "Car stuck at the causeway"
    assert any("Your call for help is out" in w.value for w in app.warning)

    button(app, "+5").click().run()
    holding = sum(any(r.report_id == sos.report_id for r in p.report_store.live_reports())
                  for p in app.session_state.world.phones())
    assert holding > 1
    # A phone that heard it shows the call for help as a notification, in plain words.
    told = next(p for p in app.session_state.world.phones() if p.report_notifications)
    app.selectbox(key="p_phone").set_value(told.id).run()
    assert any(f"{phone.id} needs help nearby" in m.value and "Car stuck at the causeway" in m.value
               for m in app.markdown)

    app.selectbox(key="p_phone").set_value(phone.id).run()
    button(app, "I'm safe now").click().run()
    assert [r.kind for r in phone.report_store.live_reports()] == [reports.ReportKind.SAFE]
    assert button(app, "Send call for help")  # the form is back


def test_a_hazard_report_is_not_a_warning(app):
    phone = chosen_phone(app)
    app.text_input(key="p_report_note").input("Causeway under water").run()
    button(app, "Send report").click().run()
    [report] = phone.report_store.live_reports()
    assert report.kind is reports.ReportKind.HAZARD and report.note == "Causeway under water"
    assert phone.alert_store.live_alerts() == []


# --- Hub board ---


def test_the_board_is_empty_then_shows_the_warning(app):
    assert "Hub board" in [t.label for t in app.tabs]
    assert any("No current warnings" in m.value for m in app.markdown)
    fill_warning(app)
    send(app)
    board = next(m.value for m in app.markdown if "Evacuation centre board" in m.value)
    assert "Emergency Warning · Bushfire" in board
    assert "Bushfire near Katherine - leave now" in board
