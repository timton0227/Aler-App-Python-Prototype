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

from collections import defaultdict, deque

from alertmesh import geohash, proximity, reports, wire
from alertmesh.alert_store import AlertStore, IngestResult
from alertmesh.report_store import ReportStore

# Mesh message types (Swift: MessageType.officialAlert / .communityReport).
OFFICIAL_ALERT_TYPE = 0x2D
COMMUNITY_REPORT_TYPE = reports.MESSAGE_TYPE  # 0x2E

# TransportConfig.messageTTLDefault: a new broadcast reaches at most 7 hops.
MESSAGE_TTL_DEFAULT = 7
# TransportConfig.bleHighDegreeThreshold: 6 or more neighbours is a "dense" spot.
HIGH_DEGREE_THRESHOLD = 6
# Phone-to-phone Bluetooth reach outdoors. Real range varies from about 10 m to over
# 100 m; 60 m is a middle value. Every run can set its own.
DEFAULT_BLUETOOTH_RANGE_M = 60.0
DEFAULT_TICK_S = 10.0
# GossipSyncManager: warnings and reports are swapped with each neighbour every 60 s,
# and about 5 s after two phones first meet (scheduleInitialSyncToPeer).
SYNC_INTERVAL_S = 60.0

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


@dataclass(frozen=True)
class Notification:
    """A notification a phone showed (Swift: AlertNotificationsModel -> notify)."""

    time_ms: int
    alert_id: bytes
    issued_at: int
    urgency: proximity.Urgency
    reason: proximity.Reason
    headline: str


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
        # When this phone first held each warning event (alert_id -> ms).
        self.first_heard_ms: dict[bytes, int] = {}
        # Every notification shown, and the loudest level per warning VERSION so
        # far (Swift: NotificationLedger), so a version never notifies twice at a level.
        self.notifications: list[Notification] = []
        self._notified: dict[tuple[bytes, int], proximity.Urgency] = {}
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

    def receive(self, msg_type: int, payload: bytes) -> IngestResult:
        """Hand a payload to the right store. The store checks the signature."""
        if msg_type == OFFICIAL_ALERT_TYPE:
            result = self.alert_store.ingest_payload(payload)
            if result is IngestResult.ACCEPTED:
                item = wire.decode(payload)
                if isinstance(item, wire.OfficialAlert):
                    self.first_heard_ms.setdefault(item.alert_id, self.clock())
                    self.evaluate(item)
            return result
        if msg_type == COMMUNITY_REPORT_TYPE:
            return self.report_store.ingest_payload(payload)
        return IngestResult.REJECTED

    # --- Loud or quiet ---

    def decide(self, alert: wire.OfficialAlert) -> proximity.Decision:
        return proximity.decide(
            alert.severity, alert.area_cells, self.geohash(), self.bookmarks,
            None if self.location_on else self.remembered_cell,
        )

    def evaluate(self, alert: wire.OfficialAlert) -> None:
        """Notify if this version now deserves a louder level than it already got.
        Port of AlertNotificationsModel.evaluate."""
        decision = self.decide(alert)
        if decision.urgency <= proximity.Urgency.SILENT:
            return
        key = (alert.alert_id, alert.issued_at)
        if decision.urgency <= self._notified.get(key, proximity.Urgency.SILENT):
            return
        self._notified[key] = decision.urgency
        self.notifications.append(Notification(
            self.clock(), alert.alert_id, alert.issued_at, decision.urgency, decision.reason, alert.headline,
        ))

    def reevaluate(self) -> None:
        """Check every live warning again, e.g. after moving into the area."""
        for alert in self.alert_store.live_alerts():
            self.evaluate(alert)

    def loudest(self, alert_id: bytes) -> proximity.Urgency:
        """The loudest notification this phone has shown for any version of a warning."""
        levels = [n.urgency for n in self.notifications if n.alert_id == alert_id]
        return max(levels, default=proximity.Urgency.SILENT)

    def _remember(self) -> None:
        if self.location_on:
            self.remembered_cell = geohash.encode(self.lat, self.lon, 4)


# --- Relay rule ---------------------------------------------------------------


