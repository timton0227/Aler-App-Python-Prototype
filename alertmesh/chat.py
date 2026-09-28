"""Chat: each person's keys, and laptop-to-laptop private messages.

Modelled on: ../alert-mesh/localPackages/BitFoundation/Sources/BitFoundation/MessageType.swift
             (`announce`, `message`, `noiseEncrypted`) and
             ../alert-mesh/AlertMesh/Services/PrivateChatManager.swift
Since Phase 16 announces and Nearby messages go in the iPhone app's own packets
(alertmesh/bitchat.py, alertmesh/node.py), so iPhones and laptops chat in public.
Private messages stay between laptops: iPhones encrypt theirs with Noise, which laptops
do not speak. A laptop sends its sealed messages in a packet type iPhones do not know
(0x70), which they pass on unread. The announce and message formats below (TLVs signed
on their own) were the laptops' own wire format before; a sealed private message still
carries a signed message inside.

Each person has two keys, like the iPhone app:
- a signing key (Ed25519), which says who wrote a message. It is the person's identity;
- a chat key (X25519), which lets others encrypt private messages to them. The iPhone
  app uses its Noise key here.
An announce tells people nearby your nickname and both keys, signed by you.

A **Nearby** message is signed and readable by everyone in range, like the iPhone's
Nearby chat. A **private** message is also signed, names its recipient, and is then
sealed so only the recipient's chat key can open it: an X25519 key made for this one
message, HKDF-SHA256, then ChaCha20-Poly1305. Relays pass it on without reading it.
This is simpler than the iPhone's Noise sessions: no handshake, and no forward secrecy
for the recipient's key.

This is free and unencumbered software released into the public domain.
"""
import os
from dataclasses import dataclass
from enum import IntEnum

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from alertmesh import bitchat
from alertmesh.wire import _context, _ed25519_ok, _len16, _u64, _u64_from, _utf8, put_tlv, read_tlvs

# --- Constants ----------------------------------------------------------------

MESSAGE_ID_LENGTH = 16
KEY_LENGTH = 32
SIGNATURE_LENGTH = 64
# About a text message's worth. Keeps each message a few Bluetooth writes long.
TEXT_MAX_BYTES = 280
NICKNAME_MAX_BYTES = 32
ANNOUNCE_CONTEXT = "alertmesh-announce-v1"
CHAT_CONTEXT = "alertmesh-chat-v1"
PRIVATE_INFO = b"alertmesh-private-v1"
NONCE_LENGTH = 12
# Sealed private message: one-off public key, nonce, then the encrypted message and its tag.
SEALED_OVERHEAD = KEY_LENGTH + NONCE_LENGTH + 16
# The largest message: 7 fields of 3 header bytes, each at its largest.
MESSAGE_MAX_BYTES = 7 * 3 + MESSAGE_ID_LENGTH + 2 * KEY_LENGTH + NICKNAME_MAX_BYTES + TEXT_MAX_BYTES + 8 + SIGNATURE_LENGTH
SEALED_MAX_BYTES = MESSAGE_MAX_BYTES + SEALED_OVERHEAD


class AnnounceTLVType(IntEnum):
    SIGNING_KEY = 0x01
    CHAT_KEY = 0x02
    NICKNAME = 0x03
    SENT_AT = 0x04
    SIGNATURE = 0x05


class ChatTLVType(IntEnum):
    MESSAGE_ID = 0x01
    SENDER_KEY = 0x02
    SENDER_NICKNAME = 0x03
    RECIPIENT_KEY = 0x04
    TEXT = 0x05
    SENT_AT = 0x06
    SIGNATURE = 0x07


# --- Announce -----------------------------------------------------------------


@dataclass(frozen=True)
class Announce:
    """"I'm here": who a nearby person is. Times are milliseconds since 1970."""

    signing_key: bytes
    chat_key: bytes
    nickname: str
    sent_at: int
    signature: bytes


def announce_signing_bytes(signing_key: bytes, chat_key: bytes, nickname: str, sent_at: int) -> bytes:
    return _context(ANNOUNCE_CONTEXT) + signing_key + chat_key + _len16(nickname.encode()) + _u64(sent_at)


def encode_announce(announce: Announce) -> bytes:
    out = put_tlv(AnnounceTLVType.SIGNING_KEY, announce.signing_key)
    out += put_tlv(AnnounceTLVType.CHAT_KEY, announce.chat_key)
    out += put_tlv(AnnounceTLVType.NICKNAME, announce.nickname.encode())
    out += put_tlv(AnnounceTLVType.SENT_AT, _u64(announce.sent_at))
    out += put_tlv(AnnounceTLVType.SIGNATURE, announce.signature)
    return out


