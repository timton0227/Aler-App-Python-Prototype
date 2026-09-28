"""Geo relays: the Nostr relays nearest a place.

Ported from: alert-mesh/AlertMesh/Nostr/GeoRelayDirectory.swift (validatedEntries,
             validatedDirectoryAddress, closestRelays, haversineKm, loading and the
             daily refresh) and alert-mesh/AlertMesh/AlertMesh/Utils/AustralianAreas.swift
             (the anchors of the Australia-wide and state rooms).
Data:        alert-mesh/relays/online_relays_gps.csv, copied unchanged into
             alertmesh/data/ (see alertmesh/swift_app.py).

The iPhone app sends a call for help to the 5 relays nearest its 4-character cell, and
a phone asks the 5 relays nearest each cell around it. Both must pick the same relays,
so both read the same list (a relay's address and where it is) and pick the nearest
the same way, ties broken by address. The list comes with the app and is refreshed
once a day from the address below; a download is used only if it passes every check,
and only if it keeps at least half of the relays already known, so a broken or
hostile download cannot swap the list out.

This is free and unencumbered software released into the public domain.
"""
import math
import re
import ssl
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from alertmesh import geohash

REMOTE_URL = "https://raw.githubusercontent.com/permissionlesstech/bitchat/refs/heads/main/relays/online_relays_gps.csv"
CSV_NAME = "online_relays_gps.csv"
CSV_CANDIDATES = (
    Path(__file__).resolve().parent / "data" / CSV_NAME,
)

# GeoRelayDirectoryValidationPolicy.live
MAX_BYTES = 512 * 1024
MAX_ROWS = 5_000
MAX_ENTRIES = 5_000
MIN_REMOTE_ENTRIES = 50
MIN_RETAINED_FRACTION = 0.5

RELAY_COUNT = 5  # TransportConfig.nostrGeoRelayCount
FETCH_INTERVAL_S = 24 * 60 * 60  # TransportConfig.geoRelayFetchIntervalSeconds
RETRY_INITIAL_S = 60  # after a failed download, try again after 1, 2, 4 ... minutes,
RETRY_MAX_S = 60 * 60  # up to an hour apart (geoRelayRetryInitialSeconds, geoRelayRetryMaxSeconds)
FETCH_TIMEOUT_S = 20

HEADERS = (["relay url", "latitude", "longitude"], ["relay url", "lat", "lon"])
# A plain decimal number in ASCII digits. Python's float() would also take "1_0" and
# other scripts' digits, which Swift's Double() refuses.
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_LABEL = re.compile(r"[a-z0-9-]{1,63}")

# The Australia-wide and state rooms are not geohashes: their relays are the ones
# nearest the room's anchor (AustralianAreas: the country's centre, each capital).
AREA_ANCHORS = {
    "au": (-25.2744, 133.7751),
    "au-nsw": (-33.8688, 151.2093),
    "au-vic": (-37.8136, 144.9631),
    "au-qld": (-27.4698, 153.0251),
    "au-wa": (-31.9523, 115.8613),
    "au-sa": (-34.9285, 138.6007),
    "au-tas": (-42.8821, 147.3272),
    "au-act": (-35.2809, 149.1300),
    "au-nt": (-12.4634, 130.8456),
}


@dataclass(frozen=True, order=True)
class Entry:
    host: str  # "relay.example", or "relay.example:8443" for a port other than 443
    lat: float
    lon: float


def _address(raw: str) -> str | None:
    """A relay's address as the list gives it, reduced to its host (and port), or None
    if it is not a plain secure public address (validatedDirectoryAddress)."""
    value = raw.strip()
    if not value or not all(" " <= c <= "~" for c in value):
        return None  # empty, not ASCII, or a control character
    try:
        parts = urlsplit(value if "://" in value else "wss://" + value)
        port = parts.port
    except ValueError:
        return None
    if (parts.scheme.lower() not in ("wss", "https") or parts.username is not None or parts.password is not None
            or "?" in value or "#" in value or parts.path not in ("", "/") or not parts.hostname):
        return None
    host = parts.hostname.lower()
    if (len(host) > 253 or host.endswith(".") or host == "localhost"
            or host.endswith((".localhost", ".local", ".internal"))):
        return None
    labels = host.split(".")
    if len(labels) < 2 or all(label.isdigit() for label in labels):
        return None
    if not all(_LABEL.fullmatch(label) and label[0] != "-" and label[-1] != "-" for label in labels):
        return None
    if port is not None:
        if not 1 <= port <= 65_535:
            return None
        if port != 443:
            return f"{host}:{port}"
    return host


