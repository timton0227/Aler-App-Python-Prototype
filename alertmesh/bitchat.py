"""The iPhone app's Bluetooth packets (bitchat's binary protocol), so laptops and iPhones
share one mesh.

Ported from: ../alert-mesh/localPackages/BitFoundation/Sources/BitFoundation/
             BinaryProtocol.swift (encode, decode), BitchatPacket.swift
             (toBinaryDataForSigning), MessagePadding.swift, CompressionUtil.swift,
             Constants.swift, FileTransferLimits.swift, MessageType.swift and
             PeerID.swift (init(publicKey:)).

A packet, all numbers big-endian:

    version 1 | type 1 | ttl 1 | timestamp 8 (ms) | flags 1 | payload length 2 (4 in v2)
    | sender ID 8 | [recipient ID 8] | [route: count 1 + 8 each, v2 only]
    | [original size 2 (4 in v2), when compressed] | payload | [signature 64]
    | [padding]

Flags: 0x01 has a recipient, 0x02 has a signature, 0x04 compressed, 0x08 has a route
(v2), 0x10 a reply to a catch-up request ("RSR"). A packet with no recipient is for
everyone. The payload length counts the payload and, when compressed, the original
size in front of it; nothing else.

The signature is Ed25519, made with the key the sender puts in its announce, over the
packet encoded with TTL 0, no signature, the RSR flag clear, compressed when due, and
padded. TTL and RSR change as the packet travels, so they are left out.

Compression: a payload of 100 bytes or more with few different byte values is
compressed (raw DEFLATE; Apple's COMPRESSION_ZLIB). The receiver rebuilds the signed
bytes with its own compressor, so a sender's compressor must give the same bytes as
the iPhone's; see step 16.2. A packet taken from the air keeps its compressed bytes
(`Packet.compressed`), so its signature is checked on exactly what was signed.

Padding (PKCS#7 style: n bytes of value n) fills a packet to 256, 512, 1024 or 2048
bytes. On the air only encrypted types are padded; the signed bytes always are.

This is free and unencumbered software released into the public domain.
"""
import hashlib
import os
import zlib
from dataclasses import dataclass, replace
from enum import IntEnum

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

# The iPhone app's Bluetooth service and its one characteristic (BLEService.swift). A
# Debug build uses the "testnet" service, a Release build the "mainnet" one; only a
# Debug build trusts the development key the warning app signs with, so Debug is the
# default. ALERTMESH_BLE_NETWORK=release switches.
SERVICE_UUID_DEBUG = "f47b5e2d-4a9e-4c5a-9b3f-8e1d2c3a4b5a"
SERVICE_UUID_RELEASE = "f47b5e2d-4a9e-4c5a-9b3f-8e1d2c3a4b5c"
CHARACTERISTIC_UUID = "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d"


def service_uuid() -> str:
    network = os.environ.get("ALERTMESH_BLE_NETWORK", "debug").strip().lower()
    return SERVICE_UUID_RELEASE if network in ("release", "mainnet") else SERVICE_UUID_DEBUG


V1_HEADER_SIZE = 14
V2_HEADER_SIZE = 16
SENDER_ID_SIZE = 8
RECIPIENT_ID_SIZE = 8
SIGNATURE_SIZE = 64


class Flags:
    HAS_RECIPIENT = 0x01
    HAS_SIGNATURE = 0x02
    IS_COMPRESSED = 0x04
    HAS_ROUTE = 0x08
    IS_RSR = 0x10


class MessageType(IntEnum):
    """MessageType.swift. Types this port does not handle are still relayed."""

    ANNOUNCE = 0x01
    MESSAGE = 0x02  # public chat: plain UTF-8
    LEAVE = 0x03
    NOISE_HANDSHAKE = 0x10
    NOISE_ENCRYPTED = 0x11
    FRAGMENT = 0x20
    REQUEST_SYNC = 0x21
    FILE_TRANSFER = 0x22
    OFFICIAL_ALERT = 0x2D
    COMMUNITY_REPORT = 0x2E
    # Ours, not the iPhone's: laptop-to-laptop private messages. iPhones do not know
    # this type, so they pass it on without reading it.
    LAPTOP_PRIVATE = 0x70


