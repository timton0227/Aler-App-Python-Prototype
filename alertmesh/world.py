"""One simulated town for the Streamlit page: the phones, the evacuation centre, and
the warning console wired to them.

New code, with no Swift equivalent. In the app, the warning console and the hub board
run on the same Mac, which is also a node in the Bluetooth mesh. Here that Mac is the
phone called "hub", placed at the town centre:
- the console's Bluetooth send goes into the mesh from the hub, like
  `sendOfficialAlertPayload` (the hub's own store takes it first);
- the console's internet send goes to the mesh's internet feed, which phones with
  internet read at once (`OfficialAlertBridge.publish`).

The phones are the same layout `metrics.build` makes for a scenario, so the page and
the notebook can show the same town.

This is free and unencumbered software released into the public domain.
"""
from dataclasses import dataclass, field

import pandas as pd

from alertmesh import geohash, metrics, notifications, places, proximity, viz, wire
from alertmesh.console import Console
from alertmesh.mesh_sim import OFFICIAL_ALERT_TYPE, Mesh, Notification, Phone

HUB_ID = "hub"
HUB_NICKNAME = "Evacuation centre"
# A watched place is a suburb-sized cell (~1 km), like a bookmarked location channel.
WATCHED_PRECISION = 6

# The town the page starts with: the notebook's section 3 town.
DEFAULT_SCENARIO = metrics.Scenario(n_phones=300, area_m=1_200, share_online=0.10,
                                    share_moving=0.25, speed_mps=1.4, seed=4)


