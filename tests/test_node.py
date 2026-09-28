"""Tests for alertmesh.node, with a fake radio instead of Bluetooth.

The node follows the iPhone app's receive rules (BLEIngressPacketGuard,
BLEAnnounceHandlingPolicy, BLEPublicMessagePolicy, RelayController); the cases below
port the ones that matter to a laptop: clock skew, duplicates, own echoes, announce
checks and key pinning, and signed Nearby messages from announced people only.
"""
import os
import random
from collections import deque

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from alertmesh import bitchat, node, reports, wire
from alertmesh.bitchat import MessageType, Packet
from alertmesh.chat import Identity
from alertmesh.node import NEARBY, Node
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
    """Laptops and who is in range of whom. Packets are delivered in order until quiet."""

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
            sender, raw = self.queue.popleft()
            for other in sorted(self.links[sender]):
                self.nodes[other].receive(raw)

    def kinds(self, name=None):
        return [bitchat.decode(raw).type for who, raw in self.sent if name in (None, who)]


class FakeLink:
    def __init__(self, radio: Radio, name: str):
        self.radio, self.name = radio, name

    def send(self, raw: bytes):
        self.radio.sent.append((self.name, raw))
        self.radio.queue.append((self.name, raw))

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
                             publisher_key=PUBLISHER.public_key().public_bytes_raw(), rng=random.Random(1))
    return radio.nodes[name]


def line(radio, clock, *names):
    """Laptops in a row, each in range of the next only."""
    nodes = [add(radio, clock, n) for n in names]
    for a, b in zip(names, names[1:]):
        radio.link(a, b)
    return nodes


def announce_all(radio):
    for n in radio.nodes.values():
        n.announce()
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


def packet_from(who: Identity, kind, payload: bytes, timestamp=NOW, ttl=7, sign=True) -> bytes:
    """A packet as another device (an iPhone, say) would send it."""
    p = Packet(kind, who.peer_id, timestamp, payload, ttl)
    return bitchat.encode(who.sign_packet(p) if sign else p)


def announce_of(who: Identity, timestamp=NOW, laptop=False, signing_key=None) -> bytes:
    payload = bitchat.encode_announcement(bitchat.Announcement(
        who.nickname, who.chat_key, signing_key or who.signing_key, laptop=laptop))
    return packet_from(who, MessageType.ANNOUNCE, payload, timestamp)


# --- Packets


def test_our_packets_are_the_iphones():
    radio, clock = Radio(), Clock()
    (a,) = line(radio, clock, "A")
    a.announce()
    a.say("hello")
    announce, message = (bitchat.decode(raw) for _, raw in radio.sent)
    assert (announce.type, announce.ttl, announce.sender_id) == (MessageType.ANNOUNCE, 7, a.identity.peer_id)
    parsed = bitchat.decode_announcement(announce.payload)
    assert (parsed.nickname, parsed.signing_key, parsed.laptop) == ("A", a.identity.signing_key, True)
    assert bitchat.verify(announce, a.identity.signing_key)
    assert (message.type, message.payload, message.recipient_id) == (MessageType.MESSAGE, b"hello", None)
    assert bitchat.verify(message, a.identity.signing_key)
    assert message.timestamp > announce.timestamp  # never two packets in one millisecond


def test_bad_packets_are_ignored(radio, clock):
    (a,) = line(radio, clock, "A")
    a.receive(b"not a packet")
    a.receive(b"")
    assert a.version == 0 and radio.sent == []


# --- Chat across the mesh


def test_nearby_message_reaches_c_through_b(radio, clock):
    a, b, c = line(radio, clock, "A", "B", "C")
    announce_all(radio)
    a.say("Bridge is under water")
    radio.run()
    assert texts(b) == texts(c) == ["Bridge is under water"]
    assert texts(a) == ["Bridge is under water"]
    assert a.chats.unread == 0 and c.chats.unread == 1


