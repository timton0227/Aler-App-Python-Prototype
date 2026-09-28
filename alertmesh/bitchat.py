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
import zlib
from dataclasses import dataclass, replace
from enum import IntEnum

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

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