def _number(text: str, limit: float) -> float | None:
    if not _NUMBER.fullmatch(text):
        return None
    value = float(text)
    return value if math.isfinite(value) and -limit <= value <= limit else None


def validated_entries(data: bytes, minimum_entries: int = 1, baseline=None, max_bytes: int = MAX_BYTES,
                      max_rows: int = MAX_ROWS, max_entries: int = MAX_ENTRIES,
                      min_retained_fraction: float = MIN_RETAINED_FRACTION) -> list[Entry] | None:
    """The relays in a list, sorted, or None if anything in it is wrong: the whole list
    is trusted or none of it. `baseline` is the list already held: at least
    `min_retained_fraction` of it must be in the new one, at the same places."""
    if not data or len(data) > max_bytes:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if text.startswith("\ufeff"):
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or len(lines) - 1 > max_rows:
        return None
    if [part.strip().lower() for part in lines[0].split(",")] not in HEADERS:
        return None
    by_host: dict[str, Entry] = {}
    for line in lines[1:]:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 3:
            return None
        host, lat, lon = _address(parts[0]), _number(parts[1], 90.0), _number(parts[2], 180.0)
        if host is None or lat is None or lon is None:
            return None
        entry = Entry(host, lat, lon)
        if by_host.get(host, entry) != entry:
            return None  # one relay in two places: row order must not decide which to trust
        by_host[host] = entry
        if len(by_host) > max_entries:
            return None
    entries = set(by_host.values())
    if len(entries) < minimum_entries:
        return None
    if baseline is not None:
        baseline = set(baseline)
        if len(entries & baseline) < math.ceil(len(baseline) * min_retained_fraction):
            return None
    return sorted(entries)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2)
    return 6371.0 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def closest(entries, lat: float, lon: float, count: int = RELAY_COUNT) -> list[str]:
    """Up to `count` relays nearest a point, as wss:// addresses. Ties go by address,
    so every device with the same list picks the same relays."""
    if count <= 0:
        return []
    ranked = sorted(entries, key=lambda e: (haversine_km(lat, lon, e.lat, e.lon), e.host))
    return [f"wss://{e.host}" for e in ranked[:count]]


def closest_to_cell(entries, cell: str, count: int = RELAY_COUNT) -> list[str]:
    """Up to `count` relays nearest a geohash cell's centre, or a room's anchor."""
    anchor = AREA_ANCHORS.get(cell.lower())
    lat, lon = anchor if anchor else geohash.decode_center(cell)
    return closest(entries, lat, lon, count)


def _https_context() -> ssl.SSLContext:
    """Certificates from certifi when it is there: python.org's Python on a Mac, and
    the packaged app, have none of their own until set up."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def download(url: str = REMOTE_URL) -> bytes:
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_S, context=_https_context()) as response:
        return response.read(MAX_BYTES + 1)


class Directory:
    """The relay list one app uses. Starts from the list that comes with the app;
    `refresh_if_due()` downloads a newer one at most once a day."""

    def __init__(self, candidates=CSV_CANDIDATES, fetch=download, clock=time.time):
        self.entries: list[Entry] = []
        for path in candidates:
            try:
                entries = validated_entries(Path(path).read_bytes())
            except OSError:
                continue
            if entries:
                self.entries = entries
                break
        self._fetch = fetch
        self._clock = clock
        self._next_fetch = None  # due at once
        self._failures = 0
        self._lock = threading.Lock()

    def relays_for(self, cell: str, count: int = RELAY_COUNT) -> list[str]:
        with self._lock:
            return closest_to_cell(self.entries, cell, count)

    def refresh_if_due(self) -> bool:
        """Download the list when due: once a day, or sooner after a failed try. True
        if the list changed. A failed or refused download keeps the list held."""
        now = self._clock()
        if self._next_fetch is not None and now < self._next_fetch:
            return False
        try:
            data = self._fetch()
        except Exception:  # no network, a timeout, a certificate problem: keep what we have
            data = None
        with self._lock:
            entries = None if data is None else validated_entries(data, MIN_REMOTE_ENTRIES,
                                                                  baseline=self.entries or None)
            if entries is None:
                self._failures = min(self._failures + 1, 10)
                self._next_fetch = now + min(RETRY_MAX_S, RETRY_INITIAL_S * 2 ** (self._failures - 1))
                return False
            self._failures = 0
            self._next_fetch = now + FETCH_INTERVAL_S
            changed = entries != self.entries
            self.entries = entries
            return changed
