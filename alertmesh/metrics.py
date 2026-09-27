"""Numbers for judges: how many people a warning reaches, and how fast.

New code, with no Swift equivalent. It builds repeatable scenarios on top of
`mesh_sim` and measures them. Every run uses a fixed random seed, so the same
scenario always gives the same numbers.

The measure: of the phones inside the warning area, what share holds the warning
at each moment after it is published?

This is free and unencumbered software released into the public domain.
"""
import math
import random
from dataclasses import dataclass, field

from alertmesh import geohash, mesh_sim, places, proximity, wire
from alertmesh.mesh_sim import OFFICIAL_ALERT_TYPE, Mesh
from alertmesh.signer import OfficialAlertSigner, WarningDraft
from alertmesh.wire import HazardType, Severity

START_MS = 1_700_000_000_000


@dataclass(frozen=True)
class Scenario:
    """One simulated community. Distances in metres, times in seconds."""

    town: str = "Katherine"
    n_phones: int = 300
    area_m: float = 1_000.0          # phones are spread over a square this wide
    share_online: float = 0.10       # share of phones with internet
    bluetooth_range_m: float = mesh_sim.DEFAULT_BLUETOOTH_RANGE_M
    share_moving: float = 0.0        # share of phones that walk or drive about
    speed_mps: float = 1.4           # walking pace; a car is about 15
    mesh_on: bool = True             # False: Bluetooth off everywhere (internet only)
    severity: Severity = Severity.EMERGENCY_WARNING
    duration_s: float = 3_600.0
    sample_s: float = 60.0           # how often the curve is sampled
    seed: int = 1


@dataclass
class Result:
    scenario: Scenario
    times_s: list[float]
    warned_share: list[float]        # share of in-area phones holding the warning at each time
    loud_share: float                # share of in-area phones told loudly by the end
    in_area: int                     # how many phones were inside the warning area
    first_heard_s: dict[str, float] = field(default_factory=dict)  # phone id -> seconds after publishing

    @property
    def final_share(self) -> float:
        return self.warned_share[-1] if self.warned_share else 0.0

    def time_to_share(self, share: float) -> float | None:
        """Seconds until at least `share` of in-area phones held the warning, or None."""
        for t, s in zip(self.times_s, self.warned_share):
            if s >= share:
                return t
        return None


def _centre(town: str) -> tuple[float, float]:
    place = places.find(town)
    if place is None:
        raise ValueError(f"unknown town: {town}")
    return place.latitude, place.longitude


def area_cells(lat: float, lon: float, area_m: float) -> list[str]:
    """Warning cells that cover the whole square: the corners' cells at the finest
    precision where the square is no wider than one cell (so 4 corners cover it)."""
    for precision, cell_deg in ((5, 180 / 2**12), (4, 180 / 2**10), (3, 180 / 2**7)):
        # A cell is cell_deg tall and at least cell_deg * cos(lat) wide at these precisions.
        if area_m <= cell_deg * mesh_sim.EARTH_M_PER_DEGREE * abs(math.cos(math.radians(lat))):
            break
    half = area_m / 2
    corners = [mesh_sim.offset_m(lat, lon, n, e) for n in (-half, half) for e in (-half, half)]
    return sorted({geohash.encode(c_lat, c_lon, precision) for c_lat, c_lon in corners})


def build(scenario: Scenario) -> tuple[Mesh, wire.OfficialAlert]:
    """The phones and the signed warning for a scenario. Same seed, same layout."""
    rng = random.Random(scenario.seed)
    lat, lon = _centre(scenario.town)
    half = scenario.area_m / 2
    mesh = Mesh(start_ms=START_MS, bluetooth_range_m=scenario.bluetooth_range_m)

    def spot():
        return mesh_sim.offset_m(lat, lon, rng.uniform(-half, half), rng.uniform(-half, half))

    for i in range(scenario.n_phones):
        online = rng.random() < scenario.share_online
        moving = rng.random() < scenario.share_moving
        route = [spot() for _ in range(20)] if moving else []
        mesh.add_phone(f"p{i}", *spot(), has_internet=online, bluetooth_on=scenario.mesh_on,
                       route=route, speed_mps=scenario.speed_mps if moving else 0.0)

    draft = WarningDraft(HazardType.FLOOD, scenario.severity, f"Flooding at {scenario.town}",
                         "Move to higher ground now.", 12, area_cells(lat, lon, scenario.area_m))
    alert = OfficialAlertSigner().sign(draft, bytes(rng.randrange(256) for _ in range(16)), START_MS)
    return mesh, alert


def _inside(phone: mesh_sim.Phone, alert: wire.OfficialAlert) -> bool:
    """Where the phone really is, whatever its location setting."""
    here = geohash.encode(phone.lat, phone.lon, 8)
    return proximity.match(here, alert.area_cells)[0] == proximity.Match.INSIDE


def run(scenario: Scenario) -> Result:
    """Publish the warning at time 0 and follow it for `duration_s`."""
    mesh, alert = build(scenario)
    mesh.publish(wire.encode(alert))
    times, shares = [], []
    elapsed = 0.0
    while True:
        area = [p for p in mesh.phones.values() if _inside(p, alert)]
        warned = sum(1 for p in area if alert.alert_id in p.first_heard_ms)
        times.append(elapsed)
        shares.append(warned / len(area) if area else 0.0)
        if elapsed >= scenario.duration_s:
            break
        mesh.run(scenario.sample_s)
        elapsed += scenario.sample_s
    area = [p for p in mesh.phones.values() if _inside(p, alert)]
    loud = sum(1 for p in area if p.loudest(alert.alert_id) >= proximity.Urgency.LOUD)
    first = {p.id: (p.first_heard_ms[alert.alert_id] - START_MS) / 1000
             for p in mesh.phones.values() if alert.alert_id in p.first_heard_ms}
    return Result(scenario, times, shares, loud / len(area) if area else 0.0, len(area), first)