def test_message_in_a_ring_is_handled_once(radio, clock):
    a, b, c = line(radio, clock, "A", "B", "C")
    radio.link("C", "A")
    announce_all(radio)
    radio.sent.clear()
    a.say("hello")
    radio.run()
    assert texts(b) == texts(c) == ["hello"]
    # A sent it once; B and C each passed it on once; nothing came round again.
    assert len(radio.sent) == 3


def test_ttl_stops_a_message(radio, clock):
    names = [f"N{i}" for i in range(12)]
    nodes = line(radio, clock, *names)
    announce_all(radio)
    nodes[0].say("far")
    radio.run()
    reached = [name for name, x in zip(names, nodes) if texts(x) == ["far"]]
    # 7 hops: N1..N7 hear it, N8 and beyond do not.
    assert reached == names[:8]


def test_forged_nearby_message_is_not_shown_or_passed_on(radio, clock):
    a, b, c = line(radio, clock, "A", "B", "C")
    announce_all(radio)
    radio.sent.clear()
    real = a.identity.sign_packet(Packet(MessageType.MESSAGE, a.peer_id, NOW + 5, b"real", 7))
    b.receive(bitchat.encode(Packet(MessageType.MESSAGE, a.peer_id, NOW + 5, b"fake", 7, signature=real.signature)))
    radio.run()
    assert texts(b) == [] and texts(c) == [] and radio.sent == []


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
    announce_all(radio)
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
    b.receive(packet_from(Identity("Forger"), MessageType.OFFICIAL_ALERT, forged))
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
    announce_all(radio)
    before = b.version
    a.say("hi")
    radio.run()
    assert b.version > before


def test_seen_list_is_bounded(radio, clock):
    (a,) = line(radio, clock, "A")
    stranger = Identity("Stranger")
    for i in range(node.SEEN_CAPACITY + 50):
        a.receive(packet_from(stranger, MessageType.MESSAGE, b"x", NOW + i))
    assert len(a._seen) == node.SEEN_CAPACITY


# --- The iPhone's receive rules (BLEIngressPacketGuard, BLEAnnounceHandlingPolicy,
#     BLEPublicMessagePolicy)

IPHONE = Identity("9vision")


def test_an_iphone_is_listed_and_its_nearby_message_shown(radio, clock):
    (a,) = line(radio, clock, "A")
    a.receive(announce_of(IPHONE))
    a.receive(packet_from(IPHONE, MessageType.MESSAGE, "Checking from iphone".encode(), NOW + 1))
    (peer,) = a.nearby_peers()
    assert (peer.nickname, peer.is_laptop, peer.peer_id) == ("9vision", False, IPHONE.peer_id)
    assert texts(a) == ["Checking from iphone"]
    (entry,) = a.chats.conversations[NEARBY].entries
    assert entry.message.sender_nickname == "9vision" and not entry.outgoing


def test_a_message_from_someone_never_announced_is_dropped(radio, clock):
    (a,) = line(radio, clock, "A")
    a.receive(packet_from(IPHONE, MessageType.MESSAGE, b"who am I", NOW))
    assert texts(a) == []


def test_an_unsigned_message_is_dropped(radio, clock):
    (a,) = line(radio, clock, "A")
    a.receive(announce_of(IPHONE))
    a.receive(packet_from(IPHONE, MessageType.MESSAGE, b"unsigned", NOW + 1, sign=False))
    assert texts(a) == []


@pytest.mark.parametrize("skew", [-node.MAX_CLOCK_SKEW_MS - 1, node.MAX_CLOCK_SKEW_MS + 1])
def test_a_packet_more_than_2_minutes_off_our_clock_is_dropped(radio, clock, skew):
    (a,) = line(radio, clock, "A")
    a.receive(announce_of(IPHONE, NOW + skew))
    assert a.peers == {}
    a.receive(announce_of(IPHONE, NOW + node.MAX_CLOCK_SKEW_MS))
    assert len(a.peers) == 1


def test_an_announce_whose_sender_is_not_its_key_is_dropped(radio, clock):
    (a,) = line(radio, clock, "A")
    other = Identity("Other")
    payload = bitchat.encode_announcement(bitchat.Announcement("9vision", other.chat_key, IPHONE.signing_key))
    a.receive(packet_from(IPHONE, MessageType.ANNOUNCE, payload))
    assert a.peers == {}


