"""Nostr events: what the internet link sends and receives.

Ported from: alert-mesh/AlertMesh/Nostr/NostrProtocol.swift (NostrEvent: sign,
             calculateEventId, isValidSignature, isWithinInboundTagLimits)
         and alert-mesh/AlertMesh/Nostr/NostrIdentity.swift (generate).

Nostr is a public network of relay servers. Anyone can send an event to a relay, and
anyone can ask a relay for the events it holds. An event is a small JSON object:

    {"id": ..., "pubkey": ..., "created_at": ..., "kind": ..., "tags": [...],
     "content": ..., "sig": ...}

`id` is the SHA-256 of the other fields written in a fixed way (NIP-01), and `sig` is
a BIP-340 Schnorr signature of the id on the secp256k1 curve, made with the key whose
public half is `pubkey`. Relays and apps drop events whose id or signature is wrong.

The app signs every event with a fresh, throwaway key, so events cannot be linked to
each other or to a person. Trust never comes from this envelope: a warning or report
inside it carries its own Ed25519 signature, which is what the stores check.

BIP-340 is written out here in plain Python (after the BIP's reference code), so the
link needs no extra library. Plain Python is not constant-time, so the time taken
could hint at the key. That does not matter here: each key signs one event and is
then thrown away.

This is free and unencumbered software released into the public domain.
"""
import base64
import binascii
import hashlib
import json
import os
import time
from dataclasses import dataclass

from alertmesh import geohash, reports, wire

# --- secp256k1 and BIP-340 ----------------------------------------------------

_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
      0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def _add(a, b):
    """Adds two points on the curve. None is the point at infinity."""
    if a is None:
        return b
    if b is None:
        return a
    if a[0] == b[0] and a[1] != b[1]:
        return None
    if a == b:
        slope = 3 * a[0] * a[0] * pow(2 * a[1], -1, _P) % _P
    else:
        slope = (b[1] - a[1]) * pow(b[0] - a[0], -1, _P) % _P
    x = (slope * slope - a[0] - b[0]) % _P
    return x, (slope * (a[0] - x) - a[1]) % _P


def _mul(point, n: int):
    result = None
    while n:
        if n & 1:
            result = _add(result, point)
        point = _add(point, point)
        n >>= 1
    return result


def _bytes32(n: int) -> bytes:
    return n.to_bytes(32, "big")


def _int(b: bytes) -> int:
    return int.from_bytes(b, "big")


def _tagged_hash(tag: str, message: bytes) -> bytes:
    tag_hash = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(tag_hash + tag_hash + message).digest()