def relay_ttl(ttl: int, degree: int, urgent: bool) -> int | None:
    """The TTL to relay a broadcast with, or None to stop.

    Port of the broadcast branch of RelayController.decide:
    - dense spots (6+ neighbours) cap at 5 so a crowd does not flood the air;
    - thin chains (2 or fewer neighbours) keep the full depth: every hop counts;
    - otherwise 6, or 7 for an Emergency Warning or an SOS ("the extra hop is what
      reaches the last house").
    """
    cap = min(ttl, MESSAGE_TTL_DEFAULT)
    if cap <= 1:
        return None
    if degree >= HIGH_DEGREE_THRESHOLD:
        limit = max(2, min(cap, 5))
    elif degree <= 2:
        limit = cap
    else:
        limit = max(2, min(cap, 7 if urgent else 6))
    return limit - 1


def is_urgent(msg_type: int, payload: bytes) -> bool:
    """Emergency Warnings and SOS calls get the extra hop. Only asked about payloads
    the store has already accepted, so a forged claim cannot buy hops."""
    if msg_type == OFFICIAL_ALERT_TYPE:
        return wire.severity_peek(payload) == wire.Severity.EMERGENCY_WARNING
    if msg_type == COMMUNITY_REPORT_TYPE:
        return reports.kind_peek(payload) == reports.ReportKind.SOS
    return False


# --- The mesh -----------------------------------------------------------------


