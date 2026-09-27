"""Cross-check the Python port against Swift, both ways. Needs a Mac with Swift.

    python3 tools/cross_check_swift.py

1. Swift signs, Python checks. For each case, the app's own signing script
   (../alert-mesh/scripts/sign-test-alert.swift, an independent implementation of
   docs/ALERT-WIRE-FORMAT.md) signs a warning or cancellation with fresh inputs.
   Python must decode it, verify it with the pinned key, read back the same fields,
   and produce the very same bytes up to the signature (Ed25519 signatures from
   CryptoKit are randomised, so only the signature itself may differ). A phone's
   store must accept it.
2. Python signs, Swift checks. Signatures made by the Python signer are checked by
   Apple's CryptoKit (tools/verify_signature.swift), the library the app verifies
   with. A signature with one bit flipped must fail, so the check is not vacuous.

This is free and unencumbered software released into the public domain.
"""
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from alertmesh import wire  # noqa: E402
from alertmesh.alert_store import AlertStore, IngestResult  # noqa: E402
from alertmesh.signer import DEV_PRIVATE_KEY, OfficialAlertSigner, WarningDraft  # noqa: E402
from alertmesh.wire import HazardType, Severity  # noqa: E402

SIGN_SCRIPT = ROOT.parent / "alert-mesh" / "scripts" / "sign-test-alert.swift"
VERIFY_SCRIPT = HERE / "verify_signature.swift"

HAZARDS = {"flood": HazardType.FLOOD, "bushfire": HazardType.BUSHFIRE, "storm": HazardType.STORM,
           "fireweather": HazardType.FIRE_WEATHER, "cyclone": HazardType.CYCLONE, "heatwave": HazardType.HEATWAVE}
SEVERITIES = {"advice": Severity.ADVICE, "watch": Severity.WATCH_AND_ACT, "emergency": Severity.EMERGENCY_WARNING}
HOUR_MS = 3_600_000


@dataclass(frozen=True)
class Case:
    name: str
    hazard: str = "flood"
    severity: str = "watch"
    areas: tuple[str, ...] = ("r7hg",)
    headline: str = "Test alert - this is not a real warning"
    action: str = "No action required. Local test only."
    hours: int = 6
    alert_id: str = "000102030405060708090a0b0c0d0e0f"
    issued_at: int = 1_700_000_000_000

    def args(self) -> list[str]:
        out = ["--hazard", self.hazard, "--severity", self.severity, "--headline", self.headline,
               "--action", self.action, "--hours", str(self.hours), "--id", self.alert_id,
               "--issued", str(self.issued_at)]
        for cell in self.areas:
            out += ["--area", cell]
        return out


CASES = [
    Case("the frozen vector's inputs", "bushfire", "emergency", ("r7hg", "r7hu"),
         "Bushfire at Mount Barker - leave now", "Travel north on Highway 1. Do not wait."),
    Case("Katherine flood, one town cell", "flood", "watch", ("qvqj9",),
         "Katherine River rising - prepare to leave", "Move vehicles and animals to high ground.", 12,
         "a1b2c3d4e5f60718293a4b5c6d7e8f90", 1_758_000_000_000),
    Case("storm advice, no action text, 1 hour", "storm", "advice", ("r3",), "Severe storm tonight", "", 1,
         "ffffffffffffffffffffffffffffffff", 1_759_999_999_999),
    Case("fire weather, 4 cells, 7 days", "fireweather", "watch", ("qd", "qe", "qs", "qu"),
         "Extreme fire danger", "Do not light fires.", 168, "0f0e0d0c0b0a09080706050403020100"),
    Case("cyclone, non-English text", "cyclone", "emergency", ("rq4",),
         "Cyclone Alfred - évacuez maintenant", "Allez à l'école — 避難所へ", 24,
         "11112222333344445555666677778888"),
    Case("heatwave, the longest warning that fits", "heatwave", "emergency", ("r1r0fsnz", "r1r0fsnx", "r1r0fsnw", "r1r0fsny"),
         "H" * 100, "A" * 100, 48, "99999999999999999999999999999999"),
]


def swift_available() -> bool:
    return shutil.which("swift") is not None and SIGN_SCRIPT.exists()


def sign_with_swift(args: list[str]) -> bytes:
    out = subprocess.run(["swift", str(SIGN_SCRIPT), *args], capture_output=True, text=True, check=True)
    return bytes.fromhex(out.stdout.strip())


def verify_with_cryptokit(triples: list[tuple[bytes, bytes, bytes]]) -> list[bool]:
    args = [part.hex() for triple in triples for part in triple]
    out = subprocess.run(["swift", str(VERIFY_SCRIPT), *args], capture_output=True, text=True, check=True)
    return [line == "valid" for line in out.stdout.split()]