BROADCAST = b"\xff" * RECIPIENT_ID_SIZE  # also read as "for everyone"

# Compression (Constants.compressionThresholdBytes, CompressionUtil)
COMPRESSION_THRESHOLD = 100
COMPRESSION_LEVEL = 5  # Apple documents COMPRESSION_ZLIB as zlib level 5; checked in step 16.2
MAX_COMPRESSION_RATIO = 50_000.0

# Padding (MessagePadding)
BLOCK_SIZES = (256, 512, 1024, 2048)

# FileTransferLimits.maxFramedFileBytes: the largest payload length a packet may claim.
MAX_FRAMED_BYTES = 1024 * 1024 + (18 + 0xFFFF * 2) + V2_HEADER_SIZE + SENDER_ID_SIZE + RECIPIENT_ID_SIZE \
    + SIGNATURE_SIZE


@dataclass(frozen=True)
class Packet:
    type: int
    sender_id: bytes  # 8 bytes
    timestamp: int  # milliseconds since 1970
    payload: bytes  # always uncompressed
    ttl: int
    recipient_id: bytes | None = None
    signature: bytes | None = None
    version: int = 1
    route: tuple[bytes, ...] = ()
    is_rsr: bool = False
    # The payload as it came off the air, when it came compressed. Encoding reuses it,
    # so the signed bytes are the sender's, whatever compressor this computer has.
    compressed: bytes | None = None

    @property
    def is_broadcast(self) -> bool:
        return self.recipient_id is None or self.recipient_id == BROADCAST


# --- Padding ---------------------------------------------------------------------


def optimal_block_size(size: int) -> int:
    """The smallest block that holds the data plus 16 bytes, or the size itself."""
    for block in BLOCK_SIZES:
        if size + 16 <= block:
            return block
    return size


def pad(data: bytes, target: int) -> bytes:
    needed = target - len(data)
    if not 0 < needed <= 255:
        return data
    return data + bytes([needed]) * needed


def unpad(data: bytes) -> bytes:
    if not data:
        return data
    n = data[-1]
    if n == 0 or n > len(data) or data[-n:] != bytes([n]) * n:
        return data
    return data[:-n]


# --- Compression -----------------------------------------------------------------


def should_compress(data: bytes) -> bool:
    """Big enough, and few enough different byte values that it is not already
    compressed (CompressionUtil.shouldCompress)."""
    if len(data) < COMPRESSION_THRESHOLD:
        return False
    return len(set(data)) / min(len(data), 256) < 0.9


def compress(data: bytes) -> bytes | None:
    """Raw DEFLATE, or None when that would not make it smaller."""
    if len(data) < COMPRESSION_THRESHOLD:
        return None
    engine = zlib.compressobj(COMPRESSION_LEVEL, zlib.DEFLATED, -15)
    out = engine.compress(data) + engine.flush()
    return out if 0 < len(out) < len(data) else None


# Apple's own bytes for one text (from tools/cross_check_bitchat.py). A laptop must
# compress exactly as the iPhone does, or iPhones reject its long messages: the signed
# bytes they rebuild would differ. zlib at level 5 matched Apple on every text tried,
# but another zlib (zlib-ng, say, in some Windows builds) may not, so each start checks.
_APPLE_SAMPLE = (b"at is east rope phone power to closed go fire boat east rope , we dog bridge in 5pm in "
                 b"roof out oval nort",
                 bytes.fromhex("4dcab111c3201005d156b600a52e08cc093123f399e324da979d39d9976c0adac4d20c5cc31887fab7"
                               "5ae684789f9a56a8626f6e64a5f89b37965154c9de4a355ae7353e3f5cdad115e84e275d1e0f"))