class Mesh:
    """All simulated phones, the clock, and the Bluetooth links between them."""

    def __init__(self, start_ms: int = 1_700_000_000_000, tick_s: float = DEFAULT_TICK_S,
                 bluetooth_range_m: float = DEFAULT_BLUETOOTH_RANGE_M):
        self.now_ms = start_ms
        self.tick_s = tick_s
        self.bluetooth_range_m = bluetooth_range_m
        self.phones: dict[str, Phone] = {}
        self._grid: dict[tuple[int, int], list[Phone]] | None = None
        self._next_packet_id = 0
        # Which packets each phone has already handled (Swift: messageDeduplicator).
        self._seen: dict[str, set[int]] = defaultdict(set)
        # (time_ms, phone_id, what, detail): a readable record for the notebook.
        self.log: list[tuple[int, str, str, str]] = []
        self.sync_interval_s = SYNC_INTERVAL_S
        # Warnings published on the internet (Nostr kind 1403 in the app), in order.
        self.internet_feed: list[bytes] = []
        self._pulled: dict[str, int] = defaultdict(int)  # phone id -> how much of the feed it has read
        self._last_sync_ms = start_ms
        self._links: set[frozenset[str]] = set()

    def clock(self) -> int:
        return self.now_ms

    def add_phone(self, phone_id: str, lat: float, lon: float, **options) -> Phone:
        phone = Phone(phone_id, lat, lon, clock=self.clock, **options)
        self.phones[phone_id] = phone
        self._grid = None
        return phone

    # --- Links ---

    def _cell(self, lat: float, lon: float) -> tuple[int, int]:
        size = self.bluetooth_range_m
        return (int(math.floor(lat * EARTH_M_PER_DEGREE / size)),
                int(math.floor(lon * EARTH_M_PER_DEGREE * math.cos(math.radians(lat)) / size)))

    def neighbours(self, phone: Phone) -> list[Phone]:
        """Phones within Bluetooth range, both with Bluetooth on."""
        if not phone.bluetooth_on:
            return []
        if self._grid is None:
            self._grid = defaultdict(list)
            for p in self.phones.values():
                if p.bluetooth_on:
                    self._grid[self._cell(p.lat, p.lon)].append(p)
        row, col = self._cell(phone.lat, phone.lon)
        out = []
        for d_row in (-1, 0, 1):
            for d_col in (-1, 0, 1):
                for other in self._grid.get((row + d_row, col + d_col), ()):
                    if other is not phone and flat_distance_m(phone.lat, phone.lon, other.lat, other.lon) <= self.bluetooth_range_m:
                        out.append(other)
        return out

    # --- Flooding ---

    def broadcast(self, sender: Phone, msg_type: int, payload: bytes, ttl: int = MESSAGE_TTL_DEFAULT) -> int:
        """Send a payload from `sender` to everyone in range, and let it flood.

        A phone relays only what its store ACCEPTED or already held (DUPLICATE),
        like BLEService.handleOfficialAlert; a REJECTED payload goes no further.
        Each phone handles one packet once. Hops within a tick are treated as
        instant: real relays take tens of milliseconds, a tick is 10 seconds.
        Returns how many phones received it.
        """
        packet_id = self._next_packet_id
        self._next_packet_id += 1
        self._seen[sender.id].add(packet_id)
        queue = deque([(sender, ttl)])
        reached = 0
        while queue:
            relayer, packet_ttl = queue.popleft()
            for other in self.neighbours(relayer):
                if packet_id in self._seen[other.id]:
                    continue
                self._seen[other.id].add(packet_id)
                reached += 1
                result = other.receive(msg_type, payload)
                if result is IngestResult.ACCEPTED:
                    self.log.append((self.now_ms, other.id, "received", relayer.id))
                if result is IngestResult.REJECTED:
                    continue
                next_ttl = relay_ttl(packet_ttl, len(self.neighbours(other)), is_urgent(msg_type, payload))
                if next_ttl is not None:
                    queue.append((other, next_ttl))
        return reached

    def send(self, sender: Phone, msg_type: int, payload: bytes) -> IngestResult:
        """A phone sends something of its own: its store must take it first (the
        store is the gate, as in sendOfficialAlertPayload), then it floods."""
        result = sender.receive(msg_type, payload)
        if result is not IngestResult.REJECTED:
            self.broadcast(sender, msg_type, payload)
        return result

    # --- Internet ---

    def publish(self, payload: bytes) -> None:
        """The warning console posts a signed warning or cancellation to the internet.
        Phones online receive it at once (the app keeps a live subscription)."""
        self.internet_feed.append(payload)
        self._pull_internet()

    def _pull_internet(self) -> None:
        """Every phone with internet reads what it has not read yet. What its store
        accepts it hands to its Bluetooth neighbours (OfficialAlertBridge -> mesh),
        which is how one connected phone warns a whole camp."""
        for phone in self.phones.values():
            if not phone.has_internet:
                continue
            start = self._pulled[phone.id]
            for payload in self.internet_feed[start:]:
                if phone.receive(OFFICIAL_ALERT_TYPE, payload) is IngestResult.ACCEPTED:
                    self.log.append((self.now_ms, phone.id, "internet", ""))
                    self.broadcast(phone, OFFICIAL_ALERT_TYPE, payload)
            self._pulled[phone.id] = len(self.internet_feed)

    # --- Carrying: gossip sync ---

    def links(self) -> set[frozenset[str]]:
        """Every pair of phones currently in range of each other."""
        return {frozenset((p.id, n.id)) for p in self.phones.values() for n in self.neighbours(p)}

    def sync_pair(self, a: Phone, b: Phone) -> int:
        """Two neighbours swap what they hold, both ways. Sync replies go out with
        TTL 0 in the app (link-local), so nothing received here is relayed onward;
        it spreads further at the next sync. Returns how many items were new."""
        new = 0
        for giver, taker in ((a, b), (b, a)):
            for payload in giver.alert_store.sync_candidates():
                if taker.receive(OFFICIAL_ALERT_TYPE, payload) is IngestResult.ACCEPTED:
                    new += 1
                    self.log.append((self.now_ms, taker.id, "synced", giver.id))
            for payload in giver.report_store.sync_candidates():
                if taker.receive(COMMUNITY_REPORT_TYPE, payload) is IngestResult.ACCEPTED:
                    new += 1
                    self.log.append((self.now_ms, taker.id, "synced report", giver.id))
        return new

    def _sync(self) -> None:
        links = self.links()
        periodic = self.now_ms - self._last_sync_ms >= self.sync_interval_s * 1000
        if periodic:
            self._last_sync_ms = self.now_ms
        for pair in links if periodic else links - self._links:
            a, b = (self.phones[i] for i in sorted(pair))
            self.sync_pair(a, b)
        self._links = links

    # --- Time ---

    def step(self) -> None:
        """Advance one tick: time moves on, phones on a route drive, phones online
        read the internet, neighbours sync (pairs that just met at once,
        everyone every 60 s), and every phone re-checks how loud each warning is."""
        self.now_ms += int(self.tick_s * 1000)
        for phone in self.phones.values():
            if phone.route:
                phone.move(self.tick_s)
                self._grid = None
        self._pull_internet()
        self._sync()
        for phone in self.phones.values():
            phone.reevaluate()

    def run(self, seconds: float) -> None:
        for _ in range(int(round(seconds / self.tick_s))):
            self.step()
