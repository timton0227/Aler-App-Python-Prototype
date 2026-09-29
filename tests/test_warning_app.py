"""The warning app's page, run headless with Streamlit's own test runner (no browser).

These check that each tab runs and that its buttons do what they say. How the page
looks is checked by eye in a browser (see PROGRESS.md, Phase 10).
"""
import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from alertmesh import lan, wire
from alertmesh.wire import HazardType, Severity

TIMEOUT = 30
# An absolute path: newer Streamlit resolves a relative one against this test file,
# older Streamlit against the current folder.
APP = str(Path(__file__).resolve().parent.parent / "warning_app.py")


@pytest.fixture
def app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.run()
    assert not at.exception
    return at


def button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def show(at: AppTest, view: str) -> None:
    at.button(key="nav_" + view.lower().replace(" ", "_")).click().run()
    assert not at.exception and at.session_state["view"] == view


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
    assert [b.key for b in app.sidebar.button if b.key.startswith("nav_")] == [
        "nav_warning_console", "nav_map", "nav_hub_board"]
    assert app.session_state["view"] == "Warning console"
    assert 'class="am-statusbar"' in " ".join(m.value for m in app.markdown)  # on or off, it says which
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
    assert "minute 5" in " ".join(m.value for m in app.sidebar.markdown)


def test_the_preview_shows_the_block_phones_in_the_area_show(app):
    fill_warning(app)
    shown = " ".join(m.value for m in app.markdown)
    assert 'class="am-block am-fill-e"' in shown and "Bushfire near Katherine - leave now" in shown
    assert "Go to the evacuation centre on Giles Street." in shown


# --- Map ---


def test_the_map_waits_for_a_warning(app):
    show(app, "Map")
    assert any("No warning yet" in i.value for i in app.info)


def test_the_map_shows_how_far_a_warning_has_got_and_plays_minutes(app):
    fill_warning(app)
    send(app)
    world = app.session_state.world
    [alert] = world.live_warnings()
    show(app, "Map")
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


# --- Real phone apps on the local network ---


@pytest.fixture
def heard():
    """What a phone app on this computer would hear (on the tests' own port)."""
    got = []
    listener = lan.Listener(got.append)
    yield got
    listener.close()


def wait_for(condition, seconds=5):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    return condition()


def test_a_sent_warning_reaches_phone_apps_with_the_real_time(app, heard):
    fill_warning(app)
    send(app)
    assert "sent to phone apps on the local network" in app.info[0].value
    [simulated] = app.session_state.world.live_warnings()
    assert wait_for(lambda: heard)
    real = wire.decode(heard[0])
    assert wire.verify_pinned(real)
    assert (real.alert_id, real.headline, real.area_cells) == (simulated.alert_id, simulated.headline,
                                                               simulated.area_cells)
    assert abs(real.issued_at - time.time() * 1000) < 60_000  # now, not the town's 2023 clock
    assert real.expires_at - real.issued_at == simulated.expires_at - simulated.issued_at


def test_cancelling_reaches_phone_apps(app, heard):
    fill_warning(app)
    send(app)
    button(app, "Cancel warning").click().run()
    next(b for b in app.button if (b.key or "").startswith("cancel_yes_")).click().run()
    assert wait_for(lambda: any(isinstance(wire.decode(x), wire.AlertCancellation) for x in heard))


# --- The internet (Nostr relays) ---


@pytest.fixture
def relay(monkeypatch):
    """A relay inside the tests, which the warning app's internet link uses instead of
    the real ones."""
    pytest.importorskip("websockets")
    from fake_relay import FakeRelay

    r = FakeRelay()
    monkeypatch.setenv("ALERTMESH_NOSTR_RELAYS", r.url)
    import streamlit as st

    st.cache_resource.clear()  # a new internet link, which reads the relay's address
    yield r
    st.cache_resource.clear()
    r.close()


def alert_events(relay):
    from alertmesh import nostr

    return [wire.decode(nostr.payload_of(nostr.Event.from_dict(e), 1403)) for e in relay.events if e["kind"] == 1403]


def test_the_internet_is_off_until_switched_on(app):
    assert app.toggle(key="internet_on").value is False
    assert "Internet off" in " ".join(m.value for m in app.markdown)
    fill_warning(app)
    button(app, "Send warning…").click().run()
    assert "public relays" not in app.warning[0].value