def decompress(data: bytes, original_size: int) -> bytes | None:
    """At most `original_size` bytes back, as Apple's decoder writes into a buffer of
    that size; None if nothing comes out."""
    try:
        out = zlib.decompressobj(-15).decompress(data, original_size)
    except zlib.error:
        return None
    return out or None


# --- Encoding --------------------------------------------------------------------


def _id(value: bytes, size: int) -> bytes:
    return value[:size].ljust(size, b"\x00")


def encode(packet: Packet, padding: bool = False) -> bytes | None:
    """The packet as bytes (BinaryProtocol.encode). On the air the iPhone sends
    announces, messages, warnings and reports unpadded; `padding` is for the signed
    bytes and encrypted types."""
    version = packet.version
    if version not in (1, 2):
        return None
    length_size = 4 if version == 2 else 2

    payload, original_size = packet.payload, None
    if packet.compressed is not None:
        payload, original_size = packet.compressed, len(packet.payload)
    elif should_compress(packet.payload) and len(packet.payload) <= (0xFFFFFFFF if version == 2 else 0xFFFF):
        squeezed = compress(packet.payload)
        if squeezed is not None:
            payload, original_size = squeezed, len(packet.payload)

    route = [_id(hop, SENDER_ID_SIZE) for hop in packet.route] if version >= 2 else []
    if any(not hop for hop in packet.route if version >= 2) or len(route) > 255:
        return None
    payload_size = len(payload) + (length_size if original_size is not None else 0)
    if payload_size > (0xFFFFFFFF if version == 2 else 0xFFFF):
        return None

    flags = 0
    if packet.recipient_id is not None:
        flags |= Flags.HAS_RECIPIENT
    if packet.signature is not None:
        flags |= Flags.HAS_SIGNATURE
    if original_size is not None:
        flags |= Flags.IS_COMPRESSED
    if route:
        flags |= Flags.HAS_ROUTE
    if packet.is_rsr:
        flags |= Flags.IS_RSR

    out = bytearray([version, packet.type, packet.ttl])
    out += packet.timestamp.to_bytes(8, "big")
    out.append(flags)
    out += payload_size.to_bytes(length_size, "big")
    out += _id(packet.sender_id, SENDER_ID_SIZE)
    if packet.recipient_id is not None:
        out += _id(packet.recipient_id, RECIPIENT_ID_SIZE)
    if route:
        out.append(len(route))
        for hop in route:
            out += hop
    if original_size is not None:
        out += original_size.to_bytes(length_size, "big")
    out += payload
    if packet.signature is not None:
        out += packet.signature[:SIGNATURE_SIZE]
    data = bytes(out)
    return pad(data, optimal_block_size(len(data))) if padding else data


def decode(data: bytes) -> Packet | None:
    """A packet, or None. Bytes after the packet (padding) are ignored; if the bytes
    do not read as they are, they are read again without their padding."""
    packet = _decode_core(data)
    if packet is not None:
        return packet
    unpadded = unpad(data)
    return None if unpadded == data else _decode_core(unpadded)


