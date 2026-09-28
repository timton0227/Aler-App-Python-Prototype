"""One laptop in a real mesh: what it keeps, what it shows, what it passes on.

Modelled on: alert-mesh/AlertMesh/Services/BLE/BLEService.swift (receive and relay),
             BLEIngressPacketGuard.swift (clock and duplicates), BLEAnnounceHandlingPolicy
             and BLEAnnounceHandler.swift (who is nearby), BLEPublicMessagePolicy and
             BLEPublicMessageHandler.swift (Nearby chat), RelayController.swift (TTL) and
             GossipSyncManager (neighbours swap what they hold).

Since Phase 16 the node speaks the iPhone app's Bluetooth packets (alertmesh/bitchat.py),
so laptops and iPhones share one mesh. The node knows nothing about radios. A link
(Bluetooth in `ble.py`, or a fake one in the tests) hands it each whole packet that
arrives with `receive()`, and the node hands packets to send to `link.send()`, which
sends them to every device in range. `link.neighbours()` says how many that is.

What it does with a packet, in the iPhone's order:
1. Drops it if it is not a packet, was seen before (sender, time, type and payload), is
   our own come back round, or its time is more than 2 minutes from this laptop's
   clock (the iPhone's rule: a laptop with a wrong clock is ignored by iPhones too).
2. Takes it in:
   - an announce ("I'm here", with nickname and keys) only if signed by the key it
     carries and its sender ID comes from its X25519 key. The first signing key seen
     for a sender ID is kept: a later announce with another key is refused;
   - a Nearby message (plain text) only from someone whose announce was taken, and
     only if signed by them;
   - a warning or report only if its store takes it (so a forged one stops here);
   - a laptop-only private message (type 0x70): opened if it is for us, else passed on
     unread. iPhones do not know the type and pass it on unread too;
   - a leave: the sender has gone, if signed by them;
   - fragments of a packet too big for one link: passed on, and put back together.
3. Passes it on with a smaller TTL (the RelayController rule, `mesh_sim.relay_ttl`),
   unchanged otherwise: the TTL is not signed. Types the laptop does not know (the
   iPhone's encrypted private messages, files) are passed on unread, as iPhones do.

All public methods take a lock: the radio calls in from its own thread while the page
reads from another.

This is free and unencumbered software released into the public domain.
"""
import hashlib
import random
import threading
from collections import OrderedDict
from dataclasses import dataclass, field

from alertmesh import bitchat, chat, reports, wire
from alertmesh.alert_store import AlertStore, IngestResult, _system_clock_ms
from alertmesh.bitchat import MessageType, Packet
from alertmesh.chat import ChatMessage, Identity
from alertmesh.mesh_sim import MESSAGE_TTL_DEFAULT, is_urgent, relay_ttl
from alertmesh.report_store import ReportStore

# The biggest packet the laptop makes: a sealed private message, with a recipient,
# its original size (when compressed) and a signature.
MAX_PACKET_BYTES = (bitchat.V1_HEADER_SIZE + bitchat.SENDER_ID_SIZE + bitchat.RECIPIENT_ID_SIZE + 2
                    + chat.SEALED_MAX_BYTES + bitchat.SIGNATURE_SIZE)
# Packets remembered, so each is handled once (the iPhone keeps 1000 for 5 minutes).
SEEN_CAPACITY = 1000
# A packet whose time is further than this from our clock is dropped (BLEIngressPacketGuard).
MAX_CLOCK_SKEW_MS = 120_000
# An announce older than this is not taken (BLEPacketFreshnessPolicy), nor a Nearby
# message older than 6 hours (TransportConfig.publicMessageMaxAge).
ANNOUNCE_MAX_AGE_MS = 900_000
MESSAGE_MAX_AGE_MS = 6 * 60 * 60 * 1000
# "I'm here" every 15 s or so: iPhones forget a peer not heard from for 45-60 s.
ANNOUNCE_INTERVAL_MS = 15_000
ANNOUNCE_JITTER_MS = 4_000
PEER_GONE_MS = 60_000
# A new link is greeted with an announce at once, but no more than once a second.
LINK_ANNOUNCE_GAP_MS = 1_000
# Every 60 s neighbours are sent every warning and report held, so a device that comes
# into range later still gets them (GossipSyncManager).
GOSSIP_INTERVAL_MS = 60_000
MAX_MESSAGES_PER_CONVERSATION = 500
NEARBY = "nearby"  # the conversation everyone in range shares
# Nearby messages above 99 bytes are compressed. If this computer's compression does
# not match Apple's (bitchat.APPLE_COMPRESSION_OK), iPhones would refuse them.
TEXT_MAX_BYTES = chat.TEXT_MAX_BYTES if bitchat.APPLE_COMPRESSION_OK else bitchat.SAFE_MESSAGE_BYTES
NICKNAME_MAX_BYTES = chat.NICKNAME_MAX_BYTES if bitchat.APPLE_COMPRESSION_OK else bitchat.SAFE_NICKNAME_BYTES


