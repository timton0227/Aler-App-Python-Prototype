"""The phone app: its engine (alertmesh.phone) and its page (phone_app.py), run
headless with Streamlit's own test runner and a fake radio. How the page looks is
checked by eye (PROGRESS.md, step 13.6).
"""
import os
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from streamlit.testing.v1 import AppTest

from alertmesh import chat, node, phone, places, reports, signer, wire
from alertmesh.chat import Identity
from alertmesh.node import NEARBY, Frame, FrameKind
from alertmesh.phone import Phone, Profile
from alertmesh.reports import ReportKind, ReportSeverity
from alertmesh.wire import HazardType, Severity

TIMEOUT = 30
APP = str(Path(__file__).resolve().parent.parent / "phone_app.py")
NOW = 1_790_000_000_000
HOUR_MS = 60 * 60 * 1000
KATHERINE = places.find("Katherine")


class Clock:
    def __init__(self):
        self.now_ms = NOW

    def __call__(self):
        return self.now_ms


class Air:
    """Records what the phone sends; `neighbours` laptops are "in range"."""

    status = "on"

    def __init__(self):
        self.frames = []

    def send(self, frame):
        self.frames.append(node.decode_frame(frame))

    def neighbours(self):
        return 1

    def kinds(self):
        return [f.kind for f in self.frames]


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def me(tmp_path, clock):
    p = Phone(tmp_path, clock)
    p.node.link = Air()
    p.set_town("Katherine")
    phone.set_shared(p)
    yield p
    phone.set_shared(None)


def arrive(p: Phone, kind: FrameKind, body: bytes) -> None:
    p.node.receive(node.encode_frame(Frame(kind, 7, os.urandom(16), body)))


def warning_for(cell: str, severity=Severity.WATCH_AND_ACT, now_ms=NOW):
    draft = signer.WarningDraft(severity=severity, headline="Flooding at Katherine",
                                action_text="Move to higher ground.", area_cells=[cell])
    return signer.OfficialAlertSigner().sign(draft, os.urandom(16), now_ms)


# --- Profile ---


def test_profile_is_made_once_and_kept(tmp_path):
    first = Profile.load(tmp_path)
    again = Profile.load(tmp_path)
    assert again.seed == first.seed and len(first.seed) == Identity.SEED_LENGTH
    assert (tmp_path / phone.PROFILE_FILE).stat().st_mode & 0o077 == 0  # only the owner can read the keys


def test_broken_profile_is_replaced(tmp_path):
    (tmp_path / phone.PROFILE_FILE).write_text("{not json")
    assert len(Profile.load(tmp_path).seed) == Identity.SEED_LENGTH


def test_same_person_after_a_restart(tmp_path, clock):
    first = Phone(tmp_path, clock)
    first.set_nickname("Aroha")
    first.set_town("Katherine")
    again = Phone(tmp_path, clock)
    assert again.node.identity.signing_key == first.node.identity.signing_key
    assert (again.nickname, again.town.name) == ("Aroha", "Katherine")


def test_home_folder_can_be_moved(monkeypatch, tmp_path):
    monkeypatch.setenv("ALERTMESH_HOME", str(tmp_path))
    assert phone.home_folder() == tmp_path


# --- Engine ---


def test_warning_for_my_town_is_loud_and_elsewhere_quiet(me):
    here = warning_for(me.geohash[:4])
    far = warning_for("r1r0")  # Melbourne
    me.node.take_official(wire.encode(here))
    me.node.take_official(wire.encode(far))
    loud = {w.alert.alert_id: w.decision.urgency.name for w in me.warnings()}
    assert loud == {here.alert_id: "LOUD", far.alert_id: "QUIET"}


def test_call_for_help_is_sent_from_my_town_and_answered(me):
    assert me.send_sos("Trapped on the roof")
    mine = me.my_call_for_help()
    assert mine.geohash == places.geohash_of(KATHERINE) and mine.note == "Trapped on the roof"
    assert me.node.link.kinds() == [FrameKind.REPORT]
    assert me.send_safe()
    assert me.my_call_for_help() is None


def test_no_call_for_help_without_a_town(me):
    me.set_town(None)
    assert not me.send_sos("help")
    assert not me.send_hazard(HazardType.FLOOD, ReportSeverity.HIGH, "")
    assert me.node.link.frames == []


def test_other_peoples_calls_for_help_are_listed_mine_are_not(me):
    other = reports.ReportAuthor("Bob")
    arrive(me, FrameKind.REPORT, reports.encode(other.sos(me.geohash, "help", NOW)))
    me.send_sos("me too")
    assert [r.author_nickname for r in me.calls_for_help()] == ["Bob"]