def _decode_core(raw: bytes) -> Packet | None:
    if len(raw) < V1_HEADER_SIZE + SENDER_ID_SIZE:
        return None
    version = raw[0]
    if version not in (1, 2):
        return None
    length_size = 4 if version == 2 else 2
    header_size = V2_HEADER_SIZE if version == 2 else V1_HEADER_SIZE
    if len(raw) < header_size + SENDER_ID_SIZE:
        return None
    offset = 0

    def take(n: int) -> bytes | None:
        nonlocal offset
        if offset + n > len(raw):
            return None
        chunk = raw[offset:offset + n]
        offset += n
        return chunk

    def number(n: int) -> int | None:
        chunk = take(n)
        return None if chunk is None else int.from_bytes(chunk, "big")

    kind, ttl = raw[1], raw[2]
    offset = 3
    timestamp = number(8)
    flags = number(1)
    payload_length = number(length_size)
    if timestamp is None or flags is None or payload_length is None or payload_length > MAX_FRAMED_BYTES:
        return None
    has_route = version >= 2 and bool(flags & Flags.HAS_ROUTE)
    sender = take(SENDER_ID_SIZE)
    if sender is None:
        return None
    recipient = None
    if flags & Flags.HAS_RECIPIENT:
        recipient = take(RECIPIENT_ID_SIZE)
        if recipient is None:
            return None
    route: list[bytes] = []
    if has_route:
        count = number(1)
        if count is None:
            return None
        for _ in range(count):
            hop = take(SENDER_ID_SIZE)
            if hop is None:
                return None
            route.append(hop)

    compressed = None
    if flags & Flags.IS_COMPRESSED:
        if payload_length < length_size:
            return None
        original_size = number(length_size)
        if original_size is None or original_size > MAX_FRAMED_BYTES:
            return None
        compressed = take(payload_length - length_size) if payload_length > length_size else None
        if compressed is None or original_size / len(compressed) > MAX_COMPRESSION_RATIO:
            return None
        payload = decompress(compressed, original_size)
        if payload is None or len(payload) != original_size:
            return None
    else:
        payload = take(payload_length)
        if payload is None:
            return None

    signature = None
    if flags & Flags.HAS_SIGNATURE:
        signature = take(SIGNATURE_SIZE)
        if signature is None:
            return None
    return Packet(kind, sender, timestamp, payload, ttl, recipient, signature, version, tuple(route),
                  bool(flags & Flags.IS_RSR), compressed)


# --- Signatures ------------------------------------------------------------------


def signing_bytes(packet: Packet) -> bytes | None:
    """What the sender signs (toBinaryDataForSigning): TTL 0, no signature, RSR clear,
    padded."""
    return encode(replace(packet, ttl=0, signature=None, is_rsr=False), padding=True)


def sign(packet: Packet, private_key: Ed25519PrivateKey) -> Packet:
    """The packet with its signature. Its compressed bytes are fixed first, so the
    bytes signed are the bytes sent."""
    if packet.compressed is None and should_compress(packet.payload):
        packet = replace(packet, compressed=compress(packet.payload))
    return replace(packet, signature=private_key.sign(signing_bytes(packet)))


def verify(packet: Packet, public_key: bytes) -> bool:
    if packet.signature is None or len(public_key) != 32:
        return False
    data = signing_bytes(packet)
    if data is None:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(packet.signature, data)
        return True
    except (InvalidSignature, ValueError):
        return False


# --- Identity and bookkeeping ----------------------------------------------------


def peer_id(x25519_public_key: bytes) -> bytes:
    """The 8-byte peer ID the iPhone derives from a device's X25519 ("Noise static")
    public key: the first 8 bytes of its SHA-256 (PeerID(publicKey:))."""
    return hashlib.sha256(x25519_public_key).digest()[:8]


def set_ttl(raw: bytes, ttl: int) -> bytes:
    """Encoded packet bytes with another TTL. TTL is not signed, so the rest stays."""
    return raw[:2] + bytes([ttl]) + raw[3:]


def dedup_key(packet: Packet) -> str:
    """One per packet sent: sender, time, type and the start of the payload's SHA-256
    (BLEReceivePipeline), so packets sent in the same millisecond stay apart."""
    digest = hashlib.sha256(packet.payload).digest()[:4].hex()
    return f"{packet.sender_id.hex()}-{packet.timestamp}-{packet.type}-{digest}"



# --- Announce (AlertMesh/Protocols/Packets.swift, AnnouncementPacket) --------------------
#
# TLVs with a 1-byte type and a 1-byte length. The iPhone needs the first three, and
# skips types it does not know, so laptops add one of their own: 0x70, "this device
# takes laptop-to-laptop private messages".


class AnnounceTLV(IntEnum):
    NICKNAME = 0x01
    NOISE_KEY = 0x02  # X25519; the laptop's chat key
    SIGNING_KEY = 0x03  # Ed25519
    NEIGHBORS = 0x04  # peer IDs, 8 bytes each, at most 10
    CAPABILITIES = 0x05
    BRIDGE_GEOHASH = 0x06
    LAPTOP = 0x70  # ours


