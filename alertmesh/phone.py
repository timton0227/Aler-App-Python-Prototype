"""The phone app's engine: one person's identity and settings, the mesh node, and the
links that feed it. The Streamlit page (phone_app.py) only draws what this holds.

Modelled on the iPhone app's AppChromeModel, CommunityReportManager and
AlertNotificationsModel: who you are, where you are, what to show and how loud.

Where you are: the iPhone app uses GPS and will not open without location. A laptop
may have no position of its own, so the phone app takes a pin the person dropped, else
this Mac's fix from Location Services (alertmesh/location.py), else the centre of the
town they picked (alertmesh/position.py). That position decides which warnings cover
them, is where a call for help or a report says they are, and picks the relays.

Saved between runs, in a folder of the person's own (`home_folder()`): the identity
seed (so the same person keeps the same keys and conversations are not orphaned),
nickname, town, whether to use the internet (off until the person turns it on: calls
for help then go to public relays), whether to use this Mac's location, the pin, and
the last fix (as a geohash only). Messages and warnings are not saved: they come back
from the mesh.

This is free and unencumbered software released into the public domain.
"""
import json
import os
import platform
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from alertmesh import geohash, location, places, position, proximity
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
    internet: bool = False  # use the internet link (alertmesh.internet)
    use_location: bool = True  # use this Mac's Location Services (alertmesh.location)
    pin: str | None = None  # a geohash the person dropped a pin on (alertmesh.position)
    last_fix: position.Fix | None = None  # this Mac's last fix, already a geohash

    @classmethod
    def load(cls, folder: Path) -> "Profile":
        """The saved profile, or a new one (made and saved) on first run."""
        try:
            data = json.loads((folder / PROFILE_FILE).read_text(encoding="utf-8"))
            seed = bytes.fromhex(data["seed"])
            if len(seed) != Identity.SEED_LENGTH:
                raise ValueError
            pin = data.get("pin")
            return cls(str(data.get("nickname") or default_nickname()), data.get("town"), seed,
                       data.get("internet") is True, data.get("use_location") is not False,
                       pin if isinstance(pin, str) and geohash.is_valid(pin) else None,
                       _fix_from(data.get("last_fix")))
        except (OSError, ValueError, KeyError, TypeError):
            profile = cls(default_nickname(), None, os.urandom(Identity.SEED_LENGTH))
            profile.save(folder)
            return profile

    def save(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / PROFILE_FILE
        fix = self.last_fix
        path.write_text(json.dumps({
            "nickname": self.nickname, "town": self.town, "seed": self.seed.hex(), "internet": self.internet,
            "use_location": self.use_location, "pin": self.pin,
            "last_fix": fix and {"cell": fix.cell, "accuracy": fix.accuracy_m, "at": fix.at_ms},
        }), encoding="utf-8")
        if sys.platform != "win32":
            path.chmod(0o600)  # it holds the private keys


def _fix_from(data) -> position.Fix | None:
    """A saved fix, or None when there is none or it is broken."""
    try:
        if geohash.is_valid(data["cell"]):
            return position.Fix(data["cell"], float(data["accuracy"]), int(data["at"]))
    except (KeyError, TypeError, ValueError):
        pass
    return None


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
        self.internet = None  # alertmesh.internet.PhoneLink, made by start_internet()
        self.location = None  # alertmesh.location.LocationProcess, made by start_location()
        self._listener = None
        self._stop = threading.Event()

    # --- Links ---

    def start_internet(self, pool=None, choice=None) -> None:
        """Make the internet link, switched on if the profile says so. The tests pass
        their own pool and relays."""
        from alertmesh import internet

        if pool is None:
            from alertmesh.relays import RelayPool

            pool = RelayPool()
        self.internet = internet.PhoneLink(pool, choice or internet.RelayChoice.from_environment(), self.node,
                                           lambda: [self.geohash], self.clock)
        self.node.on_report = self.internet.report_arrived
        if self.profile.internet and pool.available:
            self.internet.set_enabled(True)

    @property
    def internet_available(self) -> bool:
        return self.internet is not None and self.internet.pool.available

    def set_internet(self, on: bool) -> None:
        self.profile.internet = on
        self.profile.save(self.folder)
        if self.internet_available:
            self.internet.set_enabled(on)

    @property
    def internet_status(self) -> str:
        """ "on: 3 of 9 relays", "off", or "off: why"."""
        if self.internet is None:
            return "off"
        if not self.internet.pool.available:
            return "off: needs the websockets library"
        if not self.internet.enabled:
            return "off"
        connected, total = self.internet.pool.status()
        return f"on: {connected} of {total} relays"

    def start_location(self, process=None) -> None:
        """Start the location process if the person wants it and this is a Mac. The
        tests pass their own process."""
        if self.location is None and self.profile.use_location and (process or location.available()):
            self.location = process or location.LocationProcess()
            self.location.on_fix = self.fix_arrived

    def fix_arrived(self, fix: position.Fix) -> None:
        with self._where_changes():
            self.profile.last_fix = fix
            self.profile.save(self.folder)

    def refresh_location(self) -> None:
        """Ask for a fresh fix, without waiting for it (the call for help does, as it opens)."""
        if self.location is not None:
            self.location.refresh()

    def set_use_location(self, on: bool) -> None:
        with self._where_changes():
            self.profile.use_location = on
            if not on:
                self.profile.last_fix = None  # "off" means this Mac's position is not used at all
                if self.location is not None:
                    self.location.stop()
                    self.location = None
            self.profile.save(self.folder)
        if on:
            self.start_location()

    @property
    def location_status(self) -> str:
        if not self.profile.use_location:
            return "off"
        if self.location is None:
            return location.NOT_HERE if not location.available() else "off"
        return self.location.status

    def start(self, bluetooth: bool = True, wifi: bool = True, internet: bool = True,
              locate: bool = True) -> "Phone":
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
        if internet:
            self.start_internet()
        if locate:
            self.start_location()
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
        if self.internet is not None:
            self.internet.pool.close()
        if self.location is not None:
            self.location.stop()

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
        with self._where_changes():
            self.profile.town = name
            self.profile.save(self.folder)

    def set_pin(self, cell: str | None) -> bool:
        """Drop a pin on a geohash, or clear it with None. False for a broken geohash."""
        if cell is not None and not geohash.is_valid(cell):
            return False
        with self._where_changes():
            self.profile.pin = cell.lower()[:position.PIN_PRECISION] if cell else None
            self.profile.save(self.folder)
        return True

    @property
    def where(self) -> position.Where | None:
        """The position in use: the pin, else a fresh fix, else the town's centre."""
        return position.choose(self.profile.pin, self.profile.last_fix, self.town, self.clock())

    @property
    def geohash(self) -> str | None:
        """Where this person is, as exact as the position allows (reports cut it to about
        150 m for a call for help)."""
        where = self.where
        return where.geohash if where else None

    @contextmanager
    def _where_changes(self):
        """Around anything that may move the person: calls for help are asked for from
        the relays around them, so a new area means asking again."""
        before = self.geohash
        yield
        after = self.geohash
        if self.internet is not None and (before or "")[:4] != (after or "")[:4]:
            self.internet.refresh()

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