def test_nickname_change_is_saved_and_signed(me):
    me.set_nickname("  Aroha ")
    assert Profile.load(me.folder).nickname == "Aroha"
    assert me.node.author.nickname == "Aroha"


# --- Page ---


@pytest.fixture
def app(me) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.run()
    assert not at.exception
    return at


def button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def show(at: AppTest, view: str) -> None:
    at.button(key=f"nav_{view.lower()}").click().run()
    assert not at.exception
    assert at.session_state["view"] == view


def page(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


def test_page_opens_on_now_with_three_tabs_in_the_sidebar(app):
    assert [b.key for b in app.sidebar.button if b.key.startswith("nav_")] == ["nav_now", "nav_report", "nav_chat"]
    assert app.session_state["view"] == "Now"
    assert '<div class="am-pagetitle">Now</div>' in page(app)
    assert "No current warnings" in page(app)
    show(app, "Report")
    assert '<div class="am-pagetitle">Report</div>' in page(app)


def test_status_bar_shows_bluetooth_and_the_local_network_on_every_tab(me, app):
    for view in ("Now", "Report", "Chat"):
        show(app, view)
        assert "Bluetooth on · 1 laptop nearby" in page(app) and "Local network off" in page(app)


def test_i_need_help_bar_is_on_now_only(app):
    assert button(app, "I need help").key == "need_help"
    show(app, "Chat")
    assert not [b for b in app.button if b.key == "need_help"]


def test_page_asks_for_a_town_first(me):
    me.set_town(None)
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.run()
    assert any("Pick your town" in i.value for i in at.info)
    assert button(at, "I need help").disabled
    button(at, "Open Settings").click().run()
    at.selectbox(key="town").set_value("Katherine").run()
    assert me.town.name == "Katherine"
    button(at, "Done").click().run()
    assert not at.exception and not [s for s in at.selectbox if s.key == "town"]
    assert not button(at, "I need help").disabled


def test_settings_open_from_the_foot_of_the_sidebar(me, app):
    foot = app.button(key="open_settings")
    assert foot.label == f"{me.nickname} · Katherine"
    foot.click().run()
    app.text_input(key="nickname").input("Aroha").run()
    assert me.nickname == "Aroha"


def test_warning_shows_on_now(me, app):
    me.node.take_official(wire.encode(warning_for(me.geohash[:4], Severity.EMERGENCY_WARNING)))
    app.run()
    shown = page(app)
    assert "Flooding at Katherine" in shown and "You are in this area" in shown
    assert "Emergency Warning" in shown


# --- Now (NowView's status) ---


def view_of(p: Phone, cell: str, severity=Severity.WATCH_AND_ACT):
    p.node.take_official(wire.encode(warning_for(cell, severity)))


def test_now_is_clear_with_no_warnings(me):
    assert phone.now_status(me.warnings()).kind is phone.NowKind.CLEAR


def test_now_is_elsewhere_when_no_warning_covers_you(me):
    view_of(me, "r1r0")  # Melbourne
    now = phone.now_status(me.warnings())
    assert now.kind is phone.NowKind.ELSEWHERE and now.affected is None and len(now.others) == 1


def test_the_block_shows_the_worst_warning_that_covers_you(me):
    view_of(me, "r1r0", Severity.EMERGENCY_WARNING)          # worse, but elsewhere
    view_of(me, me.geohash[:4], Severity.ADVICE)
    view_of(me, me.geohash[:4], Severity.WATCH_AND_ACT)
    now = phone.now_status(me.warnings())
    assert now.kind is phone.NowKind.AFFECTED
    assert now.affected.alert.severity is Severity.WATCH_AND_ACT
    # Every other warning is listed under it, most severe first.
    assert [w.alert.severity for w in now.others] == [Severity.EMERGENCY_WARNING, Severity.ADVICE]


def test_next_to_the_area_is_not_covering_you(me):
    view_of(me, wire_neighbours(me.geohash[:5])[0])  # adjacency counts from 5 characters (~5 km)
    now = phone.now_status(me.warnings())
    assert now.kind is phone.NowKind.ELSEWHERE
    assert now.others[0].decision.reason.kind.name == "ADJACENT_TO_AREA"


def wire_neighbours(cell: str) -> list[str]:
    from alertmesh import geohash

    return geohash.neighbors(cell)


def test_page_says_no_warnings_where_you_are(me, app):
    view_of(me, "r1r0")
    app.run()
    assert "No warnings where you are" in page(app) and "am-block" not in page(app)
    assert "Other warnings" in page(app)


def test_page_shows_the_block_what_to_do_and_the_full_warning(me, app):
    view_of(me, me.geohash[:4], Severity.EMERGENCY_WARNING)
    app.run()
    shown = page(app)
    assert 'class="am-block am-fill-e"' in shown and "What to do" in shown and "Move to higher ground." in shown
    button(app, "Open full warning ›").click().run()
    assert "You are inside the warning area" in page(app)
    button(app, "Close").click().run()
    assert "You are inside the warning area" not in page(app)


def test_page_says_how_you_are_connected(me, app):
    assert "How you're connected" in page(app) and "1 laptop nearby can pass warnings to you" in page(app)


def test_calling_for_help_from_the_page(me, app):
    button(app, "I need help").click().run()
    app.text_input(key="sos_note").input("Two of us, one hurt")
    button(app, "Send call for help").click().run()
    assert not app.exception
    assert me.my_call_for_help().note == "Two of us, one hurt"
    assert any("Your call for help is out" in e.value for e in app.error)
    button(app, "I'm safe now").click().run()
    assert me.my_call_for_help() is None


def test_someone_elses_call_for_help_shows_first(me, app):
    arrive(me, FrameKind.REPORT, reports.encode(reports.ReportAuthor("Bob").sos(me.geohash, "leg broken", NOW)))
    app.run()
    assert "Calls for help" in page(app) and "Bob needs help" in page(app) and "leg broken" in page(app)
    assert not [b for b in app.button if b.label == "Message Bob"]  # Bob's laptop is not in range


def test_a_call_for_help_from_someone_in_range_can_be_answered(me, app):
    bob = Identity("Bob")  # one key signs Bob's chat and his reports, as on his phone
    arrive(me, FrameKind.ANNOUNCE, chat.encode_announce(bob.announce(NOW)))
    arrive(me, FrameKind.REPORT, reports.encode(reports.ReportAuthor("Bob", bob.signing_seed).sos(me.geohash, "", NOW)))
    app.run()
    button(app, "Message Bob").click().run()
    assert app.session_state["view"] == "Chat" and app.session_state["chat_with"] == bob.signing_key.hex()


def test_reporting_a_hazard(me, app):
    show(app, "Report")
    app.selectbox(key="r_hazard").set_value(HazardType.STORM)
    app.radio(key="r_how_bad").set_value(ReportSeverity.HIGH)
    app.text_input(key="r_note").input("Tree down on the highway")
    button(app, "Send report").click().run()
    assert not app.exception
    (report,) = me.reports()
    assert (report.kind, report.hazard, report.note) == (ReportKind.HAZARD, HazardType.STORM, "Tree down on the highway")
    assert any("You" in m.value and "Storm" in m.value for m in app.markdown)


def test_typing_a_message_sends_it_to_nearby(me, app):
    show(app, "Chat")
    app.chat_input(key="chat_text").set_value("Is the bridge open?").run()
    assert not app.exception
    (frame,) = [f for f in me.node.link.frames if f.kind == FrameKind.CHAT]
    assert chat.decode_message(frame.body).text == "Is the bridge open?"
    assert any(t.value == "Is the bridge open?" for t in app.text)


def test_incoming_message_is_counted_then_read(me, app):
    bob = Identity("Bob")
    arrive(me, FrameKind.CHAT, chat.encode_message(bob.message("Bridge is closed", NOW)))
    app.run()
    assert me.node.chats.unread == 1
    assert app.button(key="nav_chat").label == "Chat :red-badge[1]"
    show(app, "Chat")
    assert me.node.chats.unread == 0
    assert app.button(key="nav_chat").label == "Chat"
    assert any(t.value == "Bridge is closed" for t in app.text)


def test_private_conversation_with_someone_in_range(me, app):
    bob = Identity("Bob")
    arrive(me, FrameKind.ANNOUNCE, chat.encode_announce(bob.announce(NOW)))
    show(app, "Chat")
    button(app, "Message Bob").click().run()
    app.chat_input(key="chat_text").set_value("just to you").run()
    assert not app.exception
    (frame,) = [f for f in me.node.link.frames if f.kind == FrameKind.PRIVATE]
    assert bob.open(frame.body).text == "just to you"


def test_too_long_message_is_refused_with_a_reason(me, app):
    show(app, "Chat")
    app.chat_input(key="chat_text").set_value("😀" * 100).run()
    assert any("at most 280 bytes" in w.value for w in app.warning)
    assert not [f for f in me.node.link.frames if f.kind == FrameKind.CHAT]