LAPTOP_MARKER = b"\x01"  # version 1 of the laptop private-message format


@dataclass(frozen=True)
class Announcement:
    nickname: str
    noise_key: bytes
    signing_key: bytes
    neighbors: tuple[bytes, ...] = ()
    capabilities: bytes | None = None
    bridge_geohash: str | None = None
    laptop: bool = False  # sent by a laptop: it can take private messages


def encode_announcement(a: Announcement) -> bytes | None:
    nickname = a.nickname.encode()
    if len(nickname) > 255 or len(a.noise_key) > 255 or len(a.signing_key) > 255:
        return None
    out = bytearray()
    for kind, value in ((AnnounceTLV.NICKNAME, nickname), (AnnounceTLV.NOISE_KEY, a.noise_key),
                        (AnnounceTLV.SIGNING_KEY, a.signing_key)):
        out += bytes([kind, len(value)]) + value
    neighbors = b"".join(a.neighbors[:10])
    if neighbors and len(neighbors) % 8 == 0:
        out += bytes([AnnounceTLV.NEIGHBORS, len(neighbors)]) + neighbors
    if a.capabilities is not None:
        if len(a.capabilities) > 255:
            return None
        out += bytes([AnnounceTLV.CAPABILITIES, len(a.capabilities)]) + a.capabilities
    if a.bridge_geohash:
        cell = a.bridge_geohash.encode()
        if len(cell) <= 12:
            out += bytes([AnnounceTLV.BRIDGE_GEOHASH, len(cell)]) + cell
    if a.laptop:
        out += bytes([AnnounceTLV.LAPTOP, len(LAPTOP_MARKER)]) + LAPTOP_MARKER
    return bytes(out)


def decode_announcement(data: bytes) -> Announcement | None:
    """None without a nickname (valid UTF-8), a noise key and a signing key."""
    fields: dict = {}
    offset = 0
    while offset + 2 <= len(data):
        kind, length = data[offset], data[offset + 1]
        offset += 2
        if offset + length > len(data):
            return None
        value = data[offset:offset + length]
        offset += length
        if kind == AnnounceTLV.NICKNAME:
            try:
                fields["nickname"] = value.decode()
            except UnicodeDecodeError:
                fields.pop("nickname", None)
        elif kind == AnnounceTLV.NOISE_KEY:
            fields["noise_key"] = value
        elif kind == AnnounceTLV.SIGNING_KEY:
            fields["signing_key"] = value
        elif kind == AnnounceTLV.NEIGHBORS and length and length % 8 == 0:
            fields["neighbors"] = tuple(value[i:i + 8] for i in range(0, length, 8))
        elif kind == AnnounceTLV.CAPABILITIES:
            fields["capabilities"] = value
        elif kind == AnnounceTLV.BRIDGE_GEOHASH and length <= 12:
            try:
                fields["bridge_geohash"] = value.decode()
            except UnicodeDecodeError:
                pass
        elif kind == AnnounceTLV.LAPTOP and value == LAPTOP_MARKER:
            fields["laptop"] = True
    if not {"nickname", "noise_key", "signing_key"} <= fields.keys():
        return None
    return Announcement(**fields)


# --- Catch-up request (AlertMesh/Models/RequestSyncPacket.swift, SyncTypeFlags.swift) ---
#
# "Send me what you hold that is not in this filter." TLVs with a 1-byte type and a
# 2-byte length. The filter is a Golomb-coded set of what the asker already has; an
# empty one (M = 1, no data) asks for everything, as the iPhone itself does when it
# holds nothing. The iPhone answers with its held packets, TTL 0, the RSR flag set.

SYNC_BITS = {MessageType.ANNOUNCE: 0, MessageType.MESSAGE: 1, MessageType.LEAVE: 2,
             MessageType.NOISE_HANDSHAKE: 3, MessageType.NOISE_ENCRYPTED: 4, MessageType.FRAGMENT: 5,
             MessageType.REQUEST_SYNC: 6, MessageType.FILE_TRANSFER: 7,
             MessageType.OFFICIAL_ALERT: 11, MessageType.COMMUNITY_REPORT: 12}
