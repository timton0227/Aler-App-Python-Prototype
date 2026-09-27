"""The phone app's engine: one person's identity and settings, the mesh node, and the
links that feed it. The Streamlit page (phone_app.py) only draws what this holds.

Modelled on the iPhone app's AppChromeModel, CommunityReportManager and
AlertNotificationsModel: who you are, where you are, what to show and how loud.

Where you are: the iPhone app uses GPS and will not open without location. A laptop
has no GPS, so the person picks their town; the town's centre stands in for their
position when deciding whether a warning covers them, and is where a call for help
says they are.

Saved between runs, in a folder of the person's own (`home_folder()`): the identity
seed (so the same person keeps the same keys and conversations are not orphaned),
nickname and town. Messages and warnings are not saved: they come back from the mesh.

This is free and unencumbered software released into the public domain.
"""
import json
import os
import platform
import sys
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from alertmesh import places, proximity
from alertmesh.alert_store import _system_clock_ms
from alertmesh.chat import Identity
from alertmesh.node import Node
from alertmesh.reports import CommunityReport, ReportKind
from alertmesh.wire import HazardType, OfficialAlert

APP_FOLDER = "Alert Mesh"
PROFILE_FILE = "phone.json"
TICK_S = 1.0


def home_folder() -> Path:
    """Where this person's phone app keeps its settings. ALERTMESH_HOME overrides it, so
    two people can run the phone app on one computer."""
    if os.environ.get("ALERTMESH_HOME"):
        return Path(os.environ["ALERTMESH_HOME"])
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_FOLDER
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / APP_FOLDER
    return Path.home() / ".alert-mesh"


def default_nickname() -> str:
    """The computer's name, which people nearby can then change the meaning of."""
    return platform.node().removesuffix(".local")[:20] or "Laptop"


