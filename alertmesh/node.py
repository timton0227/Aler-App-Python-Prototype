"""One laptop in a real mesh: what it keeps, what it shows, what it passes on.

Modelled on: ../alert-mesh/AlertMesh/Services/BLE/BLEService.swift (relay with TTL,
             announces, handling each message type),
             ../alert-mesh/AlertMesh/Services/MessageDeduplicationService.swift (each
             packet handled once) and GossipSyncManager (neighbours swap what they hold).

The node knows nothing about radios. A link (Bluetooth in `ble.py`, or a fake one in the
tests) hands it the frames that arrive with `receive()`, and the node hands frames to
send to `link.send()`, which sends them to every laptop in range. `link.neighbours()`
says how many that is.

A frame is: version (1 byte), kind (1), TTL (1), packet ID (16), then the body. The
kinds reuse the iPhone app's message type numbers, so `mesh_sim.is_urgent` works on
them. Every laptop handles each packet ID once and passes it on with a smaller TTL (the
same rule as `mesh_sim.relay_ttl`), so a message crosses up to 7 laptops and never goes
round in circles.

What is passed on is checked first, like the app: a warning only if the warning store
accepted it (so a forged warning stops at the first laptop), a report only if the
report store accepted it, a Nearby message only if its signature is good. A private
message for someone else cannot be checked (it is locked), so it is passed on as is.

All public methods take a lock: the radio calls in from its own thread while the page
reads from another.

This is free and unencumbered software released into the public domain.
"""
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import IntEnum

from alertmesh import chat, reports, wire
from alertmesh.alert_store import AlertStore, IngestResult, _system_clock_ms
from alertmesh.chat import Announce, ChatMessage, Identity
from alertmesh.mesh_sim import COMMUNITY_REPORT_TYPE, MESSAGE_TTL_DEFAULT, OFFICIAL_ALERT_TYPE, is_urgent, relay_ttl
from alertmesh.report_store import ReportStore

FRAME_VERSION = 1
PACKET_ID_LENGTH = 16
HEADER_LENGTH = 3 + PACKET_ID_LENGTH
# The biggest body is a sealed private message; warnings and reports are smaller.
MAX_FRAME_BYTES = HEADER_LENGTH + chat.SEALED_MAX_BYTES
# Packet IDs remembered, so each packet is handled once (the app keeps 1000).
SEEN_CAPACITY = 1000
# "I'm here" every 30 s; someone not heard from for 3 announces has gone.
ANNOUNCE_INTERVAL_MS = 30_000
PEER_GONE_MS = 3 * ANNOUNCE_INTERVAL_MS + 5_000
# Every 60 s neighbours are sent every warning and report held, so a laptop that comes
# into range later still gets them (GossipSyncManager).
GOSSIP_INTERVAL_MS = 60_000
MAX_MESSAGES_PER_CONVERSATION = 500
NEARBY = "nearby"  # the conversation everyone in range shares


class FrameKind(IntEnum):
    """The iPhone app's numbers (BitFoundation MessageType). Frozen."""

    ANNOUNCE = 0x01
    CHAT = 0x02
    PRIVATE = 0x11
    OFFICIAL = OFFICIAL_ALERT_TYPE  # 0x2D
    REPORT = COMMUNITY_REPORT_TYPE  # 0x2E


@dataclass(frozen=True)
class Frame:
    kind: int
    ttl: int
    packet_id: bytes
    body: bytes


def encode_frame(frame: Frame) -> bytes:
    return bytes([FRAME_VERSION, frame.kind, frame.ttl]) + frame.packet_id + frame.body


def decode_frame(data: bytes) -> Frame | None:
    if not HEADER_LENGTH < len(data) <= MAX_FRAME_BYTES or data[0] != FRAME_VERSION:
        return None
    if data[1] not in FrameKind._value2member_map_:
        return None
    return Frame(data[1], data[2], data[3:HEADER_LENGTH], data[HEADER_LENGTH:])


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
    announce: Announce
    last_heard: int

    @property
    def key(self) -> str:
        return self.announce.signing_key.hex()


# --- The node -----------------------------------------------------------------


