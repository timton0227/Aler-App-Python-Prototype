"""The phone app: its engine (alertmesh.phone) and its page (phone_app.py), run
headless with Streamlit's own test runner and a fake radio. How the page looks is
checked by eye (PROGRESS.md, step 13.6).
"""
import os
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from streamlit.testing.v1 import AppTest

from alertmesh import bitchat, geohash, node, phone, places, position, reports, signer, wire
from alertmesh.chat import Identity
from alertmesh.bitchat import MessageType, Packet
from alertmesh.node import NEARBY
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
    """Records what the phone sends; one device is "in range"."""

    status = "on"

    def __init__(self):
        self.packets = []

    def send(self, raw):
        self.packets.append(bitchat.decode(raw))

    def neighbours(self):
        return 1

    def kinds(self):
        return [p.type for p in self.packets if p.type != MessageType.ANNOUNCE]


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


SOMEONE = Identity("Someone")
_sent = iter(range(1, 10**6))


def arrive(p: Phone, kind: MessageType, body: bytes, sender: Identity = SOMEONE) -> None:
    """A packet from a device nearby, a millisecond after the last one."""
    packet = Packet(kind, sender.peer_id, p.clock() + next(_sent), body, 7)
    p.node.receive(bitchat.encode(sender.sign_packet(packet)))


def announce(p: Phone, who: Identity, laptop: bool = True) -> None:
    arrive(p, MessageType.ANNOUNCE, bitchat.encode_announcement(
        bitchat.Announcement(who.nickname, who.chat_key, who.signing_key, laptop=laptop)), who)


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
    assert me.node.link.kinds() == [MessageType.COMMUNITY_REPORT]
    assert me.send_safe()
    assert me.my_call_for_help() is None


def test_no_call_for_help_without_a_town(me):
    me.set_town(None)
    assert not me.send_sos("help")
    assert not me.send_hazard(HazardType.FLOOD, ReportSeverity.HIGH, "")
    assert me.node.link.kinds() == []


def test_other_peoples_calls_for_help_are_listed_mine_are_not(me):
    other = reports.ReportAuthor("Bob")
    arrive(me, MessageType.COMMUNITY_REPORT, reports.encode(other.sos(me.geohash, "help", NOW)))
    me.send_sos("me too")
    assert [r.author_nickname for r in me.calls_for_help()] == ["Bob"]


def test_nickname_change_is_saved_and_signed(me):
    me.set_nickname("  Aroha ")
    assert Profile.load(me.folder).nickname == "Aroha"
    assert me.node.author.nickname == "Aroha"



# --- Where you are ---

DARWIN_STREET = (-12.4630, 130.8440)


class FakeLocation:
    """Stands in for the location process."""

    def __init__(self):
        self.on_fix, self.status, self.asked, self.stopped = None, "on", 0, False

    def refresh(self):
        self.asked += 1

    def stop(self):
        self.stopped = True


def located(p: Phone) -> FakeLocation:
    fake = FakeLocation()
    p.start_location(fake)
    return fake


def test_the_town_stands_in_until_there_is_a_fix(me):
    assert me.where == position.Where(places.geohash_of(KATHERINE), position.TOWN, "Katherine")


def test_this_macs_fix_is_used_and_kept_as_a_geohash_only(me, tmp_path, clock):
    fake = located(me)
    fake.on_fix(position.Fix.from_point(*DARWIN_STREET, 35, NOW))
    assert me.where.source == position.MAC
    assert me.geohash == geohash.encode(*DARWIN_STREET, 8)
    saved = (tmp_path / phone.PROFILE_FILE).read_text()
    assert "130.8" not in saved and "-12.4" not in saved  # no raw coordinates on disk
    assert Phone(tmp_path, clock).where.source == position.MAC  # kept for a restart


def test_warnings_and_calls_for_help_follow_the_fix(me):
    located(me).on_fix(position.Fix.from_point(*DARWIN_STREET, 35, NOW))
    darwin = warning_for(geohash.encode(*DARWIN_STREET, 4))
    katherine = warning_for(places.geohash_of(KATHERINE)[:4])
    me.node.take_official(wire.encode(darwin))
    me.node.take_official(wire.encode(katherine))
    loud = {w.alert.alert_id: w.decision.urgency.name for w in me.warnings()}
    assert loud == {darwin.alert_id: "LOUD", katherine.alert_id: "QUIET"}
    assert me.send_sos("Trapped")
    assert me.my_call_for_help().geohash == geohash.encode(*DARWIN_STREET, 7)  # cut to about 150 m


