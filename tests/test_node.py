"""Tests for alertmesh.node, with a fake radio instead of Bluetooth.

No Swift tests to port directly: the rules follow BLEService (relay, TTL, announces) and
MessageDeduplicationService (each packet once), as the module docstring says.
"""
import os
from collections import deque

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from alertmesh import chat, node, reports, wire
from alertmesh.chat import Identity
from alertmesh.node import NEARBY, Frame, FrameKind, Node
from alertmesh.wire import HazardType, OfficialAlert, Severity

PUBLISHER = Ed25519PrivateKey.generate()
NOW = 1_790_000_000_000
HOUR_MS = 60 * 60 * 1000


class Clock:
    def __init__(self):
        self.now_ms = NOW

    def __call__(self):
        return self.now_ms


class Radio:
    """Laptops and who is in range of whom. Frames are delivered in order until quiet."""

    def __init__(self):
        self.nodes: dict[str, Node] = {}
        self.links: dict[str, set[str]] = {}
        self.queue = deque()
        self.sent: list[tuple[str, bytes]] = []

    def link(self, a: str, b: str):
        self.links[a].add(b)
        self.links[b].add(a)

    def run(self):
        while self.queue:
            sender, frame = self.queue.popleft()
            for other in sorted(self.links[sender]):
                self.nodes[other].receive(frame)


class FakeLink:
    def __init__(self, radio: Radio, name: str):
        self.radio, self.name = radio, name

    def send(self, frame: bytes):
        self.radio.sent.append((self.name, frame))
        self.radio.queue.append((self.name, frame))

    def neighbours(self) -> int:
        return len(self.radio.links[self.name])


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def radio():
    return Radio()


def add(radio, clock, name):
    radio.links[name] = set()
    radio.nodes[name] = Node(Identity(name), FakeLink(radio, name), clock,
                             publisher_key=PUBLISHER.public_key().public_bytes_raw())
    return radio.nodes[name]


def line(radio, clock, *names):
    """Laptops in a row, each in range of the next only."""
    nodes = [add(radio, clock, n) for n in names]
    for a, b in zip(names, names[1:]):
        radio.link(a, b)
    return nodes


def announce_all(radio):
    for n in radio.nodes.values():
        n.tick()
    radio.run()


def make_alert(severity=Severity.WATCH_AND_ACT, key=PUBLISHER):
    alert_id = os.urandom(16)
    args = (alert_id, HazardType.FLOOD, severity, ("r7hg",), "Flooding at Fitzroy Crossing",
            "Move to higher ground.", NOW, NOW + 24 * HOUR_MS)
    signature = key.sign(wire.alert_signing_bytes(*args))
    return OfficialAlert(alert_id, int(HazardType.FLOOD), severity, ("r7hg",), args[4], args[5],
                         NOW, NOW + 24 * HOUR_MS, signature)


def texts(n: Node, conversation=NEARBY):
    return [e.message.text for e in n.chats.conversations.get(conversation, node.Conversation(conversation)).entries]


# --- Frames


def test_frame_round_trips():
    frame = Frame(FrameKind.CHAT, 7, os.urandom(16), b"body")
    assert node.decode_frame(node.encode_frame(frame)) == frame


def test_bad_frames_are_ignored():
    good = node.encode_frame(Frame(FrameKind.CHAT, 7, os.urandom(16), b"body"))
    assert node.decode_frame(b"\x02" + good[1:]) is None        # unknown version
    assert node.decode_frame(good[:1] + b"\x99" + good[2:]) is None  # unknown kind
    assert node.decode_frame(good[:node.HEADER_LENGTH]) is None  # no body
    assert node.decode_frame(good + bytes(node.MAX_FRAME_BYTES)) is None  # too big


def test_kinds_use_the_iphone_numbers():
    assert (FrameKind.ANNOUNCE, FrameKind.CHAT, FrameKind.PRIVATE, FrameKind.OFFICIAL, FrameKind.REPORT) == \
        (0x01, 0x02, 0x11, 0x2D, 0x2E)


# --- Chat across the mesh


def test_nearby_message_reaches_c_through_b(radio, clock):
    a, b, c = line(radio, clock, "A", "B", "C")
    a.say("Bridge is under water")
    radio.run()
    assert texts(b) == texts(c) == ["Bridge is under water"]
    assert texts(a) == ["Bridge is under water"]
    assert a.chats.unread == 0 and c.chats.unread == 1


def test_message_in_a_ring_is_handled_once(radio, clock):
    a, b, c = line(radio, clock, "A", "B", "C")
    radio.link("C", "A")
    a.say("hello")
    radio.run()
    assert texts(b) == texts(c) == ["hello"]
    # A sent it once; B and C each passed it on once; nothing came round again.
    assert len(radio.sent) == 3


def test_ttl_stops_a_message(radio, clock):
    names = [f"N{i}" for i in range(12)]
    nodes = line(radio, clock, *names)
    nodes[0].say("far")
    radio.run()
    reached = [name for name, x in zip(names, nodes) if texts(x) == ["far"]]
    # 7 hops: N1..N7 hear it, N8 and beyond do not.
    assert reached == names[:8]