@dataclass
class World:
    scenario: metrics.Scenario
    mesh: Mesh
    hub: Phone
    console: Console = None
    # Whether the centre (the Mac running the console and the board) has internet.
    online: bool = True
    # The latest version the console sent of each warning event, cancelled ones too.
    sent: dict[bytes, wire.OfficialAlert] = field(default_factory=dict)

    @property
    def centre(self) -> tuple[float, float]:
        return self.hub.lat, self.hub.lon

    @property
    def minutes(self) -> float:
        """Simulated minutes since the town was built."""
        return (self.mesh.now_ms - metrics.START_MS) / 60_000

    def town_cells(self) -> list[str]:
        """Warning cells that cover the whole simulated town."""
        return metrics.area_cells(*self.centre, self.scenario.area_m)

    def live_warnings(self) -> list[wire.OfficialAlert]:
        """What the console lists as live: the centre's own store, as on the Mac."""
        return self.hub.alert_store.live_alerts()

    def set_online(self, online: bool) -> None:
        """The centre loses or gets back its internet: the console cannot post, and
        the hub stops or starts reading the internet feed."""
        self.online = online
        self.hub.has_internet = online

    def advance(self, minutes: float) -> None:
        self.mesh.run(minutes * 60)

    # --- How far a warning has got (the map tab) ---

    def phones_now(self, alert_id: bytes) -> pd.DataFrame:
        """Every phone (not the centre) and whether it has the warning, at this minute."""
        rows = [r for r in viz.phone_status(self.mesh, alert_id) if r["phone"] != HUB_ID]
        return pd.DataFrame(rows).assign(minute=round(self.minutes))

    def play(self, alert_id: bytes, minutes: int) -> pd.DataFrame:
        """Let `minutes` pass, recording every phone each minute, labelled with the
        town's own minutes. Time really moves on, as with the + buttons."""
        start = round(self.minutes)
        frames = viz.spread_frames(self.mesh, alert_id, minutes)
        return frames[frames["phone"] != HUB_ID].assign(minute=frames["minute"] + start)

    def spread(self, alert_id: bytes) -> dict[str, int]:
        """Counts for one warning: phones by status, phones inside its area and how
        many of those have it, and how many were told loudly."""
        alert = self.sent[alert_id]
        phones = [p for p in self.mesh.phones.values() if p.id != HUB_ID]
        counts = {status: 0 for status in viz.STATUS_COLOURS}
        for row in viz.phone_status(self.mesh, alert_id):
            if row["phone"] != HUB_ID:
                counts[row["status"]] += 1
        # Where the phone really is, whatever its location setting.
        inside = [p for p in phones
                  if proximity.match(geohash.encode(p.lat, p.lon, 8), alert.area_cells)[0] == proximity.Match.INSIDE]
        return {
            **counts,
            "phones": len(phones),
            "in area": len(inside),
            "in area warned": sum(alert_id in p.first_heard_ms for p in inside),
            "told loudly": sum(p.loudest(alert_id) >= proximity.Urgency.LOUD for p in phones),
        }

    # --- One phone (the phone view tab) ---

    def phones(self) -> list[Phone]:
        """Every phone except the evacuation centre, in the order they were made."""
        return [p for p in self.mesh.phones.values() if p.id != HUB_ID]

    def set_phone(self, phone: Phone, *, bluetooth: bool | None = None, location: bool | None = None,
                  internet: bool | None = None, watched: places.Place | None | bool = False) -> None:
        """Change one phone's settings. `watched`: a place to watch, None for none,
        False to leave it as it is. The phone re-checks its warnings at once, as the
        app does when location changes (a warning can get louder, never quieter)."""
        if bluetooth is not None:
            phone.bluetooth_on = bluetooth
            self.mesh._grid = None  # who is in range has changed
        if location is not None:
            phone.location_on = location
            phone._remember()
        if internet is not None:
            phone.has_internet = internet
        if watched is not False:
            phone.bookmarks = () if watched is None else (places.geohash_of(watched, WATCHED_PRECISION),)
        phone.reevaluate()

    def warnings_on(self, phone: Phone) -> list["PhoneWarning"]:
        """The phone's warning list: each live warning, how the phone would decide
        now, and the loudest notification it showed for this version."""
        out = []
        for alert in phone.alert_store.live_alerts():
            shown = [n for n in phone.notifications if (n.alert_id, n.issued_at) == (alert.alert_id, alert.issued_at)]
            loudest = max(shown, key=lambda n: n.urgency, default=None)
            out.append(PhoneWarning(alert, phone.decide(alert), loudest))
        return out

    # --- Console wiring ---

    def _broadcast(self, payload: bytes) -> None:
        item = wire.decode(payload)
        if isinstance(item, wire.OfficialAlert):
            self.sent[item.alert_id] = item
        self.mesh.send(self.hub, OFFICIAL_ALERT_TYPE, payload)

    def _publish(self, payload: bytes, area, expires_at: int) -> bool:
        # In the app a relay is chosen by the area's cells; here any internet will do.
        if not self.online:
            return False
        self.mesh.publish(payload)
        return True


@dataclass(frozen=True)
class PhoneWarning:
    alert: wire.OfficialAlert
    now: proximity.Decision              # how the phone would decide at this moment
    notified: Notification | None        # the loudest notification shown for this version

    def notification(self) -> notifications.Content | None:
        """The words of that notification, as the phone showed them."""
        if self.notified is None:
            return None
        where = notifications.whereabouts(self.notified.reason.kind)
        return notifications.alert_content(self.alert, self.notified.urgency, where)


def build(scenario: metrics.Scenario = DEFAULT_SCENARIO) -> World:
    """A fresh town: the scenario's phones, plus the evacuation centre at the middle."""
    mesh, _ = metrics.build(scenario)
    place = places.find(scenario.town)
    hub = mesh.add_phone(HUB_ID, place.latitude, place.longitude, has_internet=True, nickname=HUB_NICKNAME)
    world = World(scenario, mesh, hub)
    world.console = Console(
        broadcast=world._broadcast,
        publish=world._publish,
        connected_peer_count=lambda: len(mesh.neighbours(hub)),
        now_ms=mesh.clock,
    )
    return world
