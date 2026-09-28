"""Cross-check the Bluetooth packet codec (alertmesh/bitchat.py) against the iPhone
app's own code. Needs a Mac with Swift.

    python3 tools/cross_check_bitchat.py

Builds tools/bitchat_check, a small Swift program on the app's BitFoundation package
(the iPhone's packet code) and Apple's CryptoKit, then:

1. Python makes and signs packets; Swift decodes them, reads back the same fields, and
   checks the signature the way the iPhone does (rebuilding the signed bytes with its
   own compressor).
2. Swift makes and signs the same packets; Python must produce the very same bytes on
   the air and the very same signed bytes, and must verify Swift's signatures.
3. Compression: Apple's bytes for a few hundred chat-like texts, compared with
   Python's. They must be equal, or iPhones would reject long messages from laptops.

Writes tests/data/bitchat_vectors.json, which tests/test_bitchat.py checks on every run
(also where Swift is missing).

This is free and unencumbered software released into the public domain.
"""
import json
import random
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from alertmesh import bitchat, places, reports, wire  # noqa: E402
from alertmesh.bitchat import MessageType, Packet  # noqa: E402
from alertmesh.chat import Identity  # noqa: E402
from alertmesh.signer import OfficialAlertSigner, WarningDraft  # noqa: E402

PACKAGE = HERE / "bitchat_check"
BINARY = PACKAGE / ".build" / "release" / "bitchat_check"
VECTORS = ROOT / "tests" / "data" / "bitchat_vectors.json"
NOW = 1_790_000_000_000
SEED = bytes(range(1, 65))  # a fixed identity, so the vectors are the same every run

WORDS = ("flood water road bridge closed fire smoke evacuate centre school oval river causeway "
         "help please we are safe need boat rope kids dog car stuck roof power out phone storm "
         "wind north south east west katherine darwin highway now soon wait stay go leave the a "
         "to at on in is are near far over under 3 mile 12 km 5pm tonight morning !! ? , .").split()


def swift(request: dict) -> dict:
    out = subprocess.run([str(BINARY)], input=json.dumps(request).encode(), capture_output=True, check=True)
    return json.loads(out.stdout)


def spec(p: Packet, key: bytes | None) -> dict:
    s = {"type": p.type, "sender": p.sender_id.hex(), "timestamp": p.timestamp, "payload": p.payload.hex(),
         "ttl": p.ttl, "version": p.version, "is_rsr": p.is_rsr}
    if p.recipient_id is not None:
        s["recipient"] = p.recipient_id.hex()
    if p.route:
        s["route"] = [hop.hex() for hop in p.route]
    if key is not None:
        s["key"] = key.hex()
    return s


def cases(me: Identity) -> list[tuple[str, Packet]]:
    alert = OfficialAlertSigner().sign(
        WarningDraft(headline="Bushfire near Katherine - leave now",
                     action_text="Go to the evacuation centre on Giles Street.", area_cells=["qvqj"]),
        bytes(range(16)), NOW)
    sos = reports.ReportAuthor("Sam", bytes(range(1, 33))).sos(places.geohash_of(places.find("Katherine")),
                                                                "Trapped on the roof with two kids", NOW)
    announce = b"\x01\x06Laptop\x02\x20" + me.chat_key + b"\x03\x20" + me.signing_key
    base = dict(sender_id=me.peer_id, timestamp=NOW, ttl=7)
    long_text = ("Flood water over the causeway at Katherine, take the high road north to the school "
                 "instead of the river road. The bridge is closed until morning.").encode()
    return [
        ("announce", Packet(MessageType.ANNOUNCE, payload=announce, **base)),
        ("short message", Packet(MessageType.MESSAGE, payload=b"hello", **base)),
        ("long message, compressed", Packet(MessageType.MESSAGE, payload=long_text, **base)),
        ("280-byte message", Packet(MessageType.MESSAGE, payload=(long_text * 2)[:280], **base)),
        ("emoji message", Packet(MessageType.MESSAGE, payload="Safe at the oval 🙏🏽 see you soon".encode(), **base)),
        ("to one peer", Packet(MessageType.MESSAGE, payload=b"direct", recipient_id=bytes(range(8)), **base)),
        ("warning", Packet(MessageType.OFFICIAL_ALERT, payload=wire.encode(alert), **base)),
        ("call for help", Packet(MessageType.COMMUNITY_REPORT, payload=reports.encode(sos), **base)),
        ("leave", Packet(MessageType.LEAVE, payload=b"", **base)),
        ("catch-up reply (RSR)", Packet(MessageType.OFFICIAL_ALERT, payload=wire.encode(alert), is_rsr=True,
                                         **dict(base, ttl=0))),
        ("v2 with a route", Packet(MessageType.MESSAGE, payload=b"routed", version=2,
                                    route=(bytes(range(8)), bytes(range(8, 16))), **base)),
        ("laptop private", Packet(MessageType.LAPTOP_PRIVATE, payload=bytes(range(200)) * 2, **base)),
    ]