def test_switched_on_a_warning_and_its_cancellation_go_to_the_relays(relay):
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.run()
    at.toggle(key="internet_on").set_value(True).run()
    assert not at.exception
    fill_warning(at)
    button(at, "Send warning…").click().run()
    assert "public relays" in at.warning[0].value  # the confirmation says where it goes
    button(at, "Send warning").click().run()
    assert wait_for(lambda: len(alert_events(relay)) == 1)
    [real] = alert_events(relay)
    assert wire.verify_pinned(real) and real.headline == "Bushfire near Katherine - leave now"
    assert abs(real.issued_at - time.time() * 1000) < 60_000  # the real-time copy, as for phone apps
    button(at, "Cancel warning").click().run()
    next(b for b in at.button if (b.key or "").startswith("cancel_yes_")).click().run()
    assert wait_for(lambda: any(isinstance(x, wire.AlertCancellation) for x in alert_events(relay)))
    tags = [e["tags"] for e in relay.events]
    assert tags[0] == tags[1]  # the cancellation carries the warning's area and expiry


def test_switching_on_sends_the_warnings_already_live(relay):
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.run()
    fill_warning(at)
    send(at)
    assert relay.events == []
    at.toggle(key="internet_on").set_value(True).run()
    assert wait_for(lambda: len(alert_events(relay)) == 1)


def test_the_status_bar_says_how_many_relays_took_the_last_warning(relay):
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.run()
    at.toggle(key="internet_on").set_value(True).run()
    fill_warning(at)
    send(at)
    assert wait_for(lambda: relay.events)
    time.sleep(0.5)
    at.run()
    bar = next(m.value for m in at.markdown if "am-statusbar" in m.value)
    assert "Internet on · 1 of 1 relays connected · last warning taken by 1 of 1" in bar


# --- Hub board ---


def test_the_board_is_empty_then_shows_the_warning(app):
    show(app, "Hub board")
    assert any("No current warnings" in m.value for m in app.markdown)
    show(app, "Warning console")
    fill_warning(app)
    send(app)
    show(app, "Hub board")
    board = next(m.value for m in app.markdown if "Evacuation centre board" in m.value)
    assert "Emergency Warning · Bushfire" in board
    assert "Bushfire near Katherine - leave now" in board


def test_a_warning_can_be_cancelled_after_the_app_is_closed_and_opened_again(heard):
    """Closing the app used to forget its warnings, so phones kept them with no way to
    cancel them. Opening the app again now lists them, with Cancel."""
    import streamlit as st

    from alertmesh import phone

    st.cache_resource.clear()
    (phone.home_folder() / "warnings-sent.json").unlink(missing_ok=True)
    first = AppTest.from_file(APP, default_timeout=TIMEOUT)
    first.run()
    fill_warning(first)
    send(first)
    [sent] = first.session_state.world.live_warnings()

    st.cache_resource.clear()  # the program ends; a new one starts
    again = AppTest.from_file(APP, default_timeout=TIMEOUT)
    again.run()
    assert not again.exception and again.session_state.world.live_warnings() == []
    assert "Sent before this window was opened" in " ".join(m.value for m in again.markdown)
    again.button(key=f"earlier_{sent.alert_id.hex()}").click().run()
    again.button(key=f"earlier_yes_{sent.alert_id.hex()}").click().run()
    assert not again.exception
    assert wait_for(lambda: any(isinstance(c := wire.decode(x), wire.AlertCancellation)
                                and c.alert_id == sent.alert_id for x in heard))
    assert "Sent before this window was opened" not in " ".join(m.value for m in again.markdown)
    st.cache_resource.clear()


def test_a_warning_can_be_cancelled_by_its_id(app, heard):
    alert_id = bytes(range(16))
    app.text_input(key="c_cancel_id").input(alert_id.hex()).run()
    button(app, "Cancel this warning").click().run()
    assert not app.exception and "Cancellation sent" in app.info[0].value
    assert wait_for(lambda: any(isinstance(c := wire.decode(x), wire.AlertCancellation) and c.alert_id == alert_id
                                for x in heard))
    app.text_input(key="c_cancel_id").input("not an id").run()
    button(app, "Cancel this warning").click().run()
    assert "32 letters and digits" in app.info[0].value


def test_a_new_town_withdraws_the_old_towns_warnings(app, heard):
    fill_warning(app)
    send(app)
    app.button(key="FormSubmitter:town-Build").click().run()
    assert not app.exception
    assert wait_for(lambda: any(isinstance(wire.decode(x), wire.AlertCancellation) for x in heard))