def test_an_old_fix_gives_way_to_the_town(me, clock):
    located(me).on_fix(position.Fix.from_point(*DARWIN_STREET, 35, NOW))
    clock.now_ms += position.FIX_FRESH_MS + 1
    assert me.where.source == position.TOWN


def test_a_pin_comes_first_and_clearing_it_goes_back(me, tmp_path, clock):
    located(me).on_fix(position.Fix.from_point(*DARWIN_STREET, 35, NOW))
    assert me.set_pin("QVQJ0CZX")
    assert me.where == position.Where("qvqj0cz", position.PIN)
    assert Phone(tmp_path, clock).profile.pin == "qvqj0cz"
    assert not me.set_pin("no!")
    assert me.set_pin(None)
    assert me.where.source == position.MAC


def test_a_pin_is_enough_to_call_for_help_without_a_town(me):
    me.set_town(None)
    assert not me.send_sos("help")
    me.set_pin("qvqj0cz")
    assert me.send_sos("help")
    assert me.my_call_for_help().geohash == "qvqj0cz"


def test_turning_location_off_forgets_the_fix_and_stops_the_process(me, tmp_path, clock):
    fake = located(me)
    fake.on_fix(position.Fix.from_point(*DARWIN_STREET, 35, NOW))
    me.set_use_location(False)
    assert fake.stopped and me.location is None
    assert me.where.source == position.TOWN and me.location_status == "off"
    again = Phone(tmp_path, clock)
    assert again.profile.use_location is False and again.profile.last_fix is None
    again.start_location(FakeLocation())
    assert again.location is None  # off stays off


def test_the_location_status_comes_from_the_process(me):
    fake = located(me)
    fake.status = "asking macOS for permission"
    assert me.location_status == "asking macOS for permission"


def test_a_fresh_fix_is_asked_for_without_waiting(me):
    fake = located(me)
    me.refresh_location()
    assert fake.asked == 1


def test_relays_are_asked_again_only_when_the_area_changes(me):
    with_internet(me)
    asked = []
    me.internet.refresh = lambda: asked.append(me.geohash)
    fake = located(me)
    fake.on_fix(position.Fix.from_point(*DARWIN_STREET, 35, NOW))  # Katherine to Darwin
    fake.on_fix(position.Fix.from_point(DARWIN_STREET[0], DARWIN_STREET[1] + 0.001, 35, NOW))  # next door
    me.set_town("Darwin")  # the fix is in use, so the town changes nothing
    assert len(asked) == 1


def test_an_old_profile_without_the_new_settings_still_loads(tmp_path):
    (tmp_path / phone.PROFILE_FILE).write_text(
        '{"nickname": "Aroha", "town": "Katherine", "seed": "%s", "internet": false}' % ("11" * 32))
    profile = Profile.load(tmp_path)
    assert (profile.use_location, profile.pin, profile.last_fix) == (True, None, None)


def test_a_broken_pin_or_fix_in_the_profile_is_dropped(tmp_path):
    (tmp_path / phone.PROFILE_FILE).write_text(
        '{"seed": "%s", "pin": "no!", "last_fix": {"cell": "qvqj", "accuracy": "x"}}' % ("11" * 32))
    profile = Profile.load(tmp_path)
    assert (profile.pin, profile.last_fix) == (None, None)

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
        assert "Bluetooth on · 1 device nearby" in page(app) and "Local network off" in page(app)


def test_a_wrong_clock_is_shown_instead_of_bluetooth_on(me, app):
    """Every packet nearby is dropped when this computer's clock is over 2 minutes off, and
    the iPhones drop ours: "Bluetooth on" would hide that nothing gets through."""
    for i in range(3):
        packet = Packet(MessageType.MESSAGE, SOMEONE.peer_id, NOW - 135_000 + i, b"hi", 7)
        me.node.receive(bitchat.encode(SOMEONE.sign_packet(packet)))
    assert "about 2 min fast" in me.clock_warning
    app.run()
    assert "clock is wrong" in page(app) and "Bluetooth on ·" not in page(app)
    assert "Set the time automatically" in page(app)