def message_id(sender_id: bytes, sent_at: int, text: str) -> bytes:
    """One ID for a Nearby message however it arrives (MeshMessageIdentity: sender,
    time and text), so copies are shown once."""
    return hashlib.sha256(f"{sender_id.hex()}|{sent_at}|{text}".encode()).digest()[:chat.MESSAGE_ID_LENGTH]


# --- Chat store ---------------------------------------------------------------


@dataclass(frozen=True)
class ChatEntry:
    message: ChatMessage
    outgoing: bool
    received_at: int


@dataclass
class Conversation:
    key: str  # NEARBY, or the other person's signing key in hex
    entries: list[ChatEntry] = field(default_factory=list)
    unread: int = 0


class ChatStore:
    """Conversations: Nearby, plus one per person written to or heard from privately
    (the iPhone app's ChatInboxView). Each message is kept once."""

    def __init__(self):
        self.conversations: dict[str, Conversation] = {NEARBY: Conversation(NEARBY)}
        self._ids: set[bytes] = set()

    def add(self, key: str, message: ChatMessage, outgoing: bool, now_ms: int) -> bool:
        if message.message_id in self._ids:
            return False
        self._ids.add(message.message_id)
        conversation = self.conversations.setdefault(key, Conversation(key))
        conversation.entries.append(ChatEntry(message, outgoing, now_ms))
        conversation.entries.sort(key=lambda e: (e.message.sent_at, e.received_at))
        if len(conversation.entries) > MAX_MESSAGES_PER_CONVERSATION:
            dropped = conversation.entries.pop(0)
            self._ids.discard(dropped.message.message_id)
        if not outgoing:
            conversation.unread += 1
        return True

    def mark_read(self, key: str) -> None:
        if key in self.conversations:
            self.conversations[key].unread = 0

    @property
    def unread(self) -> int:
        return sum(c.unread for c in self.conversations.values())


# --- People nearby ------------------------------------------------------------


@dataclass
class Peer:
    """Someone whose announce was taken: an iPhone, or a laptop."""

    peer_id: bytes
    announce: bitchat.Announcement
    last_heard: int
    announced_at: int  # the time on their latest announce

    @property
    def key(self) -> str:
        """Their conversation's key: the signing key, as private messages name it."""
        return self.announce.signing_key.hex()

    @property
    def signing_key(self) -> bytes:
        return self.announce.signing_key

    @property
    def chat_key(self) -> bytes:
        return self.announce.noise_key

    @property
    def nickname(self) -> str:
        return self.announce.nickname

    @property
    def is_laptop(self) -> bool:
        """Takes laptop-to-laptop private messages (its announce carries our marker)."""
        return self.announce.laptop


# --- The node -----------------------------------------------------------------


