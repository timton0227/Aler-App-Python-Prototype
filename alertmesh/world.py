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

from alertmesh import metrics, places, wire
from alertmesh.console import Console
from alertmesh.mesh_sim import OFFICIAL_ALERT_TYPE, Mesh, Phone

HUB_ID = "hub"
HUB_NICKNAME = "Evacuation centre"

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