class Node:
    """One laptop. `link` sends frames; `clock` returns "now" in milliseconds."""

    def __init__(self, identity: Identity, link, clock=_system_clock_ms,
                 publisher_key: bytes | None = wire.PINNED_PUBLIC_KEY):
        self.identity = identity
        self.link = link
        self.clock = clock
        self.alerts = AlertStore(publisher_key, clock)
        self.reports = ReportStore(clock)
        self.chats = ChatStore()
        self.author = reports.ReportAuthor(identity.nickname, identity.signing_seed)
        self.peers: dict[str, Peer] = {}
        # Goes up whenever something the page shows changes, so it knows to redraw.
        self.version = 0
        self._seen: OrderedDict[bytes, None] = OrderedDict()
        self._last_announce = None
        self._last_gossip = None
        self._lock = threading.RLock()

    # --- Sending our own ---

    def _broadcast(self, kind: FrameKind, body: bytes, ttl: int = MESSAGE_TTL_DEFAULT) -> None:
        packet_id = os.urandom(PACKET_ID_LENGTH)
        self._mark_seen(packet_id)
        self.link.send(encode_frame(Frame(kind, ttl, packet_id, body)))

    def say(self, text: str, to: str | None = None) -> ChatMessage | None:
        """Send a chat message: to everyone nearby, or to one person (`to`, a peer key).
        None when the text is empty or too long, or that person has never announced."""
        with self._lock:
            now = self.clock()
            if to is None:
                message = self.identity.message(text, now)
                if message is None:
                    return None
                self._broadcast(FrameKind.CHAT, chat.encode_message(message))
            else:
                peer = self.peers.get(to)
                message = self.identity.message(text, now, to=peer.announce) if peer else None
                if message is None:
                    return None
                self._broadcast(FrameKind.PRIVATE, chat.seal(chat.encode_message(message), peer.announce.chat_key))
            self.chats.add(to or NEARBY, message, outgoing=True, now_ms=now)
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
            self._broadcast(FrameKind.REPORT, payload)
            self.version += 1
            return True

    def take_official(self, payload: bytes) -> IngestResult:
        """A signed warning or cancellation from outside the mesh (the Wi-Fi link).
        Passed on over the mesh only if new, so repeats do not flood the air."""
        with self._lock:
            result = self.alerts.ingest_payload(payload)
            if result is IngestResult.ACCEPTED:
                self._broadcast(FrameKind.OFFICIAL, payload)
                self.version += 1
            return result

    def set_nickname(self, nickname: str) -> None:
        with self._lock:
            self.identity.nickname = nickname
            self.author.nickname = nickname
            self._last_announce = None  # tell people nearby at the next tick

    # --- Time ---

    def tick(self) -> None:
        """Call about once a second: announces, gossip, and forgetting people who left."""
        with self._lock:
            now = self.clock()
            if self._last_announce is None or now - self._last_announce >= ANNOUNCE_INTERVAL_MS:
                self._last_announce = now
                self._broadcast(FrameKind.ANNOUNCE, chat.encode_announce(self.identity.announce(now)))
            if self._last_gossip is None or now - self._last_gossip >= GOSSIP_INTERVAL_MS:
                self._last_gossip = now
                # TTL 1: to neighbours only. They pass on what is new at their own gossip.
                for payload in self.alerts.sync_candidates():
                    self._broadcast(FrameKind.OFFICIAL, payload, ttl=1)
                for payload in self.reports.sync_candidates():
                    self._broadcast(FrameKind.REPORT, payload, ttl=1)

    def nearby_peers(self) -> list[Peer]:
        """People heard from recently, newest first. Others are kept for their chats."""
        with self._lock:
            now = self.clock()
            return sorted((p for p in self.peers.values() if now - p.last_heard <= PEER_GONE_MS),
                          key=lambda p: -p.last_heard)

    # --- Receiving ---

    def receive(self, data: bytes) -> None:
        """A frame from a neighbour."""
        with self._lock:
            frame = decode_frame(data)
            if frame is None or frame.packet_id in self._seen:
                return
            self._mark_seen(frame.packet_id)
            if self._handle(frame):
                next_ttl = relay_ttl(frame.ttl, self.link.neighbours(), is_urgent(frame.kind, frame.body))
                if next_ttl is not None:
                    self.link.send(encode_frame(Frame(frame.kind, next_ttl, frame.packet_id, frame.body)))

    def _handle(self, frame: Frame) -> bool:
        """Take in one new frame. True to pass it on."""
        now = self.clock()
        if frame.kind == FrameKind.ANNOUNCE:
            announce = chat.decode_announce(frame.body)
            if announce is None or not chat.verify_announce(announce):
                return False
            if announce.signing_key == self.identity.signing_key:
                return False  # our own, come back round
            key = announce.signing_key.hex()
            held = self.peers.get(key)
            if held and announce.sent_at < held.announce.sent_at:
                return False  # an old one, still travelling
            self.peers[key] = Peer(announce, now)
            self.version += 1
            return True
        if frame.kind == FrameKind.CHAT:
            message = chat.decode_message(frame.body)
            if message is None or message.is_private or not chat.verify_message(message):
                return False
            self._heard_from(message.sender_key, now)
            if message.sender_key != self.identity.signing_key and self.chats.add(NEARBY, message, False, now):
                self.version += 1
            return True
        if frame.kind == FrameKind.PRIVATE:
            message = self.identity.open(frame.body)
            if message is None:
                return True  # for someone else: pass it on
            self._heard_from(message.sender_key, now)
            if self.chats.add(message.sender_key.hex(), message, False, now):
                self.version += 1
            return False  # it has arrived; nobody else can read it anyway
        if frame.kind == FrameKind.OFFICIAL:
            accepted = self.alerts.ingest_payload(frame.body) is IngestResult.ACCEPTED
        else:
            accepted = self.reports.ingest_payload(frame.body) is IngestResult.ACCEPTED
        if accepted:
            self.version += 1
        return accepted

    def _heard_from(self, signing_key: bytes, now: int) -> None:
        peer = self.peers.get(signing_key.hex())
        if peer:
            peer.last_heard = now

    def _mark_seen(self, packet_id: bytes) -> None:
        self._seen[packet_id] = None
        while len(self._seen) > SEEN_CAPACITY:
            self._seen.popitem(last=False)

    # --- Reads for the page ---

    def mark_read(self, conversation: str) -> None:
        with self._lock:
            self.chats.mark_read(conversation)