def test_forged_nearby_message_is_not_shown_or_passed_on(radio, clock):
    a, b, c = line(radio, clock, "A", "B", "C")
    message = a.identity.message("real", NOW)
    forged = chat.encode_message(message).replace(b"real", b"fake")
    b.receive(node.encode_frame(Frame(FrameKind.CHAT, 7, os.urandom(16), forged)))
    radio.run()
    assert texts(b) == [] and texts(c) == []


def test_announces_fill_the_people_nearby_list(radio, clock):
    a, b, c = line(radio, clock, "A", "B", "C")
    announce_all(radio)
    assert sorted(p.announce.nickname for p in a.nearby_peers()) == ["B", "C"]
    clock.now_ms += node.PEER_GONE_MS + 1
    assert a.nearby_peers() == []
    assert len(a.peers) == 2  # kept, for their chats


def test_private_message_reaches_only_its_recipient(radio, clock):
    a, b, c = line(radio, clock, "A", "B", "C")
    announce_all(radio)
    c_key = c.identity.signing_key.hex()
    a.say("meet at the school", to=c_key)
    radio.run()
    a_key = a.identity.signing_key.hex()
    assert texts(c, a_key) == ["meet at the school"]
    assert texts(a, c_key) == ["meet at the school"]
    assert b.chats.unread == 0 and set(b.chats.conversations) == {NEARBY}
    assert all(b"meet at the school" not in frame for _, frame in radio.sent)


def test_private_message_to_someone_never_announced_is_not_sent(radio, clock):
    (a,) = line(radio, clock, "A")
    assert a.say("hi", to="00" * 32) is None
    assert radio.sent == []


def test_reading_a_conversation_clears_its_unread_count(radio, clock):
    a, b = line(radio, clock, "A", "B")
    a.say("one")
    a.say("two")
    radio.run()
    assert b.chats.unread == 2
    b.mark_read(NEARBY)
    assert b.chats.unread == 0


def test_nickname_change_is_announced(radio, clock):
    a, b = line(radio, clock, "A", "B")
    announce_all(radio)
    clock.now_ms += 1000
    a.set_nickname("Aroha")
    a.tick()
    radio.run()
    assert [p.announce.nickname for p in b.nearby_peers()] == ["Aroha"]


# --- Warnings and reports across the mesh


def test_warning_from_wifi_reaches_laptops_without_wifi(radio, clock):
    a, b, c = line(radio, clock, "A", "B", "C")
    alert = make_alert()
    assert a.take_official(wire.encode(alert)).name == "ACCEPTED"
    radio.run()
    assert [x.alert_id for x in c.alerts.live_alerts()] == [alert.alert_id]


def test_repeated_warning_is_not_sent_again(radio, clock):
    a, b = line(radio, clock, "A", "B")
    payload = wire.encode(make_alert())
    a.take_official(payload)
    radio.run()
    count = len(radio.sent)
    assert a.take_official(payload).name == "DUPLICATE"
    assert len(radio.sent) == count


def test_forged_warning_stops_at_the_first_laptop(radio, clock):
    a, b, c = line(radio, clock, "A", "B", "C")
    forged = wire.encode(make_alert(key=Ed25519PrivateKey.generate()))
    b.receive(node.encode_frame(Frame(FrameKind.OFFICIAL, 7, os.urandom(16), forged)))
    radio.run()
    assert b.alerts.live_alerts() == [] and c.alerts.live_alerts() == []
    assert radio.sent == []


def test_call_for_help_reaches_c_and_im_safe_answers_it(radio, clock):
    a, b, c = line(radio, clock, "A", "B", "C")
    assert a.send_report(a.author.sos("r7hgf12", "Trapped on the roof", NOW))
    radio.run()
    assert [r.kind for r in c.reports.live_reports()] == [reports.ReportKind.SOS]
    clock.now_ms += 1000
    a.send_report(a.author.safe(None, "Rescued", clock.now_ms))
    radio.run()
    assert [r.kind for r in c.reports.live_reports()] == [reports.ReportKind.SAFE]


def test_gossip_brings_a_late_arrival_up_to_date(radio, clock):
    a, b = line(radio, clock, "A", "B")
    a.take_official(wire.encode(make_alert()))
    a.send_report(a.author.hazard(HazardType.FLOOD, reports.ReportSeverity.HIGH, "r7hgf12", "Road cut", NOW))
    a.tick()  # first gossip goes out at once
    radio.run()
    late = add(radio, clock, "Late")
    radio.link("B", "Late")
    clock.now_ms += node.GOSSIP_INTERVAL_MS
    b.tick()
    radio.run()
    assert len(late.alerts.live_alerts()) == 1 and len(late.reports.live_reports()) == 1


def test_version_goes_up_when_something_to_show_arrives(radio, clock):
    a, b = line(radio, clock, "A", "B")
    before = b.version
    a.say("hi")
    radio.run()
    assert b.version > before


def test_seen_list_is_bounded(radio, clock):
    (a,) = line(radio, clock, "A")
    for _ in range(node.SEEN_CAPACITY + 50):
        a.receive(node.encode_frame(Frame(FrameKind.CHAT, 7, os.urandom(16), b"x")))
    assert len(a._seen) == node.SEEN_CAPACITY
