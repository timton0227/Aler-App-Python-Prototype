"""Tests for alertmesh.internet, with stand-ins for the relays, and end to end against a
relay run inside the tests (fake_relay.py).

Ported from: alert-mesh/AlertMeshTests/AlertMesh/Services/OfficialAlertBridgeTests.swift
             and CommunityReportBridgeTests.swift (each test names its Swift case where
             there is one).
"""
import os
import time

import pytest

from alertmesh import georelays, internet, nostr, reports, wire
from alertmesh.chat import Identity
from alertmesh import bitchat
from alertmesh.bitchat import MessageType, Packet
from alertmesh.node import Node
from alertmesh.reports import ReportAuthor, ReportSeverity
from alertmesh.signer import OfficialAlertSigner, WarningDraft
from alertmesh.wire import HazardType

NOW_MS = int(time.time() * 1000)


def warning(cells=("r7hg2bc", "r7hu")):
    draft = WarningDraft(headline="Flood", action_text="Move to higher ground", area_cells=list(cells))
    return OfficialAlertSigner().sign(draft, bytes(range(16)), NOW_MS)


class Recorder:
    """Stands in for the relay pool."""

    available = True

    def __init__(self):
        self.published = []

    def publish(self, event, urls):
        self.published.append((event, list(urls)))

    def results(self, event_id):
        return {}


class FakeDirectory:
    def relays_for(self, cell, count=5):
        return [f"wss://relay-{cell}.example"]

    def refresh_if_due(self):
        return False


def test_relays_for_a_warning_are_the_built_in_ones_and_each_cells_geo_relays():
    choice = internet.RelayChoice(["wss://built-in.example"], FakeDirectory())
    assert choice.for_warning(["r7hg2bc", "R7HU", "r"]) == [
        "wss://built-in.example", "wss://relay-r7hg.example", "wss://relay-r7hu.example"]
    assert choice.geo("r7hg2bc") == ["wss://relay-r7hg.example"]
    assert choice.for_warning([]) == []


def test_named_relays_replace_every_other(monkeypatch):
    monkeypatch.setenv(nostr.RELAYS_VARIABLE, "ws://127.0.0.1:1")
    choice = internet.RelayChoice.from_environment()
    assert choice.directory is None
    assert choice.for_warning(["r7hg"]) == ["ws://127.0.0.1:1"] and choice.geo("r7hg") == ["ws://127.0.0.1:1"]


def test_without_a_name_the_built_in_and_geo_relays_are_used(monkeypatch):
    monkeypatch.delenv(nostr.RELAYS_VARIABLE)
    choice = internet.RelayChoice.from_environment()
    assert choice.built_in == list(nostr.BUILT_IN_RELAYS)
    assert isinstance(choice.directory, georelays.Directory)


def sender():
    pool = Recorder()
    s = internet.WarningSender(pool, internet.RelayChoice(["wss://built-in.example"], FakeDirectory()))
    return s, pool


def test_nothing_is_published_while_off():
    s, pool = sender()
    assert not s.send(wire.encode(warning()))
    assert pool.published == [] and s.status() is None