class Node:
    """One laptop. `link` sends packets; `clock` returns "now" in milliseconds."""

    def __init__(self, identity: Identity, link, clock=_system_clock_ms,
                 publisher_key: bytes | None = wire.PINNED_PUBLIC_KEY, rng: random.Random | None = None):
        self.identity = identity
        self.link = link
        self.clock = clock
        self.alerts = AlertStore(publisher_key, clock)
        self.reports = ReportStore(clock)
        self.chats = ChatStore()
        self.author = reports.ReportAuthor(identity.nickname, identity.signing_seed)
        self.peers: dict[str, Peer] = {}  # by signing key in hex
        self._peer_keys: dict[bytes, str] = {}  # sender ID -> signing key in hex (the first one seen)
        # Goes up whenever something the page shows changes, so it knows to redraw.
        self.version = 0
        # Told of every report the store takes (our own, heard, or from the internet), with
        # its signed bytes: the internet link puts calls for help online from here.
        self.on_report = None
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._fragments = bitchat.FragmentAssembler(lambda: self.clock() / 1000)
        self._next_announce = None
        self._last_link_announce = None
        self._last_gossip = None
        self._last_sent_at = 0
        self._rng = rng or random.Random()
        self._lock = threading.RLock()

    @property
    def peer_id(self) -> bytes:
        return self.identity.peer_id

    # --- Sending our own ---

    def _timestamp(self) -> int:
        """Now, but never the same millisecond twice: iPhones tell packets apart by it."""
        self._last_sent_at = max(self.clock(), self._last_sent_at + 1)
        return self._last_sent_at

    def _send(self, kind: int, payload: bytes, ttl: int = MESSAGE_TTL_DEFAULT) -> Packet | None:
        packet = self.identity.sign_packet(Packet(kind, self.peer_id, self._timestamp(), payload, ttl))
        raw = bitchat.encode(packet)
        if raw is None:
            return None
        self._mark_seen(bitchat.dedup_key(packet))
        self.link.send(raw)
        return packet

    def announce(self) -> None:
        """Say "I'm here": nickname, both keys, and that this is a laptop."""
        with self._lock:
            payload = bitchat.encode_announcement(bitchat.Announcement(
                self._nickname(), self.identity.chat_key, self.identity.signing_key, laptop=True))
            self._send(MessageType.ANNOUNCE, payload)

    def link_up(self) -> None:
        """A device has just linked up: announce at once, so it lists this laptop and takes
        its messages (the iPhone takes a message only from someone it has an announce
        from)."""
        with self._lock:
            now = self.clock()
            if self._last_link_announce is None or now - self._last_link_announce >= LINK_ANNOUNCE_GAP_MS:
                self._last_link_announce = now
                self.announce()

    def leave(self) -> None:
        """Say "I'm going", so devices nearby take this laptop off their lists at once."""
        with self._lock:
            self._send(MessageType.LEAVE, b"")

    def _nickname(self) -> str:
        nickname = self.identity.nickname.strip()
        while len(nickname.encode()) > NICKNAME_MAX_BYTES:
            nickname = nickname[:-1]
        return nickname

    def say(self, text: str, to: str | None = None) -> ChatMessage | None:
        """Send a chat message: to everyone nearby, or to one laptop (`to`, a peer key).
        None when the text is empty or too long, or that person is not a laptop that
        has announced (iPhones' private messages are encrypted in a way laptops do not
        speak)."""
        with self._lock:
            text = text.strip()
            if to is None:
                if not text or len(text.encode()) > TEXT_MAX_BYTES:
                    return None
                packet = self._send(MessageType.MESSAGE, text.encode())
                if packet is None:
                    return None
                message = ChatMessage(message_id(self.peer_id, packet.timestamp, text), self.identity.signing_key,
                                      self._nickname(), b"", text, packet.timestamp, packet.signature)
            else:
                peer = self.peers.get(to)
                if peer is None or not peer.is_laptop:
                    return None
                message = self.identity.message(text, self.clock(), to=peer)
                if message is None:
                    return None
                self._send(MessageType.LAPTOP_PRIVATE, chat.seal(chat.encode_message(message), peer.chat_key))
            self.chats.add(to or NEARBY, message, outgoing=True, now_ms=self.clock())
            self.version += 1
            return message

    def send_report(self, report: reports.CommunityReport | None) -> bool:
        """Send our own hazard report, call for help or "I'm safe" (made with `self.author`)."""
        with self._lock:
            if report is None:
                return False
            payload = reports.encode(report)
            if self.reports.ingest_payload(payload) is IngestResult.REJECTED:
                return False
            self._send(MessageType.COMMUNITY_REPORT, payload)
            self.version += 1
            self._report_arrived(payload)
            return True

    def take_official(self, payload: bytes) -> IngestResult:
        """A signed warning or cancellation from outside the mesh (the Wi-Fi link).
        Passed on over the mesh only if new, so repeats do not flood the air."""
        with self._lock:
            result = self.alerts.ingest_payload(payload)
            if result is IngestResult.ACCEPTED:
                self._send(MessageType.OFFICIAL_ALERT, payload)
                self.version += 1
            return result

    def take_report(self, payload: bytes) -> IngestResult:
        """A signed call for help or "I'm safe" from outside the mesh (the internet link).
        Passed on over the mesh only if new, so nearby devices with no internet get it."""
        with self._lock:
            result = self.reports.ingest_payload(payload)
            if result is IngestResult.ACCEPTED:
                self._send(MessageType.COMMUNITY_REPORT, payload)
                self.version += 1
                self._report_arrived(payload)
            return result

    def _report_arrived(self, payload: bytes) -> None:
        if self.on_report is not None:
            self.on_report(payload)

    def set_nickname(self, nickname: str) -> None:
        with self._lock:
            self.identity.nickname = nickname
            self.author.nickname = nickname
            self._next_announce = None  # tell people nearby at the next tick

    # --- Time ---

    def tick(self) -> None:
        """Call about once a second: announces, gossip, and forgetting people who left."""
        with self._lock:
            now = self.clock()
            if self._next_announce is None or now >= self._next_announce:
                self._next_announce = now + ANNOUNCE_INTERVAL_MS + self._rng.randint(-ANNOUNCE_JITTER_MS,
                                                                                    ANNOUNCE_JITTER_MS)
                self.announce()
            if self._last_gossip is None or now - self._last_gossip >= GOSSIP_INTERVAL_MS:
                self._last_gossip = now
                # TTL 1: to neighbours only. They pass on what is new at their own gossip.
                for payload in self.alerts.sync_candidates():
                    self._send(MessageType.OFFICIAL_ALERT, payload, ttl=1)
                for payload in self.reports.sync_candidates():
                    self._send(MessageType.COMMUNITY_REPORT, payload, ttl=1)

    def nearby_peers(self) -> list[Peer]:
        """People heard from recently, newest first. Others are kept for their chats."""
        with self._lock:
            now = self.clock()
            return sorted((p for p in self.peers.values() if now - p.last_heard <= PEER_GONE_MS),
                          key=lambda p: -p.last_heard)

    def peer_by_signing_key(self, signing_key: bytes) -> Peer | None:
        """The person behind a call for help or report, if they have announced."""
        with self._lock:
            return self.peers.get(signing_key.hex())

    # --- Receiving ---

    def receive(self, data: bytes) -> None:
        """A whole packet from a neighbour."""
        with self._lock:
            packet = bitchat.decode(data)
            if packet is None or not self._fresh_and_new(packet):
                return
            if packet.type == MessageType.FRAGMENT:
                self._relay(packet, data)
                whole = self._fragments.add(packet)
                if whole is not None:
                    self._take_whole(whole)
                return
            if self._handle(packet):
                self._relay(packet, data)

    def _take_whole(self, data: bytes) -> None:
        """A packet put back together from fragments: taken in, not passed on (its
        fragments already were)."""
        packet = bitchat.decode(data)
        if packet is not None and packet.type != MessageType.FRAGMENT and self._fresh_and_new(packet):
            self._handle(packet)

    def _fresh_and_new(self, packet: Packet) -> bool:
        """The iPhone's ingress guard: not ours, not seen, clock within 2 minutes, and not
        a catch-up answer nobody asked for."""
        if packet.sender_id == self.peer_id or packet.is_rsr:
            return False
        if abs(packet.timestamp - self.clock()) > MAX_CLOCK_SKEW_MS:
            return False
        key = bitchat.dedup_key(packet)
        if key in self._seen:
            return False
        self._mark_seen(key)
        return True

    def _relay(self, packet: Packet, data: bytes) -> None:
        if packet.recipient_id == self.peer_id:
            return  # it has arrived
        urgent = packet.type in (MessageType.OFFICIAL_ALERT, MessageType.COMMUNITY_REPORT) and \
            is_urgent(packet.type, packet.payload)
        next_ttl = relay_ttl(packet.ttl, self.link.neighbours(), urgent)
        if next_ttl is not None:
            self.link.send(bitchat.set_ttl(data, next_ttl))

    def _handle(self, packet: Packet) -> bool:
        """Take in one new packet. True to pass it on."""
        now = self.clock()
        kind = packet.type
        if kind == MessageType.ANNOUNCE:
            return self._take_announce(packet, now)
        if kind == MessageType.MESSAGE:
            return self._take_message(packet, now)
        if kind == MessageType.LAPTOP_PRIVATE:
            return self._take_private(packet, now)
        if kind == MessageType.LEAVE:
            peer = self._known(packet)
            if peer is None or not bitchat.verify(packet, peer.signing_key):
                return False
            peer.last_heard = 0
            self.version += 1
            return True
        if kind == MessageType.OFFICIAL_ALERT:
            accepted = self.alerts.ingest_payload(packet.payload) is IngestResult.ACCEPTED
        elif kind == MessageType.COMMUNITY_REPORT:
            accepted = self.reports.ingest_payload(packet.payload) is IngestResult.ACCEPTED
            if accepted:
                self._report_arrived(packet.payload)
        elif kind == MessageType.REQUEST_SYNC:
            return False  # for its neighbours only; our gossip already reaches them
        else:
            return True  # a type we do not read (encrypted, files): passed on, as iPhones do
        if accepted:
            self._heard(packet, now)
            self.version += 1
        return accepted

    def _take_announce(self, packet: Packet, now: int) -> bool:
        a = bitchat.decode_announcement(packet.payload)
        if a is None or bitchat.peer_id(a.noise_key) != packet.sender_id:
            return False
        if now - packet.timestamp > ANNOUNCE_MAX_AGE_MS or not bitchat.verify(packet, a.signing_key):
            return False
        key = a.signing_key.hex()
        if self._peer_keys.setdefault(packet.sender_id, key) != key:
            return False  # this sender ID came with another key before: keep the first
        held = self.peers.get(key)
        if held and packet.timestamp < held.announced_at:
            return False  # an old one, still travelling
        changed = held is None or held.announce != a or now - held.last_heard > PEER_GONE_MS
        self.peers[key] = Peer(packet.sender_id, a, now, packet.timestamp)
        if changed:
            self.version += 1
        return True

    def _take_message(self, packet: Packet, now: int) -> bool:
        if packet.recipient_id not in (None, bitchat.BROADCAST):
            return True  # a message for one device: not ours to read
        peer = self._known(packet)
        if peer is None or now - packet.timestamp > MESSAGE_MAX_AGE_MS or not bitchat.verify(packet, peer.signing_key):
            return False
        try:
            text = packet.payload.decode()
        except UnicodeDecodeError:
            return False
        peer.last_heard = now
        message = ChatMessage(message_id(packet.sender_id, packet.timestamp, text), peer.signing_key,
                              peer.nickname, b"", text, packet.timestamp, packet.signature)
        if text.strip() and self.chats.add(NEARBY, message, False, now):
            self.version += 1
        return True

    def _take_private(self, packet: Packet, now: int) -> bool:
        message = self.identity.open(packet.payload)
        if message is None:
            return True  # for someone else: pass it on
        peer = self.peers.get(message.sender_key.hex())
        if peer is not None:
            peer.last_heard = now
        if self.chats.add(message.sender_key.hex(), message, False, now):
            self.version += 1
        return False  # it has arrived; nobody else can read it anyway

    def _known(self, packet: Packet) -> Peer | None:
        key = self._peer_keys.get(packet.sender_id)
        return self.peers.get(key) if key else None

    def _heard(self, packet: Packet, now: int) -> None:
        peer = self._known(packet)
        if peer is not None and bitchat.verify(packet, peer.signing_key):
            peer.last_heard = now

    def _mark_seen(self, key: str) -> None:
        self._seen[key] = None
        while len(self._seen) > SEEN_CAPACITY:
            self._seen.popitem(last=False)

    # --- Reads for the page ---

    def mark_read(self, conversation: str) -> None:
        with self._lock:
            self.chats.mark_read(conversation)
