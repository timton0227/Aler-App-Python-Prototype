"""A simulated Bluetooth mesh: phones on a map passing warnings and reports along.

New code, with no Swift file to port. The behaviour follows the app:
- TTL values and relay rules: ../alert-mesh/AlertMesh/Services/TransportConfig.swift,
  ../alert-mesh/AlertMesh/Services/RelayController.swift
- what is relayed: BLEService.handleOfficialAlert (only what the store accepts)
- carrying: GossipSyncManager (every 60 s, neighbours swap what they hold, one hop)
- internet: OfficialAlertBridge (phones online pull warnings and hand them to the mesh)

Each simulated phone runs the REAL wire, store and proximity code from this package,
so a forged warning is stopped exactly where the app would stop it.

This is free and unencumbered software released into the public domain.
"""
import math
from dataclasses import dataclass, field

from alertmesh import geohash, reports
from alertmesh.alert_store import AlertStore
from alertmesh.report_store import ReportStore

# Mesh message types (Swift: MessageType.officialAlert / .communityReport).
OFFICIAL_ALERT_TYPE = 0x2D
COMMUNITY_REPORT_TYPE = reports.MESSAGE_TYPE  # 0x2E

EARTH_M_PER_DEGREE = 111_195.0  # metres per degree of latitude (Earth radius 6371 km)


def offset_m(lat: float, lon: float, north_m: float, east_m: float) -> tuple[float, float]:
    """A point `north_m` metres north and `east_m` metres east of (lat, lon).
    Flat-earth: fine over the few kilometres a simulation covers."""
    return (
        lat + north_m / EARTH_M_PER_DEGREE,
        lon + east_m / (EARTH_M_PER_DEGREE * math.cos(math.radians(lat))),
    )


def flat_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Flat-earth distance in metres, accurate at Bluetooth ranges."""
    d_north = (lat2 - lat1) * EARTH_M_PER_DEGREE
    d_east = (lon2 - lon1) * EARTH_M_PER_DEGREE * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(d_north, d_east)


@dataclass
class Phone:
    """One simulated phone.

    `clock` returns the simulation time in milliseconds; the phone's stores use it.
    A phone with a `route` drives along it at `speed_mps` (metres per second).
    """

    id: str
    lat: float
    lon: float
    clock: object
    has_internet: bool = False
    bluetooth_on: bool = True
    # Location permission. Off means no live area code: warnings stay quiet unless
    # a bookmark or the remembered area matches.
    location_on: bool = True
    bookmarks: tuple[str, ...] = ()
    route: list[tuple[float, float]] = field(default_factory=list)
    speed_mps: float = 0.0
    nickname: str = ""

    def __post_init__(self):
        self.alert_store = AlertStore(clock=self.clock)
        self.report_store = ReportStore(clock=self.clock)
        self.author = reports.ReportAuthor(self.nickname or self.id)
        # The last rough area (4 characters, ~40 km) seen with location on
        # (Swift: RememberedArea). Used when location is off.
        self.remembered_cell: str | None = None
        self._remember()

    def geohash(self, precision: int = 8) -> str | None:
        """The phone's own area code, or None when location is off.
        8 characters (about 20 m) is the building level the app uses."""
        return geohash.encode(self.lat, self.lon, precision) if self.location_on else None

    def move(self, seconds: float) -> None:
        """Drive along the route for `seconds`. Stops at the last waypoint."""
        left = self.speed_mps * seconds
        while left > 0 and self.route:
            target_lat, target_lon = self.route[0]
            gap = flat_distance_m(self.lat, self.lon, target_lat, target_lon)
            if gap <= left:
                self.lat, self.lon = target_lat, target_lon
                self.route.pop(0)
                left -= gap
            else:
                share = left / gap
                self.lat += (target_lat - self.lat) * share
                self.lon += (target_lon - self.lon) * share
                left = 0
        self._remember()

    def _remember(self) -> None:
        if self.location_on:
            self.remembered_cell = geohash.encode(self.lat, self.lon, 4)