GCS_MAX_P = 32
GCS_P = 7  # GCSFilter.deriveP(targetFpr: 0.01)
SYNC_MAX_ACCEPT_BYTES = 1024


def sync_types(*types: MessageType) -> int:
    return sum(1 << SYNC_BITS[t] for t in set(types))


# What a laptop asks for on a new link: people nearby and their recent public chat, and
# the warnings and reports the other device holds.
CATCH_UP_TYPES = sync_types(MessageType.ANNOUNCE, MessageType.MESSAGE, MessageType.OFFICIAL_ALERT,
                            MessageType.COMMUNITY_REPORT)


@dataclass(frozen=True)
class RequestSync:
    p: int
    m: int
    data: bytes
    types: int | None = None  # SYNC_BITS; None means announces and messages
    since: int | None = None  # ms
    fragment_filter: str | None = None


def catch_up_request(types: int = CATCH_UP_TYPES) -> RequestSync:
    return RequestSync(GCS_P, 1, b"", types)


def _tlv16(kind: int, value: bytes) -> bytes:
    return bytes([kind]) + len(value).to_bytes(2, "big") + value


def _types_bytes(types: int) -> bytes:
    out = types.to_bytes(8, "little").rstrip(b"\x00")
    return out


def encode_request_sync(r: RequestSync) -> bytes:
    out = _tlv16(0x01, bytes([r.p & 0xFF])) + _tlv16(0x02, r.m.to_bytes(4, "big")) + _tlv16(0x03, r.data)
    if r.types:
        out += _tlv16(0x04, _types_bytes(r.types))
    if r.since is not None:
        out += _tlv16(0x05, r.since.to_bytes(8, "big"))
    if r.fragment_filter is not None:
        out += _tlv16(0x06, r.fragment_filter.encode())
    return out


def decode_request_sync(data: bytes, max_accept: int = SYNC_MAX_ACCEPT_BYTES) -> RequestSync | None:
    fields: dict = {}
    offset = 0
    while offset + 3 <= len(data):
        kind = data[offset]
        length = int.from_bytes(data[offset + 1:offset + 3], "big")
        offset += 3
        if offset + length > len(data):
            return None
        value = data[offset:offset + length]
        offset += length
        if kind == 0x01 and length == 1:
            fields["p"] = value[0]
        elif kind == 0x02 and length == 4:
            fields["m"] = int.from_bytes(value, "big")
        elif kind == 0x03:
            if length > max_accept:
                return None
            fields["data"] = value
        elif kind == 0x04 and 1 <= length <= 8:
            fields["types"] = int.from_bytes(value, "little") & sum(1 << b for b in SYNC_BITS.values())
        elif kind == 0x05 and length == 8:
            fields["since"] = int.from_bytes(value, "big")
        elif kind == 0x06 and length <= max_accept:
            try:
                fields["fragment_filter"] = value.decode()
            except UnicodeDecodeError:
                pass
    if not {"p", "m", "data"} <= fields.keys() or not 1 <= fields["p"] <= GCS_MAX_P or fields["m"] <= 0:
        return None
    return RequestSync(**fields)


# --- Fragments (BLEOutboundFragmentPlanner.swift, BLEFragmentAssemblyBuffer.swift) ------
#
# A packet too big for a link goes as several FRAGMENT packets. Each payload is
#     fragment ID 8 | index 2 | total 2 | original type 1 | a slice of the whole packet
# and the fragments carry the original's sender, time, TTL and route, unsigned. The
# whole packet is checked (signature and all) once it is put back together.