def python_alert(case: Case) -> wire.OfficialAlert:
    """The same warning signed in Python. Through the console's signer when its rules
    allow the draft; the console (Swift and Python alike) refuses a warning with no
    "what to do", which the wire format and the Swift script allow, so that one is
    built straight from the wire format."""
    draft = WarningDraft(HAZARDS[case.hazard], SEVERITIES[case.severity], case.headline, case.action,
                         case.hours, list(case.areas))
    if not draft.problems:
        return OfficialAlertSigner().sign(draft, bytes.fromhex(case.alert_id), case.issued_at)
    fields = (bytes.fromhex(case.alert_id), HAZARDS[case.hazard], SEVERITIES[case.severity], case.areas,
              case.headline, case.action, case.issued_at, case.issued_at + case.hours * HOUR_MS)
    signature = Ed25519PrivateKey.from_private_bytes(DEV_PRIVATE_KEY).sign(wire.alert_signing_bytes(*fields))
    return wire.OfficialAlert(fields[0], int(fields[1]), *fields[2:], signature)


def check_swift_signed(case: Case) -> list[str]:
    """Problems found with one Swift-signed warning; empty means it passed."""
    problems = []
    data = sign_with_swift(case.args())
    alert = wire.decode(data)
    if not isinstance(alert, wire.OfficialAlert):
        return ["Python could not decode it"]
    if not wire.verify_pinned(alert):
        problems.append("signature does not verify with the pinned key")
    expected = (bytes.fromhex(case.alert_id), HAZARDS[case.hazard], SEVERITIES[case.severity], case.areas,
                case.headline, case.action, case.issued_at, case.issued_at + case.hours * HOUR_MS)
    got = (alert.alert_id, alert.hazard, alert.severity, alert.area_cells, alert.headline, alert.action_text,
           alert.issued_at, alert.expires_at)
    if got != expected:
        problems.append(f"fields differ: {got} != {expected}")
    ours = wire.encode(python_alert(case))
    if len(ours) != len(data) or ours[:-64] != data[:-64]:
        problems.append("Python's bytes differ from Swift's before the signature")
    store = AlertStore(clock=lambda: case.issued_at)
    if store.ingest_payload(data) is not IngestResult.ACCEPTED:
        problems.append("a phone's store did not accept it")
    return problems


def check_swift_cancellation() -> list[str]:
    case = CASES[0]
    alert = sign_with_swift(case.args())
    cancel_at = case.issued_at + 60_000
    data = sign_with_swift(["--cancel", "--id", case.alert_id, "--issued", str(cancel_at)])
    item = wire.decode(data)
    if not isinstance(item, wire.AlertCancellation):
        return ["Python could not decode the cancellation"]
    problems = []
    if not wire.verify_pinned(item):
        problems.append("cancellation signature does not verify")
    if (item.alert_id.hex(), item.issued_at) != (case.alert_id, cancel_at):
        problems.append("cancellation fields differ")
    ours = wire.encode(OfficialAlertSigner().cancel(bytes.fromhex(case.alert_id), cancel_at))
    if ours[:-64] != data[:-64]:
        problems.append("Python's cancellation bytes differ from Swift's before the signature")
    store = AlertStore(clock=lambda: cancel_at)
    store.ingest_payload(alert)
    if store.ingest_payload(data) is not IngestResult.ACCEPTED or store.live_alerts():
        problems.append("the store did not withdraw the warning")
    return problems


def check_python_signed() -> list[str]:
    """Python signs every case and a cancellation; CryptoKit must accept each, and
    must reject a copy with one bit of the signature flipped."""
    signer = OfficialAlertSigner()
    items = [python_alert(c) for c in CASES] + [signer.cancel(bytes.fromhex(CASES[0].alert_id), 1_700_000_060_000)]
    triples = []
    for item in items:
        if isinstance(item, wire.AlertCancellation):
            message = wire.cancellation_signing_bytes(item.alert_id, item.issued_at)
        else:
            message = wire.signing_bytes_of(item)
        triples.append((signer.public_key, message, item.signature))
        flipped = bytes([item.signature[0] ^ 0x01]) + item.signature[1:]
        triples.append((signer.public_key, message, flipped))
    results = verify_with_cryptokit(triples)
    problems = []
    for i, item in enumerate(items):
        good, bad = results[2 * i], results[2 * i + 1]
        if not good:
            problems.append(f"CryptoKit rejected Python's signature on item {i}")
        if bad:
            problems.append(f"CryptoKit accepted a tampered signature on item {i}")
    if len(results) != len(triples):
        problems.append("CryptoKit gave the wrong number of answers")
    return problems


def run() -> list[tuple[str, list[str]]]:
    rows = [(f"Swift signs, Python checks: {c.name}", check_swift_signed(c)) for c in CASES]
    rows.append(("Swift signs a cancellation, Python checks it", check_swift_cancellation()))
    rows.append((f"Python signs {len(CASES)} warnings and a cancellation, CryptoKit checks", check_python_signed()))
    return rows


def main() -> int:
    if not swift_available():
        print("Swift is not available (or ../alert-mesh is missing): nothing to cross-check.")
        return 1
    failed = 0
    for name, problems in run():
        print(("PASS  " if not problems else "FAIL  ") + name)
        for problem in problems:
            print("      " + problem)
        failed += bool(problems)
    print(f"\n{'All passed' if not failed else f'{failed} failed'}.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