def test_a_warning_is_published_with_its_area_tags_and_expiry():
    s, pool = sender()
    s.enabled = True
    alert = warning()
    assert s.send(wire.encode(alert))
    [(event, relays)] = pool.published
    assert event.kind == 1403 and event.is_valid()
    assert ("g", "r7hg") in event.tags and ("g", "r7hu") in event.tags
    assert ("expiration", str(alert.expires_at // 1000)) in event.tags
    assert nostr.payload_of(event, 1403) == wire.encode(alert)
    assert relays == ["wss://built-in.example", "wss://relay-r7hg.example", "wss://relay-r7hu.example"]
    assert s.status() == (0, 3)


def test_a_cancellation_is_tagged_with_the_warnings_area_even_if_sent_while_off():
    s, pool = sender()
    alert = warning()
    s.send(wire.encode(alert))  # off: remembered, not published
    s.enabled = True
    cancellation = OfficialAlertSigner().cancel(alert.alert_id, NOW_MS + 1)
    assert s.send(wire.encode(cancellation))
    [(event, _)] = pool.published
    assert ("g", "r7hg") in event.tags and ("expiration", str(alert.expires_at // 1000)) in event.tags


def test_a_cancellation_of_an_unknown_warning_or_garbage_is_not_published():
    s, pool = sender()
    s.enabled = True
    assert not s.send(wire.encode(OfficialAlertSigner().cancel(bytes(16), NOW_MS)))
    assert not s.send(b"garbage")
    assert pool.published == []


def test_with_no_relays_nothing_is_published():
    pool = Recorder()
    s = internet.WarningSender(pool, internet.RelayChoice([], None))
    s.enabled = True
    assert not s.send(wire.encode(warning()))
    assert pool.published == []


def test_a_warning_reaches_a_relay_and_its_answer_counts():
    pytest.importorskip("websockets")
    from alertmesh.relays import RelayPool
    from fake_relay import FakeRelay

    relay = FakeRelay()
    pool = RelayPool()
    s = internet.WarningSender(pool, internet.RelayChoice([relay.url], None))
    s.enabled = True
    alert = warning()
    assert s.send(wire.encode(alert))
    deadline = time.monotonic() + 5
    while s.status() != (1, 1) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert s.status() == (1, 1)
    [stored] = relay.events
    assert wire.decode(nostr.payload_of(nostr.Event.from_dict(stored), 1403)) == alert
    pool.close()
    relay.close()


# --- The phone app's side (PhoneLink) ---
# Ported from: CommunityReportBridgeTests.swift and OfficialAlertBridgeTests.swift
# (aReceivedWarningGoesToTheMeshOnce, updatesAndCancellationsAreNewVersions,
# aForgedCopyDoesNotBlockTheGenuineWarning, subscriptionAsksForEveryWarning,
# anSOSIsPublishedOnceToItsCellsRelays, hazardReportsStayOffTheInternet,
# aReceivedSOSGoesToTheMeshAndIsNotEchoed, otherEventKindsAreIgnored,
# subscriptionCoversNearbyCellsOnTheirRelays, movingChangesTheSubscription,
# noPlaceMeansNoSubscription).


class SubscribingRecorder(Recorder):
    def __init__(self):
        super().__init__()
        self.subscriptions = {}

    def subscribe(self, sub_id, subscription, urls, handler):
        self.subscriptions[sub_id] = (subscription, list(urls), handler)

    def unsubscribe(self, sub_id):
        self.subscriptions.pop(sub_id, None)


class Air:
    """Stands in for Bluetooth: keeps every packet sent."""

    def __init__(self):
        self.packets = []

    def send(self, raw):
        self.packets.append(bitchat.decode(raw))

    def neighbours(self):
        return 0

    def kinds(self):
        return [p.type for p in self.packets if p.type in (MessageType.OFFICIAL_ALERT, MessageType.COMMUNITY_REPORT)]


PLACE = ["r7hg2bc"]


def phone_link(places=PLACE, on=True):
    pool = SubscribingRecorder()
    air = Air()
    node = Node(Identity("Me", os.urandom(Identity.SEED_LENGTH)), air, clock=lambda: NOW_MS)
    link = internet.PhoneLink(pool, internet.RelayChoice(["wss://built-in.example"], FakeDirectory()), node,
                              lambda: list(places), lambda: NOW_MS)
    node.on_report = link.report_arrived
    if on:
        link.set_enabled(True)
    return link, pool, node, air


def warning_event(alert, area=None):
    return nostr.alert_event(wire.encode(alert), area or alert.area_cells, alert.expires_at)


def test_the_warning_subscription_asks_for_every_warning_on_built_in_and_nearby_relays():
    link, pool, _, _ = phone_link()
    subscription, relays, _ = pool.subscriptions[link.ALERTS]
    assert subscription["kinds"] == [1403] and "#g" not in subscription
    assert subscription["since"] == NOW_MS // 1000 - wire.MAX_LIFETIME_MS // 1000
    assert "wss://built-in.example" in relays and "wss://relay-r7hg.example" in relays
    assert len(relays) == 1 + 9  # built-in, the town's cell and its 8 neighbours


def test_a_phone_with_no_town_still_listens_for_warnings_but_not_calls_for_help():
    link, pool, _, _ = phone_link(places=[None])
    assert pool.subscriptions[link.ALERTS][1] == ["wss://built-in.example"]
    assert link.REPORTS not in pool.subscriptions


def test_a_received_warning_goes_to_the_mesh_once():
    link, _, node, air = phone_link()
    alert = warning()
    link.take_alert(warning_event(alert))
    link.take_alert(warning_event(alert))  # the same version from another relay
    assert [a.alert_id for a in node.alerts.live_alerts()] == [alert.alert_id]
    assert air.kinds() == [MessageType.OFFICIAL_ALERT]


def test_updates_and_cancellations_are_new_versions():
    link, _, node, air = phone_link()
    alert = warning()
    update = OfficialAlertSigner().sign(WarningDraft(headline="Flood rising", action_text="Leave now",
                                                     area_cells=list(alert.area_cells)), alert.alert_id, NOW_MS + 1)
    cancellation = OfficialAlertSigner().cancel(alert.alert_id, NOW_MS + 2)
    for item in (alert, update):
        link.take_alert(warning_event(item))
    link.take_alert(nostr.alert_event(wire.encode(cancellation), alert.area_cells, alert.expires_at))
    assert air.kinds() == [MessageType.OFFICIAL_ALERT] * 3
    assert node.alerts.live_alerts() == []


def test_a_forged_copy_does_not_block_the_genuine_warning():
    link, _, node, _ = phone_link()
    genuine = warning()
    forged = OfficialAlertSigner(bytes(range(32))).sign(
        WarningDraft(headline="Fake", action_text="x", area_cells=["r7hg"]), genuine.alert_id, genuine.issued_at)
    link.take_alert(warning_event(forged))
    assert node.alerts.live_alerts() == []
    link.take_alert(warning_event(genuine))
    assert [a.headline for a in node.alerts.live_alerts()] == ["Flood"]


def test_other_kinds_and_broken_content_are_ignored():
    link, _, node, air = phone_link()
    link.take_alert(nostr.sign_event(1, [], warning_event(warning()).content))
    link.take_alert(nostr.sign_event(1403, [], "not base64!"))
    link.take_report(nostr.sign_event(1403, [], "AAAA"))
    assert air.packets == [] and node.alerts.live_alerts() == []


def sos(author=None, cell="r7hg2bc", note="Trapped on roof"):
    return (author or ReportAuthor("Sam")).sos(cell, note, NOW_MS)


def test_the_report_subscription_covers_nearby_cells_on_their_relays():
    link, pool, _, _ = phone_link()
    subscription, relays, _ = pool.subscriptions[link.REPORTS]
    assert subscription["kinds"] == [1402] and "r7hg" in subscription["#g"] and len(subscription["#g"]) == 9
    assert subscription["since"] == NOW_MS // 1000 - 6 * 60 * 60
    assert relays == sorted(f"wss://relay-{cell}.example" for cell in subscription["#g"])
    assert "wss://built-in.example" not in relays


def test_moving_changes_the_subscription():
    places = list(PLACE)
    link, pool, _, _ = phone_link(places=places)
    places[0] = "qd66hr2"  # another town
    link.refresh()
    assert "qd66" in pool.subscriptions[link.REPORTS][0]["#g"]
    assert "r7hg" not in pool.subscriptions[link.REPORTS][0]["#g"]


def test_our_own_sos_is_published_once_to_its_cells_relays():
    link, pool, node, _ = phone_link()
    report = sos(node.author)
    assert node.send_report(report)
    node.tick()  # gossip hands it to the store again: still published once
    [(event, relays)] = pool.published
    assert event.kind == 1402 and relays == ["wss://relay-r7hg.example"]
    assert reports.decode(nostr.payload_of(event, 1402)) == report


def test_a_heard_sos_is_published_too_but_hazard_reports_stay_off_the_internet():
    link, pool, node, _ = phone_link()
    hazard = ReportAuthor("Kim").hazard(HazardType.FLOOD, ReportSeverity.HIGH, "r7hg2bc", "Road under water",
                                        NOW_MS)
    node.receive(node_frame(MessageType.COMMUNITY_REPORT, reports.encode(hazard)))
    assert node.reports.live_reports() == [hazard]  # taken, but not put online
    assert pool.published == []
    heard = sos()
    node.receive(node_frame(MessageType.COMMUNITY_REPORT, reports.encode(heard)))
    assert [reports.decode(nostr.payload_of(e, 1402)) for e, _ in pool.published] == [heard]


NEIGHBOUR = Identity("Neighbour")


def node_frame(kind, body):
    """A packet from a device nearby."""
    return bitchat.encode(NEIGHBOUR.sign_packet(Packet(kind, NEIGHBOUR.peer_id, NOW_MS, body, 3)))


def test_a_received_sos_goes_to_the_mesh_and_is_not_echoed():
    link, pool, node, air = phone_link()
    report = sos()
    link.take_report(nostr.report_event(report))
    link.take_report(nostr.report_event(report))  # again, from another relay
    assert node.reports.live_reports() == [report]
    assert air.kinds() == [MessageType.COMMUNITY_REPORT]
    assert pool.published == []


def test_a_safe_answer_replaces_the_sos():
    link, _, node, _ = phone_link()
    author = ReportAuthor("Sam")
    first = sos(author)
    link.take_report(nostr.report_event(first))
    safe = author.safe(None, "", NOW_MS + 1)
    link.take_report(nostr.report_event(safe))
    assert [r.kind for r in node.reports.live_reports()] == [reports.ReportKind.SAFE]


def test_off_nothing_is_published_and_turning_on_publishes_what_is_live():
    link, pool, node, _ = phone_link(on=False)
    assert pool.subscriptions == {}
    report = sos(node.author)
    node.send_report(report)
    assert pool.published == []
    link.set_enabled(True)
    assert [reports.decode(nostr.payload_of(e, 1402)) for e, _ in pool.published] == [report]
    assert set(pool.subscriptions) == {link.ALERTS, link.REPORTS}
    link.set_enabled(False)
    assert pool.subscriptions == {}


def test_end_to_end_warning_app_to_phone_app_and_calls_for_help_between_phones():
    """Through a relay inside the tests: a warning from the warning app's sender reaches
    a phone app, and a call for help from one phone app reaches another."""
    pytest.importorskip("websockets")
    from alertmesh.relays import RelayPool
    from fake_relay import FakeRelay

    relay = FakeRelay()
    choice = internet.RelayChoice([relay.url], None)
    pools = [RelayPool() for _ in range(3)]
    sender = internet.WarningSender(pools[0], choice)
    sender.enabled = True
    phones = []
    for pool in pools[1:]:
        air = Air()
        node = Node(Identity("P", os.urandom(Identity.SEED_LENGTH)), air, clock=lambda: int(time.time() * 1000))
        link = internet.PhoneLink(pool, choice, node, lambda: PLACE, lambda: int(time.time() * 1000))
        node.on_report = link.report_arrived
        link.set_enabled(True)
        phones.append((node, air))

    def wait(condition):
        deadline = time.monotonic() + 5
        while not condition() and time.monotonic() < deadline:
            time.sleep(0.01)
        return condition()

    alert = OfficialAlertSigner().sign(WarningDraft(headline="Flood", action_text="Go", area_cells=["r7hg"]),
                                       bytes(16), int(time.time() * 1000))
    sender.send(wire.encode(alert))
    assert wait(lambda: all(node.alerts.live_alerts() for node, _ in phones))
    (first, _), (second, second_air) = phones
    first.send_report(first.author.sos("r7hg2bc", "Help", int(time.time() * 1000)))
    assert wait(lambda: second.reports.live_reports())
    assert wait(lambda: MessageType.COMMUNITY_REPORT in second_air.kinds())  # passed on over Bluetooth
    for pool in pools:
        pool.close()
    relay.close()