def test_i_need_help_bar_is_on_now_only(app):
    assert button(app, "I need help").key == "need_help"
    show(app, "Chat")
    assert not [b for b in app.button if b.key == "need_help"]


def test_page_asks_for_a_town_first(me):
    me.set_town(None)
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.run()
    assert any("drop a pin, or pick your town" in i.value for i in at.info)
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



def settings_open(at: AppTest) -> AppTest:
    at.button(key="open_settings").click().run()
    assert not at.exception
    return at


def test_settings_say_where_the_position_comes_from(me, app):
    settings_open(app)
    assert "<b>Near Katherine</b>, at the centre of Katherine, the town in Settings." in page(app)
    located(me).on_fix(position.Fix.from_point(*DARWIN_STREET, 35, NOW))
    app.run()
    assert "<b>Near Darwin</b>, at this Mac&#x27;s location (about 40 m)." in page(app)
    assert "Position: this Mac (about 40 m)" in page(app)


def test_the_location_switch_turns_this_macs_position_off(me, app):
    located(me).on_fix(position.Fix.from_point(*DARWIN_STREET, 35, NOW))
    settings_open(app)
    app.toggle(key="use_location").set_value(False).run()
    assert me.profile.use_location is False and me.where.source == position.TOWN
    assert any(c.value == "Location: off" for c in app.caption)


def test_dropping_a_pin_by_typing_coordinates(me, app):
    settings_open(app)
    app.button(key="drop_pin").click().run()
    assert not app.exception and app.session_state["pin_open"]
    assert button(app, "Use this spot").disabled
    app.text_input(key="pin_typed").input("12.4630 S, 130.8440 E").run()
    assert "qvqj" not in app.session_state["pin_fine"]
    button(app, "Use this spot").click().run()
    assert me.where == position.Where(geohash.encode(*DARWIN_STREET, 7), position.PIN)
    assert not app.session_state["pin_open"]
    assert "Position: your pin" in page(app)
    assert app.button(key="open_settings").label == f"{me.nickname} · Near Darwin"


def test_typing_something_that_is_not_coordinates_says_so(me, app):
    settings_open(app)
    app.button(key="drop_pin").click().run()
    app.text_input(key="pin_typed").input("Katherine").run()
    assert any(c.value.startswith("Not coordinates") for c in app.caption)
    assert button(app, "Use this spot").disabled


def test_the_pin_map_opens_on_the_current_position(me, app):
    pytest.importorskip("pydeck")
    settings_open(app)
    app.button(key="drop_pin").click().run()
    assert not app.exception
    assert any("about 1 km" in c.value for c in app.caption)


def test_clearing_the_pin_goes_back_to_the_town(me, app):
    me.set_pin("qvqj0cz")
    settings_open(app)
    app.button(key="clear_pin").click().run()
    assert me.profile.pin is None and me.where.source == position.TOWN


def test_a_pin_opens_the_call_for_help_without_a_town(me):
    me.set_town(None)
    me.set_pin(geohash.encode(*DARWIN_STREET, 7))
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.run()
    assert not at.info and not button(at, "I need help").disabled
    fake = located(me)
    button(at, "I need help").click().run()
    assert fake.asked == 1  # a fresh fix is asked for as the sheet opens
    assert "at the pin you dropped, to about 150 metres" in page(at)

class Pool:
    """Stands in for the relay pool."""

    available = True

    def __init__(self):
        self.subscriptions, self.published = {}, []

    def subscribe(self, sub_id, subscription, urls, handler):
        self.subscriptions[sub_id] = subscription

    def unsubscribe(self, sub_id):
        self.subscriptions.pop(sub_id, None)

    def publish(self, event, urls):
        self.published.append(event)

    def status(self):
        return 2, 5


def with_internet(p: Phone) -> Pool:
    from alertmesh import internet

    pool = Pool()
    p.start_internet(pool, internet.RelayChoice(["wss://built-in.example"], None))
    return pool