def corpus(n: int = 300) -> list[bytes]:
    rng = random.Random(16)
    texts = []
    for _ in range(n):
        length = rng.randint(100, 600)
        words = []
        while len(" ".join(words)) < length:
            words.append(rng.choice(WORDS))
        texts.append(" ".join(words)[:length].encode())
    return texts


def main() -> int:
    if shutil.which("swift") is None:
        print("Needs Swift (a Mac with Xcode or the command line tools).")
        return 1
    print("Building tools/bitchat_check (the app's BitFoundation package) ...")
    subprocess.run(["swift", "build", "-c", "release", "--package-path", str(PACKAGE)], check=True,
                   capture_output=True)

    me = Identity("Laptop", SEED)
    all_cases = cases(me)
    failures = 0
    vectors = {"public_key": me.signing_key.hex(), "packets": [], "compression": []}

    # 1. Python signs, Swift reads and checks.
    frames = [bitchat.encode(me.sign_packet(p)) for _, p in all_cases]
    answers = swift({"decode": [{"frame": f.hex(), "key": me.signing_key.hex()} for f in frames]})["decode"]
    print("\n1. Python makes, the iPhone's code reads and checks:")
    for (name, p), got in zip(all_cases, answers):
        ok = (got["ok"] and got["verified"] and bytes.fromhex(got["payload"]) == p.payload
              and got["type"] == p.type and got["ttl"] == p.ttl and got["is_rsr"] == p.is_rsr)
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")

    # 2. Swift signs, Python reads, checks and must make the same bytes.
    made = swift({"encode": [spec(p, SEED[:32]) for _, p in all_cases]})["encode"]
    print("\n2. The iPhone's code makes, Python reads and checks:")
    for (name, p), got in zip(all_cases, made):
        frame = bytes.fromhex(got["frame"])
        decoded = bitchat.decode(frame)
        same_wire = bitchat.encode(p) == bytes.fromhex(got["wire"])
        same_view = bitchat.signing_bytes(p) == bytes.fromhex(got["signed_view"])
        ok = (decoded is not None and bitchat.verify(decoded, me.signing_key) and same_wire and same_view
              and decoded.payload == p.payload and decoded.type == p.type)
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if same_wire else " (other bytes on the air)")
              + ("" if same_view else " (other signed bytes)"))
        vectors["packets"].append({"name": name, "packet": spec(p, None), "wire": got["wire"],
                                   "signed_view": got["signed_view"], "frame": got["frame"]})

    # 3. Compression, on texts like chat messages.
    texts = corpus()
    made = swift({"encode": [spec(Packet(MessageType.MESSAGE, me.peer_id, NOW, t, 7), SEED[:32])
                             for t in texts]})["encode"]
    same = compressed = 0
    for text, got in zip(texts, made):
        apple = bitchat.decode(bytes.fromhex(got["wire"])).compressed
        ours = bitchat.compress(text) if bitchat.should_compress(text) else None
        compressed += apple is not None
        same += apple == ours
        if len(vectors["compression"]) < 40 and apple is not None:
            vectors["compression"].append({"text": text.hex(), "apple": apple.hex()})
    print(f"\n3. Compression: {same} of {len(texts)} texts give the same bytes as Apple's "
          f"({compressed} of them compressed).")
    failures += same != len(texts)

    VECTORS.parent.mkdir(exist_ok=True)
    VECTORS.write_text(json.dumps(vectors, indent=1) + "\n")
    print(f"\nWrote {VECTORS.relative_to(ROOT)}.")
    print("All good." if not failures else f"{failures} failed: see above.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