def test_an_announce_signed_by_another_key_is_dropped(radio, clock):
    (a,) = line(radio, clock, "A")
    a.receive(announce_of(IPHONE, signing_key=Identity().signing_key))
    assert a.peers == {}


def test_the_first_signing_key_for_a_sender_is_kept(radio, clock):
    """Key pinning: someone else cannot take over a sender ID with their own key."""
    (a,) = line(radio, clock, "A")
    a.receive(announce_of(IPHONE))
    thief = Identity("thief", os.urandom(32) + IPHONE.seed[32:])  # same X25519 key, other Ed25519
    a.receive(announce_of(thief, NOW + 10))
    assert [p.signing_key for p in a.peers.values()] == [IPHONE.signing_key]
    a.receive(packet_from(thief, MessageType.MESSAGE, b"it's me", NOW + 11))
    assert texts(a) == []


def test_our_own_packets_coming_back_are_dropped(radio, clock):
    a, b = line(radio, clock, "A", "B")
    a.announce()
    radio.run()
    assert b.peers and not a.peers


def test_an_iphone_is_offered_no_private_chat(radio, clock):
    (a,) = line(radio, clock, "A")
    a.receive(announce_of(IPHONE))
    assert a.say("psst", to=IPHONE.signing_key.hex()) is None


def test_a_leave_takes_someone_off_the_list(radio, clock):
    a, b = line(radio, clock, "A", "B")
    announce_all(radio)
    assert [p.nickname for p in b.nearby_peers()] == ["A"]
    a.leave()
    radio.run()
    assert b.nearby_peers() == [] and len(b.peers) == 1


def test_a_forged_leave_is_ignored(radio, clock):
    (a,) = line(radio, clock, "A")
    a.receive(announce_of(IPHONE))
    a.receive(packet_from(IPHONE, MessageType.LEAVE, b"", NOW + 1, sign=False))
    assert len(a.nearby_peers()) == 1


def test_relaying_changes_only_the_ttl(radio, clock):
    a, b, c = line(radio, clock, "A", "B", "C")
    b.receive(announce_of(IPHONE))
    raw = packet_from(IPHONE, MessageType.MESSAGE, b"pass me on", NOW + 1)
    b.receive(raw)
    (relayed,) = [r for who, r in radio.sent if who == "B"][1:]
    assert relayed == raw[:2] + bytes([6]) + raw[3:]


def test_types_the_laptop_does_not_read_are_passed_on_unread(radio, clock):
    a, b, c = line(radio, clock, "A", "B", "C")
    noise = packet_from(IPHONE, MessageType.NOISE_ENCRYPTED, os.urandom(120), NOW)
    b.receive(noise)
    assert radio.kinds("B") == [MessageType.NOISE_ENCRYPTED]


def test_catch_up_requests_are_not_passed_on(radio, clock):
    a, b, c = line(radio, clock, "A", "B", "C")
    b.receive(packet_from(IPHONE, MessageType.REQUEST_SYNC,
                          bitchat.encode_request_sync(bitchat.catch_up_request()), NOW, ttl=0))
    assert radio.sent == []


def test_a_warning_cut_into_fragments_is_put_back_together(radio, clock):
    a, b, c = line(radio, clock, "A", "B", "C")
    whole = IPHONE.sign_packet(Packet(MessageType.OFFICIAL_ALERT, IPHONE.peer_id, NOW, wire.encode(make_alert()), 7))
    for piece in bitchat.split(whole, 64):
        b.receive(bitchat.encode(piece))
    radio.run()
    assert len(b.alerts.live_alerts()) == len(c.alerts.live_alerts()) == 1
    assert set(radio.kinds("B")) == {MessageType.FRAGMENT}  # the pieces were passed on, not the whole


def test_a_message_too_long_for_one_packet_is_refused(radio, clock):
    (a,) = line(radio, clock, "A")
    assert a.say("x" * (node.TEXT_MAX_BYTES + 1)) is None
    assert a.say("x" * node.TEXT_MAX_BYTES) is not None