def decode_announce(data: bytes) -> Announce | None:
    """Read an announce, or None if malformed. Structure only: call `verify_announce()`."""
    fields = read_tlvs(data, {t.value for t in AnnounceTLVType})
    if fields is None:
        return None
    values = {}
    for t, v in fields:
        if t in (AnnounceTLVType.SIGNING_KEY, AnnounceTLVType.CHAT_KEY) and len(v) != KEY_LENGTH:
            return None
        if t == AnnounceTLVType.NICKNAME and (len(v) > NICKNAME_MAX_BYTES or _utf8(v) is None):
            return None
        if t == AnnounceTLVType.SIGNATURE and len(v) != SIGNATURE_LENGTH:
            return None
        values[t] = v
    if len(values) != len(AnnounceTLVType):
        return None
    sent_at = _u64_from(values[AnnounceTLVType.SENT_AT])
    if sent_at is None:
        return None
    return Announce(values[AnnounceTLVType.SIGNING_KEY], values[AnnounceTLVType.CHAT_KEY],
                    _utf8(values[AnnounceTLVType.NICKNAME]), sent_at, values[AnnounceTLVType.SIGNATURE])


def verify_announce(announce: Announce) -> bool:
    """Signed by the signing key it names. Proves the two keys belong together; says
    nothing about who the person really is (anyone can pick any nickname)."""
    message = announce_signing_bytes(announce.signing_key, announce.chat_key, announce.nickname, announce.sent_at)
    return _ed25519_ok(announce.signature, message, announce.signing_key)


# --- Messages -----------------------------------------------------------------


@dataclass(frozen=True)
class ChatMessage:
    """One chat message. `recipient_key` is empty for Nearby, else the recipient's
    signing key. It is signed, so a private message cannot be passed off as Nearby or
    re-sent to someone else as if written to them."""

    message_id: bytes
    sender_key: bytes
    sender_nickname: str
    recipient_key: bytes
    text: str
    sent_at: int
    signature: bytes

    @property
    def is_private(self) -> bool:
        return bool(self.recipient_key)


def message_signing_bytes(message_id: bytes, sender_key: bytes, sender_nickname: str,
                          recipient_key: bytes, text: str, sent_at: int) -> bytes:
    out = _context(CHAT_CONTEXT) + message_id + sender_key + _len16(sender_nickname.encode())
    return out + _len16(recipient_key) + _len16(text.encode()) + _u64(sent_at)


def _signing_bytes_of(message: ChatMessage) -> bytes:
    return message_signing_bytes(message.message_id, message.sender_key, message.sender_nickname,
                                 message.recipient_key, message.text, message.sent_at)


def encode_message(message: ChatMessage) -> bytes:
    out = put_tlv(ChatTLVType.MESSAGE_ID, message.message_id)
    out += put_tlv(ChatTLVType.SENDER_KEY, message.sender_key)
    out += put_tlv(ChatTLVType.SENDER_NICKNAME, message.sender_nickname.encode())
    if message.recipient_key:
        out += put_tlv(ChatTLVType.RECIPIENT_KEY, message.recipient_key)
    out += put_tlv(ChatTLVType.TEXT, message.text.encode())
    out += put_tlv(ChatTLVType.SENT_AT, _u64(message.sent_at))
    out += put_tlv(ChatTLVType.SIGNATURE, message.signature)
    return out


def decode_message(data: bytes) -> ChatMessage | None:
    """Read a message, or None if malformed. Structure only: call `verify_message()`."""
    fields = read_tlvs(data, {t.value for t in ChatTLVType})
    if fields is None:
        return None
    values = {ChatTLVType.RECIPIENT_KEY: b""}
    for t, v in fields:
        if t == ChatTLVType.MESSAGE_ID and len(v) != MESSAGE_ID_LENGTH:
            return None
        if t in (ChatTLVType.SENDER_KEY, ChatTLVType.RECIPIENT_KEY) and len(v) != KEY_LENGTH:
            return None
        if t == ChatTLVType.SENDER_NICKNAME and (len(v) > NICKNAME_MAX_BYTES or _utf8(v) is None):
            return None
        if t == ChatTLVType.TEXT and (len(v) > TEXT_MAX_BYTES or not v or _utf8(v) is None):
            return None
        if t == ChatTLVType.SIGNATURE and len(v) != SIGNATURE_LENGTH:
            return None
        values[t] = v
    if len(values) != len(ChatTLVType):
        return None
    sent_at = _u64_from(values[ChatTLVType.SENT_AT])
    if sent_at is None:
        return None
    return ChatMessage(values[ChatTLVType.MESSAGE_ID], values[ChatTLVType.SENDER_KEY],
                       _utf8(values[ChatTLVType.SENDER_NICKNAME]), values[ChatTLVType.RECIPIENT_KEY],
                       _utf8(values[ChatTLVType.TEXT]), sent_at, values[ChatTLVType.SIGNATURE])


def verify_message(message: ChatMessage) -> bool:
    """Signed by the sender key it names: proves who wrote it and that nobody changed it."""
    return _ed25519_ok(message.signature, _signing_bytes_of(message), message.sender_key)