FRAGMENT_ID_SIZE = 8
FRAGMENT_HEADER_SIZE = 13
MIN_CHUNK = 64
MAX_FRAGMENTS = 10_000
FRAGMENT_LIFETIME_S = 30.0  # TransportConfig.bleFragmentLifetimeSeconds
MAX_ASSEMBLIES = 128  # TransportConfig.bleMaxInFlightAssemblies
MAX_ASSEMBLED_BYTES = 1024 * 1024  # FileTransferLimits.maxPayloadBytes
LINK_OVERHEAD = 42  # BLEOutboundPacketPolicy: chunk = max(64, link limit - 42)


def chunk_size_for(link_limit: int) -> int:
    return max(MIN_CHUNK, link_limit - LINK_OVERHEAD)


def split(packet: Packet, chunk_size: int, fragment_id: bytes | None = None) -> list[Packet]:
    """The packet (already signed) as fragments of at most `chunk_size` bytes of it."""
    whole = encode(packet)
    if whole is None:
        return []
    chunk_size = max(MIN_CHUNK, chunk_size)
    fragment_id = fragment_id or os.urandom(FRAGMENT_ID_SIZE)
    pieces = [whole[i:i + chunk_size] for i in range(0, len(whole), chunk_size)]
    return [Packet(MessageType.FRAGMENT, packet.sender_id, packet.timestamp,
                   fragment_id + index.to_bytes(2, "big") + len(pieces).to_bytes(2, "big") + bytes([packet.type])
                   + piece, packet.ttl, packet.recipient_id, None, 2 if packet.route else 1, packet.route,
                   packet.is_rsr)
            for index, piece in enumerate(pieces)]


@dataclass(frozen=True)
class FragmentHeader:
    key: tuple[bytes, bytes]  # (sender, fragment ID)
    index: int
    total: int
    original_type: int
    data: bytes


def fragment_header(packet: Packet) -> FragmentHeader | None:
    payload = packet.payload
    if len(payload) < FRAGMENT_HEADER_SIZE:
        return None
    index, total = int.from_bytes(payload[8:10], "big"), int.from_bytes(payload[10:12], "big")
    if not (0 < total <= MAX_FRAGMENTS and 0 <= index < total):
        return None
    return FragmentHeader((packet.sender_id, payload[:8]), index, total, payload[12], payload[13:])


class FragmentAssembler:
    """Puts fragments back together. `add` returns the whole packet's bytes when the
    last piece arrives. Unfinished packets are dropped after 30 seconds, and at most
    128 are held at once (the oldest goes first)."""

    def __init__(self, clock):
        self.clock = clock  # seconds
        self._pieces: dict[tuple, dict[int, bytes]] = {}
        self._started: dict[tuple, float] = {}

    def add(self, packet: Packet) -> bytes | None:
        header = fragment_header(packet)
        if header is None:
            return None
        now = self.clock()
        for key in [k for k, t in self._started.items() if now - t > FRAGMENT_LIFETIME_S]:
            self._drop(key)
        if header.key not in self._pieces:
            if len(self._pieces) >= MAX_ASSEMBLIES:
                self._drop(min(self._started, key=self._started.get))
            self._pieces[header.key], self._started[header.key] = {}, now
        pieces = self._pieces[header.key]
        limit = MAX_FRAMED_BYTES if header.original_type in (MessageType.FILE_TRANSFER,
                                                             MessageType.NOISE_ENCRYPTED) else MAX_ASSEMBLED_BYTES
        if sum(map(len, pieces.values())) + len(header.data) > limit:
            self._drop(header.key)
            return None
        pieces[header.index] = header.data
        if len(pieces) != header.total:
            return None
        self._drop(header.key)
        return b"".join(pieces[i] for i in range(header.total))

    def _drop(self, key) -> None:
        self._pieces.pop(key, None)
        self._started.pop(key, None)


# --- Notifications as a stream (AlertMesh/Services/NotificationStreamAssembler.swift) --
#
# Notifications from an iPhone are read as one stream of bytes and cut into packets by
# their headers, so a packet split over two notifications, or two packets in one, both
# come out right. Padding between packets is skipped; a packet still incomplete after
# 250 ms is dropped.