def _lift_x(x: int):
    """The point with this x and an even y, or None if there is none."""
    if x >= _P:
        return None
    y_squared = (pow(x, 3, _P) + 7) % _P
    y = pow(y_squared, (_P + 1) // 4, _P)
    if pow(y, 2, _P) != y_squared:
        return None
    return x, y if y % 2 == 0 else _P - y


def public_key(secret_key: bytes) -> bytes:
    """The 32-byte "x-only" public key of a 32-byte secret key."""
    d = _int(secret_key)
    if not 1 <= d < _N:
        raise ValueError("secret key out of range")
    return _bytes32(_mul(_G, d)[0])


def schnorr_sign(message: bytes, secret_key: bytes, aux: bytes | None = None) -> bytes:
    """A 64-byte BIP-340 signature of a 32-byte message. `aux` is 32 random bytes
    (fresh ones when not given); the BIP's test vectors pass their own."""
    if len(message) != 32:
        raise ValueError("the message must be 32 bytes")
    aux = os.urandom(32) if aux is None else aux
    d0 = _int(secret_key)
    if not 1 <= d0 < _N:
        raise ValueError("secret key out of range")
    point = _mul(_G, d0)
    d = d0 if point[1] % 2 == 0 else _N - d0
    t = bytes(a ^ b for a, b in zip(_bytes32(d), _tagged_hash("BIP0340/aux", aux)))
    k0 = _int(_tagged_hash("BIP0340/nonce", t + _bytes32(point[0]) + message)) % _N
    if k0 == 0:
        raise ValueError("nonce is zero")  # happens with negligible probability
    r = _mul(_G, k0)
    k = k0 if r[1] % 2 == 0 else _N - k0
    e = _int(_tagged_hash("BIP0340/challenge", _bytes32(r[0]) + _bytes32(point[0]) + message)) % _N
    signature = _bytes32(r[0]) + _bytes32((k + e * d) % _N)
    if not schnorr_verify(message, _bytes32(point[0]), signature):
        raise ValueError("the signature did not verify")  # as the reference code does
    return signature


def schnorr_verify(message: bytes, public_key_x: bytes, signature: bytes) -> bool:
    if len(message) != 32 or len(public_key_x) != 32 or len(signature) != 64:
        return False
    point = _lift_x(_int(public_key_x))
    r, s = _int(signature[:32]), _int(signature[32:])
    if point is None or r >= _P or s >= _N:
        return False
    e = _int(_tagged_hash("BIP0340/challenge", signature[:32] + public_key_x + message)) % _N
    result = _add(_mul(_G, s), _mul(point, _N - e))
    return result is not None and result[1] % 2 == 0 and result[0] == r


def new_secret_key() -> bytes:
    """A fresh random secret key (NostrIdentity.generate)."""
    while True:
        key = os.urandom(32)
        if 1 <= _int(key) < _N:
            return key


# --- Events -------------------------------------------------------------------

# Limits on events from relays, so a hostile relay cannot make us do much work
# (TransportConfig.nostrMaxEventTags and friends).
MAX_TAGS = 64
MAX_TAG_VALUES = 16
MAX_TAG_VALUE_BYTES = 1024


@dataclass(frozen=True)
class Event:
    id: str  # hex
    pubkey: str  # hex, 32 bytes
    created_at: int  # seconds since 1970
    kind: int
    tags: tuple  # of tuples of strings
    content: str
    sig: str  # hex, 64 bytes

    def to_dict(self) -> dict:
        return {"id": self.id, "pubkey": self.pubkey, "created_at": self.created_at, "kind": self.kind,
                "tags": [list(tag) for tag in self.tags], "content": self.content, "sig": self.sig}

    def is_valid(self) -> bool:
        """The id matches the fields and the signature matches the id (isValidSignature)."""
        try:
            digest = event_hash(self.pubkey, self.created_at, self.kind, self.tags, self.content)
            return (digest.hex() == self.id
                    and schnorr_verify(digest, bytes.fromhex(self.pubkey), bytes.fromhex(self.sig)))
        except ValueError:
            return False

    @classmethod
    def from_dict(cls, data) -> "Event | None":
        """An event as a relay sent it, or None if it is not one or its tags are too
        many or too long. The id and signature are not checked here: see `is_valid`."""
        try:
            tags = data["tags"]
            if not isinstance(tags, list) or len(tags) > MAX_TAGS:
                return None
            for tag in tags:
                if not isinstance(tag, list) or len(tag) > MAX_TAG_VALUES:
                    return None
                if not all(isinstance(v, str) and len(v.encode()) <= MAX_TAG_VALUE_BYTES for v in tag):
                    return None
            fields = (data["id"], data["pubkey"], data["created_at"], data["kind"], data["content"], data["sig"])
            if not all(isinstance(v, str) for v in (data["id"], data["pubkey"], data["content"], data["sig"])):
                return None
            if not all(isinstance(v, int) and not isinstance(v, bool) for v in (data["created_at"], data["kind"])):
                return None
        except (KeyError, TypeError):
            return None
        event_id, pubkey, created_at, kind, content, sig = fields
        return cls(event_id, pubkey, created_at, kind, tuple(tuple(tag) for tag in tags), content, sig)


def event_hash(pubkey: str, created_at: int, kind: int, tags, content: str) -> bytes:
    """SHA-256 of the event written the NIP-01 way: a JSON array with no spaces, and
    no characters escaped that need not be (Swift: .withoutEscapingSlashes)."""
    serialized = json.dumps([0, pubkey, created_at, kind, [list(tag) for tag in tags], content],
                            separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode()).digest()


def sign_event(kind: int, tags, content: str, created_at: int | None = None,
               secret_key: bytes | None = None) -> Event:
    """A signed event. By default signed with a fresh key and stamped with the time now."""
    secret_key = secret_key or new_secret_key()
    pubkey = public_key(secret_key).hex()
    created_at = int(time.time()) if created_at is None else created_at
    tags = tuple(tuple(tag) for tag in tags)
    digest = event_hash(pubkey, created_at, kind, tags, content)
    return Event(digest.hex(), pubkey, created_at, kind, tags, content, schnorr_sign(digest, secret_key).hex())


# --- Warnings and reports as events ---------------------------------------------
#
# Ported from: alert-mesh/AlertMesh/AlertMesh/Services/OfficialAlertBridge.swift and
#              CommunityReportBridge.swift (tagCells, makeEvent, payload, versionKey),
#              alert-mesh/AlertMesh/Nostr/NostrProtocol.swift (EventKind) and
#              NostrRelayManager.swift (builtInRelays, NostrFilter.officialAlerts,
#              NostrFilter.communityReports).
#
# The content of each event is the warning or report exactly as it is sent over
# Bluetooth, in base64, so every app reads it with the same code and checks the same
# signature.

KIND_COMMUNITY_REPORT = 1402
KIND_OFFICIAL_ALERT = 1403

# The relays the iPhone app always uses. Every phone listens for warnings on all of
# them, so a warning published to them reaches every phone with internet.
BUILT_IN_RELAYS = ("wss://relay.damus.io", "wss://nos.lol", "wss://relay.primal.net", "wss://offchain.pub")
RELAYS_VARIABLE = "ALERTMESH_NOSTR_RELAYS"  # comma-separated; the tests set their own

# A warning's area cells are tagged with every prefix of 2 to 4 characters (about
# 40 × 20 km at 4), so a client can ask for its own area without learning more.
MIN_TAG_PRECISION = wire.AREA_GEOHASH_MIN_LENGTH
MAX_TAG_PRECISION = 4
# Calls for help are tagged with, and asked for by, their 4-character cell.
REPORT_CELL_PRECISION = 4
# A maximal warning is 370 bytes, about 500 in base64. Anything much longer is not ours.
MAX_CONTENT_BYTES = 1024
FILTER_LIMIT = 200


def relay_urls() -> list[str]:
    """The relays to use: the built-in ones, or those named in ALERTMESH_NOSTR_RELAYS."""
    named = os.environ.get(RELAYS_VARIABLE)
    if named is not None:
        return [url.strip() for url in named.split(",") if url.strip()]
    return list(BUILT_IN_RELAYS)


def tag_cells(area) -> list[str]:
    """Every 2- to 4-character prefix of each area cell, sorted and unique."""
    cells = set()
    for cell in area:
        cell = cell.lower()
        if len(cell) < MIN_TAG_PRECISION:
            continue
        for length in range(MIN_TAG_PRECISION, min(MAX_TAG_PRECISION, len(cell)) + 1):
            cells.add(cell[:length])
    return sorted(cells)


def alert_event(payload: bytes, area, expires_at_ms: int, **signing) -> Event:
    """A warning or cancellation (its signed bytes) as a kind 1403 event. A
    cancellation has no area of its own: pass the cancelled warning's area and expiry.
    `signing` goes to `sign_event` (the tests fix the time and key)."""
    tags = [["g", cell] for cell in tag_cells(area)] + [["expiration", str(expires_at_ms // 1000)]]
    return sign_event(KIND_OFFICIAL_ALERT, tags, base64.b64encode(payload).decode(), **signing)


def is_bridged(kind: reports.ReportKind) -> bool:
    """Calls for help and "I'm safe" go online. Hazard reports do not: they are many
    and less urgent, and each would cost every bridging phone a publish."""
    return kind in (reports.ReportKind.SOS, reports.ReportKind.SAFE)


def report_cell(geohash: str) -> str:
    return geohash.lower()[:REPORT_CELL_PRECISION]


def report_event(report: reports.CommunityReport, **signing) -> Event:
    """A call for help or "I'm safe" as a kind 1402 event, tagged with its 4-character cell."""
    tags = [["g", report_cell(report.geohash)], ["expiration", str(report.expires_at // 1000)]]
    return sign_event(KIND_COMMUNITY_REPORT, tags, base64.b64encode(reports.encode(report)).decode(), **signing)


def payload_of(event: Event, kind: int) -> bytes | None:
    """The signed bytes inside an event of this kind, or None. Not checked here: the
    stores check the signature inside."""
    if event.kind != kind or len(event.content.encode()) > MAX_CONTENT_BYTES:
        return None
    try:
        return base64.b64decode(event.content, validate=True)
    except (binascii.Error, ValueError):
        return None


def alert_version_key(item) -> str:
    """One per version of a warning or cancellation, to hand each on once."""
    prefix = "c" if isinstance(item, wire.AlertCancellation) else "a"
    return f"{prefix}-{item.alert_id.hex()}-{item.issued_at}"


def report_version_key(report: reports.CommunityReport) -> str:
    return f"{report.author_signing_key.hex()}-{report.report_id.hex()}-{report.created_at}"


def official_alerts_filter(since_s: int | None = None, limit: int = FILTER_LIMIT) -> dict:
    """Every warning, wherever it is: the proximity rule decides how loudly to tell."""
    subscription = {"kinds": [KIND_OFFICIAL_ALERT], "limit": limit}
    if since_s is not None:
        subscription["since"] = since_s
    return subscription


def community_reports_filter(cells, since_s: int | None = None, limit: int = FILTER_LIMIT) -> dict:
    subscription = {"kinds": [KIND_COMMUNITY_REPORT], "#g": list(cells), "limit": limit}
    if since_s is not None:
        subscription["since"] = since_s
    return subscription


def report_cells(places) -> list[str]:
    """The 4-character cells to ask for calls for help: around each place (this
    phone's and its watched places), with their neighbours."""
    cells = set()
    for place in places:
        if place and len(place) >= REPORT_CELL_PRECISION:
            cell = report_cell(place)
            cells.add(cell)
            cells.update(geohash.neighbors(cell))
    return sorted(cells)