def test_the_internet_is_off_until_turned_on_and_the_choice_is_kept(me, tmp_path, clock):
    pool = with_internet(me)
    assert me.internet_status == "off" and pool.subscriptions == {}
    me.set_internet(True)
    assert me.internet_status == "on: 2 of 5 relays"
    assert set(pool.subscriptions) == {"alertmesh-official-alerts", "alertmesh-community-reports"}
    again = Phone(tmp_path, clock)
    assert again.profile.internet is True
    again_pool = with_internet(again)
    assert set(again_pool.subscriptions) == {"alertmesh-official-alerts", "alertmesh-community-reports"}
    me.set_internet(False)
    assert me.internet_status == "off" and pool.subscriptions == {}


def test_my_call_for_help_goes_online_only_with_the_internet_on(me):
    pool = with_internet(me)
    assert me.send_sos("Trapped")
    assert pool.published == []
    me.set_internet(True)  # what is still live goes out when it is turned on
    assert [e.kind for e in pool.published] == [1402]


def test_the_page_shows_the_internet_and_settings_turn_it_on(me):
    with_internet(me)
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.run()
    assert "Internet off" in page(at) and "nothing goes to the internet" in page(at)
    at.button(key="open_settings").click().run()
    assert at.toggle(key="internet").value is False and not at.toggle(key="internet").disabled
    at.toggle(key="internet").set_value(True).run()
    assert me.profile.internet is True
    button(at, "Done").click().run()
    assert "Internet on · 2 of 5 relays connected" in page(at)
    assert "Warnings and calls for help also arrive over the internet" in page(at)


def test_without_the_link_the_switch_is_greyed_out(me, app):
    app.button(key="open_settings").click().run()
    assert app.toggle(key="internet").disabled


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
    assert "How you're connected" in page(app) and "1 device nearby can pass warnings to you" in page(app)


def test_calling_for_help_from_the_page(me, app):
    button(app, "I need help").click().run()
    assert "This is not 000" in page(app)  # the sheet is open, nothing sent yet
    assert me.node.link.kinds() == []
    app.text_input(key="sos_note").input("Two of us, one hurt")
    button(app, "Send call for help").click().run()
    assert not app.exception
    assert me.my_call_for_help().note == "Two of us, one hurt"
    assert not [t for t in app.text_input if t.key == "sos_note"]  # the sheet closed
    assert "Your call for help is out" in page(app)
    button(app, "I'm safe now").click().run()
    assert me.my_call_for_help() is None


def test_cancel_closes_the_call_for_help_sheet_without_sending(me, app):
    button(app, "I need help").click().run()
    button(app, "Cancel").click().run()
    assert not app.exception and me.node.link.kinds() == []
    assert "This is not 000" not in page(app)


def test_sheet_buttons_follow_the_system(monkeypatch):
    from alertmesh import style

    monkeypatch.setattr(style, "WINDOWS", False)
    assert style.button_order("send", "cancel") == ["cancel", "send"]  # Mac: the main button last
    monkeypatch.setattr(style, "WINDOWS", True)
    assert style.button_order("send", "cancel") == ["send", "cancel"]  # Windows: the main button first


def test_the_open_sheet_shows_your_call_for_help_when_it_is_out(me, app):
    me.send_sos("")
    app.run()
    button(app, "I need help").click().run()
    assert app.button(key="sos_safe") and app.button(key="sos_again")
    app.button(key="sos_safe").click().run()
    assert me.my_call_for_help() is None


def test_someone_elses_call_for_help_shows_first(me, app):
    arrive(me, MessageType.COMMUNITY_REPORT, reports.encode(reports.ReportAuthor("Bob").sos(me.geohash, "leg broken", NOW)))
    app.run()
    assert "Calls for help" in page(app) and "Bob needs help" in page(app) and "leg broken" in page(app)
    assert not [b for b in app.button if b.label == "Message Bob"]  # Bob's laptop is not in range


def test_a_call_for_help_from_someone_in_range_can_be_answered(me, app):
    bob = Identity("Bob")  # one key signs Bob's chat and his reports, as on his phone
    announce(me, bob)
    arrive(me, MessageType.COMMUNITY_REPORT, reports.encode(reports.ReportAuthor("Bob", bob.signing_seed).sos(me.geohash, "", NOW)), bob)
    app.run()
    button(app, "Message Bob").click().run()
    assert app.session_state["view"] == "Chat" and app.session_state["chat_with"] == bob.signing_key.hex()