STREAM_STALL_S = 0.25  # TransportConfig.bleAssemblerStallResetMs
STREAM_HARD_CAP = 8 * 1024 * 1024  # TransportConfig.bleNotificationAssemblerHardCapBytes


def frame_length(buffer: bytes) -> int | None:
    """The length of the packet at the start of `buffer`, from its header; None when
    too little has arrived to tell, 0 when the header is not a packet's."""
    if not buffer:
        return None
    version = buffer[0]
    header_size = V2_HEADER_SIZE if version == 2 else V1_HEADER_SIZE
    prefix = header_size + SENDER_ID_SIZE
    if len(buffer) < prefix:
        return None
    flags = buffer[11]
    length = int.from_bytes(buffer[12:16] if version == 2 else buffer[12:14], "big")
    total = prefix + length
    if flags & Flags.HAS_RECIPIENT:
        total += RECIPIENT_ID_SIZE
    if flags & Flags.HAS_SIGNATURE:
        total += SIGNATURE_SIZE
    if version >= 2 and flags & Flags.HAS_ROUTE:
        at = prefix + (RECIPIENT_ID_SIZE if flags & Flags.HAS_RECIPIENT else 0)
        if len(buffer) <= at:
            return None
        total += 1 + buffer[at] * SENDER_ID_SIZE
    if flags & Flags.IS_COMPRESSED and length < (4 if version == 2 else 2):
        return 0
    return total if 0 < total <= STREAM_HARD_CAP else 0


class NotificationStream:
    def __init__(self, clock):
        self.clock = clock  # seconds
        self._buffer = b""
        self._waiting_since: float | None = None
        self._waiting_for = 0

    def _skip_padding(self) -> bool:
        if not self._buffer or self._buffer[0] in (1, 2):
            return False
        n = self._buffer[0]
        if n == 0 or n > len(self._buffer) or self._buffer[:n] != bytes([n]) * n:
            return False
        self._buffer = self._buffer[n:]
        self._waiting_since, self._waiting_for = None, 0
        return True

    def append(self, chunk: bytes) -> list[bytes]:
        """Whole packets that `chunk` completes, in order."""
        if not chunk:
            return []
        self._buffer += chunk
        if len(self._buffer) > STREAM_HARD_CAP:
            self._reset()
            return []
        frames = []
        now = self.clock()
        while len(self._buffer) >= V1_HEADER_SIZE + SENDER_ID_SIZE:
            if self._buffer[0] not in (1, 2):
                if not self._skip_padding():
                    self._buffer = self._buffer[1:]  # not the start of a packet
                    self._waiting_since, self._waiting_for = None, 0
                continue
            length = frame_length(self._buffer)
            if length is None:
                break
            if length == 0:
                self._reset()
                break
            if len(self._buffer) < length:
                if self._waiting_since is None or length != self._waiting_for:
                    self._waiting_since, self._waiting_for = now, length
                elif now - self._waiting_since >= STREAM_STALL_S:
                    self._reset()
                break
            frames.append(self._buffer[:length])
            self._buffer = self._buffer[length:]
            self._waiting_since, self._waiting_for = None, 0
            self._skip_padding()
        self._skip_padding()
        if self._buffer and not any(self._buffer):
            self._reset()
        return frames

    def _reset(self) -> None:
        self._buffer, self._waiting_since, self._waiting_for = b"", None, 0


# True when this computer compresses as Apple does. When it does not, the phone app
# keeps what it signs under the compression threshold (MESSAGE_MAX_BYTES), so nothing
# it signs is ever compressed.
APPLE_COMPRESSION_OK = compress(_APPLE_SAMPLE[0]) == _APPLE_SAMPLE[1]
# Chat text and nickname limits that keep a signed payload uncompressed (our announce is
# 73 bytes plus the nickname: three TLVs and the laptop marker).
SAFE_MESSAGE_BYTES = COMPRESSION_THRESHOLD - 1
SAFE_NICKNAME_BYTES = COMPRESSION_THRESHOLD - 1 - 73