@dataclass
class Profile:
    nickname: str
    town: str | None  # a town name from places.towns(), or None until picked
    seed: bytes

    @classmethod
    def load(cls, folder: Path) -> "Profile":
        """The saved profile, or a new one (made and saved) on first run."""
        try:
            data = json.loads((folder / PROFILE_FILE).read_text(encoding="utf-8"))
            seed = bytes.fromhex(data["seed"])
            if len(seed) != Identity.SEED_LENGTH:
                raise ValueError
            return cls(str(data.get("nickname") or default_nickname()), data.get("town"), seed)
        except (OSError, ValueError, KeyError, TypeError):
            profile = cls(default_nickname(), None, os.urandom(Identity.SEED_LENGTH))
            profile.save(folder)
            return profile

    def save(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / PROFILE_FILE
        path.write_text(json.dumps({"nickname": self.nickname, "town": self.town, "seed": self.seed.hex()}),
                        encoding="utf-8")
        if sys.platform != "win32":
            path.chmod(0o600)  # it holds the private keys


class NoLink:
    """Until Bluetooth starts, or when it is off: sends go nowhere."""

    status = "off"

    def send(self, frame: bytes) -> None:
        pass

    def neighbours(self) -> int:
        return 0


@dataclass(frozen=True)
class WarningView:
    alert: OfficialAlert
    decision: proximity.Decision


class NowKind(Enum):
    CLEAR = "clear"            # no live warnings at all: "No current warnings"
    ELSEWHERE = "elsewhere"    # warnings, none covering you: "No warnings where you are"
    AFFECTED = "affected"      # a warning covers you: the solid colour block


# "Covers you" is "You are in this area": the place is inside the warning's area. Next to
# it ("Near you") is listed with the other warnings, not shown as the block.
COVERS_YOU = {proximity.ReasonKind.INSIDE_AREA, proximity.ReasonKind.WATCHED_PLACE_INSIDE_AREA}


@dataclass(frozen=True)
class NowStatus:
    kind: NowKind
    affected: WarningView | None = None
    others: list[WarningView] = field(default_factory=list)


def now_status(warnings: list[WarningView]) -> NowStatus:
    """What the top of Now shows (NowView's status). `warnings` must be in the store's
    order, most severe first, so the block shows the worst warning that covers you;
    every other warning is listed under it."""
    if not warnings:
        return NowStatus(NowKind.CLEAR)
    affected = next((w for w in warnings if w.decision.reason.kind in COVERS_YOU), None)
    if affected is None:
        return NowStatus(NowKind.ELSEWHERE, None, list(warnings))
    return NowStatus(NowKind.AFFECTED, affected, [w for w in warnings if w is not affected])


class Phone:
    """One person's phone app. `start()` connects the real links; the tests pass
    their own `link` and leave Wi-Fi off."""

    def __init__(self, folder: Path | None = None, clock=_system_clock_ms):
        self.folder = folder or home_folder()
        self.profile = Profile.load(self.folder)
        self.clock = clock
        self.node = Node(Identity(self.profile.nickname, self.profile.seed), NoLink(), clock)
        self.wifi_status = "off"
        self._listener = None
        self._stop = threading.Event()

    # --- Links ---

    def start(self, bluetooth: bool = True, wifi: bool = True) -> "Phone":
        if bluetooth:
            from alertmesh.ble import BluetoothProcess

            self.node.link = BluetoothProcess(self.node.receive)
        if wifi:
            from alertmesh.lan import Listener

            try:
                self._listener = Listener(self.node.take_official)
                self.wifi_status = "on"
            except OSError as error:
                self.wifi_status = f"off: {error}"
        threading.Thread(target=self._tick, name="phone-tick", daemon=True).start()
        return self

    def _tick(self) -> None:
        while not self._stop.wait(TICK_S):
            self.node.tick()

    def stop(self) -> None:
        self._stop.set()
        if self._listener:
            self._listener.close()
        if hasattr(self.node.link, "stop"):
            self.node.link.stop()

    @property
    def bluetooth_status(self) -> str:
        return getattr(self.node.link, "status", "off")

    # --- Who and where ---

    @property
    def nickname(self) -> str:
        return self.profile.nickname

    def set_nickname(self, nickname: str) -> None:
        nickname = nickname.strip() or default_nickname()
        if nickname != self.profile.nickname:
            self.profile.nickname = nickname
            self.profile.save(self.folder)
            self.node.set_nickname(nickname)

    @property
    def town(self) -> places.Place | None:
        return places.find(self.profile.town) if self.profile.town else None

    def set_town(self, name: str | None) -> None:
        self.profile.town = name
        self.profile.save(self.folder)

    @property
    def geohash(self) -> str | None:
        """Where this person is, at the call-for-help precision (about 150 m)."""
        town = self.town
        return places.geohash_of(town) if town else None

    # --- What to show ---

    def warnings(self) -> list[WarningView]:
        """Live warnings, each with how it concerns this person (loud or quiet, and why)."""
        here = self.geohash
        with self.node._lock:
            alerts = self.node.alerts.live_alerts()
        return [WarningView(a, proximity.decide(a.severity, a.area_cells, here)) for a in alerts]

    def reports(self) -> list[CommunityReport]:
        with self.node._lock:
            return self.node.reports.live_reports()

    def calls_for_help(self) -> list[CommunityReport]:
        """Other people's calls for help still out: shown first on Now."""
        own = self.node.identity.signing_key
        return [r for r in self.reports() if r.kind is ReportKind.SOS and r.author_signing_key != own]

    def is_own(self, report: CommunityReport) -> bool:
        return report.author_signing_key == self.node.identity.signing_key

    def my_call_for_help(self) -> CommunityReport | None:
        """Our own call for help, while it is out."""
        last = self.node.author.last_check_in
        if last and last.kind is ReportKind.SOS and last.expires_at > self.clock():
            return last
        return None

    # --- Sending ---

    def send_sos(self, note: str) -> bool:
        here = self.geohash
        return here is not None and self.node.send_report(self.node.author.sos(here, note, self.clock()))

    def send_safe(self) -> bool:
        return self.node.send_report(self.node.author.safe(self.geohash, "", self.clock()))

    def send_hazard(self, hazard: HazardType, severity, note: str) -> bool:
        here = self.geohash
        return here is not None and self.node.send_report(
            self.node.author.hazard(hazard, severity, here, note, self.clock()))


# The one phone this program runs, shared by every page load (tests set their own).
_shared: Phone | None = None
_shared_lock = threading.Lock()


def shared() -> Phone:
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = Phone().start()
        return _shared


def set_shared(phone: Phone | None) -> None:
    global _shared
    with _shared_lock:
        _shared = phone