# --- Sealing private messages -------------------------------------------------


def _box_key(shared: bytes, one_off_key: bytes, recipient_chat_key: bytes) -> bytes:
    return HKDF(hashes.SHA256(), 32, salt=one_off_key + recipient_chat_key, info=PRIVATE_INFO).derive(shared)


def seal(plain: bytes, recipient_chat_key: bytes) -> bytes:
    """Encrypt so only the holder of `recipient_chat_key`'s private half can read it."""
    one_off = X25519PrivateKey.generate()
    one_off_key = one_off.public_key().public_bytes_raw()
    key = _box_key(one_off.exchange(X25519PublicKey.from_public_bytes(recipient_chat_key)),
                   one_off_key, recipient_chat_key)
    nonce = os.urandom(NONCE_LENGTH)
    return one_off_key + nonce + ChaCha20Poly1305(key).encrypt(nonce, plain, recipient_chat_key)


def open_sealed(sealed: bytes, chat_private_key: X25519PrivateKey) -> bytes | None:
    """The plain bytes, or None if this is not for us or was changed on the way."""
    if len(sealed) < SEALED_OVERHEAD:
        return None
    one_off_key, nonce, box = sealed[:KEY_LENGTH], sealed[KEY_LENGTH:KEY_LENGTH + NONCE_LENGTH], sealed[KEY_LENGTH + NONCE_LENGTH:]
    own_key = chat_private_key.public_key().public_bytes_raw()
    try:
        shared = chat_private_key.exchange(X25519PublicKey.from_public_bytes(one_off_key))
        return ChaCha20Poly1305(_box_key(shared, one_off_key, own_key)).decrypt(nonce, box, own_key)
    except (InvalidTag, ValueError):
        return None


# --- Identity: one person's keys ----------------------------------------------


class Identity:
    """One person's keys and nickname; signs their announces and messages.

    `seed` (64 bytes: signing key, then chat key) is what gets saved between runs.
    The signing half also signs the person's reports (`reports.ReportAuthor`), so the
    same person has the same key in chat and in calls for help.
    """

    SEED_LENGTH = 64

    def __init__(self, nickname: str = "", seed: bytes | None = None):
        seed = seed or os.urandom(self.SEED_LENGTH)
        if len(seed) != self.SEED_LENGTH:
            raise ValueError(f"an identity seed is {self.SEED_LENGTH} bytes")
        self.seed = seed
        self._signing = Ed25519PrivateKey.from_private_bytes(seed[:32])
        self._chat = X25519PrivateKey.from_private_bytes(seed[32:])
        self.nickname = nickname

    @property
    def signing_seed(self) -> bytes:
        return self.seed[:32]

    @property
    def signing_key(self) -> bytes:
        return self._signing.public_key().public_bytes_raw()

    @property
    def chat_key(self) -> bytes:
        return self._chat.public_key().public_bytes_raw()

    @property
    def peer_id(self) -> bytes:
        """The 8-byte ID iPhones know this device by: from the chat key, which the
        iPhone's announce calls the Noise key (bitchat.peer_id)."""
        return bitchat.peer_id(self.chat_key)

    def sign_packet(self, packet: "bitchat.Packet") -> "bitchat.Packet":
        return bitchat.sign(packet, self._signing)

    def _short_nickname(self) -> str:
        nickname = self.nickname.strip()
        while len(nickname.encode()) > NICKNAME_MAX_BYTES:
            nickname = nickname[:-1]
        return nickname

    def announce(self, now_ms: int) -> Announce:
        nickname = self._short_nickname()
        signature = self._signing.sign(announce_signing_bytes(self.signing_key, self.chat_key, nickname, now_ms))
        return Announce(self.signing_key, self.chat_key, nickname, now_ms, signature)

    def message(self, text: str, now_ms: int, to: Announce | None = None) -> ChatMessage | None:
        """A signed message, to everyone nearby, or to one person (`to`, their announce).
        None when the text is empty or too long."""
        text = text.strip()
        if not text or len(text.encode()) > TEXT_MAX_BYTES:
            return None
        message_id = os.urandom(MESSAGE_ID_LENGTH)
        nickname = self._short_nickname()
        recipient = to.signing_key if to else b""
        signature = self._signing.sign(message_signing_bytes(
            message_id, self.signing_key, nickname, recipient, text, now_ms))
        return ChatMessage(message_id, self.signing_key, nickname, recipient, text, now_ms, signature)

    def open(self, sealed: bytes) -> ChatMessage | None:
        """A private message sealed to us: opened, signature checked, and really
        addressed to us. None otherwise (most sealed messages are for someone else)."""
        plain = open_sealed(sealed, self._chat)
        message = decode_message(plain) if plain is not None else None
        if message is None or message.recipient_key != self.signing_key or not verify_message(message):
            return None
        return message