def test_reporting_a_hazard(me, app):
    show(app, "Report")
    app.selectbox(key="r_hazard").set_value(HazardType.STORM)
    app.button(key="how_bad_high").click().run()
    assert app.button(key="how_bad_high").proto.type == "primary"
    app.text_area(key="r_note").input("Tree down on the highway")
    button(app, "Send report").click().run()
    assert not app.exception
    (report,) = me.reports()
    assert (report.kind, report.hazard, report.severity, report.note) == (
        ReportKind.HAZARD, HazardType.STORM, ReportSeverity.HIGH, "Tree down on the highway")
    assert "Storm · Dangerous" in page(app) and "You · Near Katherine" in page(app)
    assert "am-help" not in page(app)  # a hazard report is grey


def test_calls_for_help_are_red_and_hazard_reports_grey_in_the_report_list(me, app):
    arrive(me, MessageType.COMMUNITY_REPORT, reports.encode(reports.ReportAuthor("Bob").sos(me.geohash, "leg broken", NOW)))
    show(app, "Report")
    assert 'class="am-card am-rep am-help"' in page(app) and "Bob needs help" in page(app)
    assert "Not official warnings. Nobody has checked them." in [c.value for c in app.caption]


def test_typing_a_message_sends_it_to_nearby(me, app):
    show(app, "Chat")
    app.chat_input(key="chat_text").set_value("Is the bridge open?").run()
    assert not app.exception
    (packet,) = [f for f in me.node.link.packets if f.type == MessageType.MESSAGE]
    assert packet.payload == "Is the bridge open?".encode()
    assert 'class="am-msg am-out"><span class="am-bub">Is the bridge open?</span>' in page(app)


def test_incoming_message_is_counted_then_read(me, app):
    bob = Identity("Bob")
    announce(me, bob, laptop=False)  # an iPhone
    arrive(me, MessageType.MESSAGE, "Bridge is closed".encode(), bob)
    app.run()
    assert me.node.chats.unread == 1
    assert app.button(key="nav_chat").label == "Chat :red-badge[1]"
    show(app, "Chat")
    assert me.node.chats.unread == 0
    assert app.button(key="nav_chat").label == "Chat"
    assert '<span class="am-from">Bob</span><span class="am-bub">Bridge is closed</span>' in page(app)


def test_private_conversation_with_someone_in_range(me, app):
    bob = Identity("Bob")
    announce(me, bob)
    show(app, "Chat")
    button(app, "Message Bob").click().run()
    app.chat_input(key="chat_text").set_value("just to you").run()
    assert not app.exception
    (packet,) = [f for f in me.node.link.packets if f.type == MessageType.LAPTOP_PRIVATE]
    assert bob.open(packet.payload).text == "just to you"



def test_iphones_and_laptops_are_listed_together(me, app):
    announce(me, Identity("9vision"), laptop=False)
    announce(me, Identity("Bob"))
    show(app, "Chat")
    assert "9vision · <span class=\"am-muted\">iPhone, Nearby only</span>" in page(app)
    assert button(app, "Message Bob")
    assert not [b for b in app.button if b.label == "Message 9vision"]
    assert any("private chat is laptop to laptop" in c.value for c in app.caption)


def test_an_iphones_call_for_help_offers_no_private_message(me, app):
    iphone = Identity("9vision")
    announce(me, iphone, laptop=False)
    arrive(me, MessageType.COMMUNITY_REPORT,
           reports.encode(reports.ReportAuthor("9vision", iphone.signing_seed).sos(me.geohash, "", NOW)), iphone)
    app.run()
    assert "9vision needs help" in page(app)
    assert not [b for b in app.button if b.label == "Message 9vision"]


def test_an_iphones_nearby_message_shows_with_its_name(me, app):
    iphone = Identity("9vision")
    announce(me, iphone, laptop=False)
    arrive(me, MessageType.MESSAGE, "Checking from iphone".encode(), iphone)
    show(app, "Chat")
    assert '<span class="am-from">9vision</span><span class="am-bub">Checking from iphone</span>' in page(app)

def test_too_long_message_is_refused_with_a_reason(me, app):
    show(app, "Chat")
    app.chat_input(key="chat_text").set_value("😀" * 100).run()
    assert any(f"at most {node.TEXT_MAX_BYTES} bytes" in w.value for w in app.warning)
    assert not [f for f in me.node.link.packets if f.type == MessageType.MESSAGE]
