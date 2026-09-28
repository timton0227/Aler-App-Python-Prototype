"""Tests for alertmesh.georelays.

Ported from: ../alert-mesh/AlertMeshTests/Nostr/GeoRelayDirectoryTests.swift and
             ../alert-mesh/AlertMeshTests/AlertMesh/Utils/AustralianAreasTests.swift
             (relaysForARoomComeFromItsAnchor).
"""
import pytest

from alertmesh import geohash, georelays
from alertmesh.georelays import Entry


def parse(csv: str):
    return georelays.validated_entries(csv.encode()) or []


def test_parse_csv_normalizes_secure_relay_schemes_and_deduplicates_entries():
    csv = """relay url,lat,lon
wss://one.example/,10,20
https://one.example,10,20
wss://one.example:443/,10,20
two.example,11,21
wss://two.example:443,11,21
"""
    assert set(parse(csv)) == {Entry("one.example", 10, 20), Entry("two.example", 11, 21)}


def test_a_port_other_than_443_is_kept():
    assert parse("relay url,lat,lon\nwss://one.example:8443,1,2\n") == [Entry("one.example:8443", 1, 2)]


# Written with chr() so this file holds no unusual characters itself.
E_ACUTE, RTL_OVERRIDE = chr(0xE9), chr(0x202E)
ARABIC_10, FULLWIDTH_10 = chr(0x661) + chr(0x660), chr(0xFF11) + chr(0xFF10)


@pytest.mark.parametrize("csv", [
    "relay,lat,lon\nrelay.example,1,2\n",
    "relay url,lat,lon\nrelay.example,1\n",
    "relay url,lat,lon\nhttp://relay.example,1,2\n",
    "relay url,lat,lon\nwss://user@relay.example,1,2\n",
    "relay url,lat,lon\nwss://relay.example/path,1,2\n",
    "relay url,lat,lon\nwss://relay.example?,1,2\n",
    "relay url,lat,lon\nwss://relay.example#,1,2\n",
    "relay url,lat,lon\nrelay.example:0,1,2\n",
    "relay url,lat,lon\nrelay.example:99999,1,2\n",
    "relay url,lat,lon\nlocalhost,1,2\n",
    f"relay url,lat,lon\nr{E_ACUTE}lay.example,1,2\n",
    f"relay url,lat,lon\nrelay{RTL_OVERRIDE}.example,1,2\n",
    "relay url,lat,lon\nrelay.example,NaN,2\n",
    "relay url,lat,lon\nrelay.example,1_0,2\n",
    f"relay url,lat,lon\nrelay.example,{ARABIC_10},2\n",
    f"relay url,lat,lon\nrelay.example,{FULLWIDTH_10},2\n",
    "relay url,lat,lon\nrelay.example,91,2\n",
    "relay url,lat,lon\nrelay.example,1,181\n",
    "relay url,lat,lon\nrelay.example,1,2\nrelay.example,3,4\n",
    # Not in the Swift list, from the same rules:
    "relay url,lat,lon\nrelay.local,1,2\n",
    "relay url,lat,lon\n10.0.0.1,1,2\n",
    "relay url,lat,lon\n-relay.example,1,2\n",
    "relay url,lat,lon\nsingle,1,2\n",
    "relay url,lat,lon\nrelay.example,inf,2\n",
])
def test_parse_csv_rejects_whole_dataset_when_any_row_or_header_is_unsafe(csv):
    assert parse(csv) == []


def test_a_byte_order_mark_or_undecodable_bytes_are_refused():
    assert georelays.validated_entries(b"\xef\xbb\xbfrelay url,lat,lon\none.example,1,2\n") is None
    assert georelays.validated_entries(b"relay url,lat,lon\n\xff.example,1,2\n") is None


def test_validated_entries_enforces_byte_row_entry_and_retention_limits():
    one = b"relay url,lat,lon\none.example,1,2\n"
    three = b"relay url,lat,lon\none.example,1,2\ntwo.example,3,4\nthree.example,5,6\n"
    limits = {"max_bytes": 100, "max_rows": 2, "max_entries": 2}
    assert georelays.validated_entries(one, 2, **limits) is None
    assert georelays.validated_entries(b"A" * 101, 1, **limits) is None
    assert georelays.validated_entries(three, 1, **limits) is None


def test_validated_entries_requires_exact_baseline_entry_overlap():
    baseline = parse("relay url,lat,lon\none.example,1,1\ntwo.example,2,2\nthree.example,3,3\n")
    disjoint = b"relay url,lat,lon\nfour.example,1,1\nfive.example,2,2\nsix.example,3,3\n"
    moved = b"relay url,lat,lon\none.example,11,11\ntwo.example,12,12\nthree.example,13,13\n"
    half_kept = b"relay url,lat,lon\nwss://one.example:443/,1,1\nhttps://two.example/,2,2\nreplacement.example,4,4\n"
    assert georelays.validated_entries(disjoint, 1, baseline=baseline) is None
    assert georelays.validated_entries(moved, 1, baseline=baseline) is None
    assert georelays.validated_entries(half_kept, 1, baseline=baseline) is not None


def test_the_swift_apps_list_passes_the_strict_checks():
    path = georelays.CSV_CANDIDATES[0]
    if not path.exists():
        pytest.skip("the Swift app is not next to this folder")
    entries = georelays.validated_entries(path.read_bytes(), georelays.MIN_REMOTE_ENTRIES)
    assert entries is not None and len(entries) > 250


SAN_FRANCISCO = """relay url,lat,lon
close.example,37.7749,-122.4194
medium.example,34.0522,-118.2437
far.example,40.7128,-74.0060
"""


def test_closest_relays_sorts_by_distance_for_lat_lon_and_geohash():
    entries = parse(SAN_FRANCISCO)
    assert georelays.closest(entries, 37.78, -122.41, 2) == ["wss://close.example", "wss://medium.example"]
    assert georelays.closest(entries, 37.78, -122.41, 10) == [
        "wss://close.example", "wss://medium.example", "wss://far.example"]
    cell = geohash.encode(37.78, -122.41, 6)
    assert georelays.closest_to_cell(entries, cell, 2) == ["wss://close.example", "wss://medium.example"]


def test_closest_relays_breaks_distance_ties_deterministically_by_host():
    entries = parse("relay url,lat,lon\nzeta.example,10,10\nalpha.example,10,10\nmike.example,10,10\n")
    assert georelays.closest(entries, 10, 10, 2) == ["wss://alpha.example", "wss://mike.example"]


def test_relays_for_a_room_come_from_its_anchor():
    entries = parse("relay url,lat,lon\nsydney.example,-33.87,151.21\nperth.example,-31.95,115.86\n")
    assert georelays.closest_to_cell(entries, "au-nsw", 1) == ["wss://sydney.example"]
    assert georelays.closest_to_cell(entries, "au-wa", 1) == ["wss://perth.example"]


def test_the_directory_starts_from_the_first_list_it_can_read(tmp_path):
    good = tmp_path / "good.csv"
    good.write_text(SAN_FRANCISCO)
    broken = tmp_path / "broken.csv"
    broken.write_text("nonsense")
    directory = georelays.Directory([tmp_path / "missing.csv", broken, good], fetch=None)
    assert len(directory.entries) == 3
    assert directory.relays_for(geohash.encode(37.78, -122.41, 4), 1) == ["wss://close.example"]


def big_list(n: int, shift: float = 0.0) -> bytes:
    rows = "".join(f"relay{i}.example,{(i % 80) + shift},{i % 170}\n" for i in range(n))
    return ("relay url,lat,lon\n" + rows).encode()


def directory_with(tmp_path, fetch, clock):
    start = tmp_path / "start.csv"
    start.write_bytes(big_list(60))
    return georelays.Directory([start], fetch=fetch, clock=clock)


def test_a_good_download_replaces_the_list_at_most_once_a_day(tmp_path):
    now = [1000.0]
    calls = []

    def fetch():
        calls.append(now[0])
        return big_list(70)

    directory = directory_with(tmp_path, fetch, lambda: now[0])
    assert directory.refresh_if_due() and len(directory.entries) == 70
    now[0] += 60
    assert not directory.refresh_if_due() and len(calls) == 1
    now[0] += georelays.FETCH_INTERVAL_S
    assert not directory.refresh_if_due() and len(calls) == 2  # same list: nothing changed


def test_a_failed_or_suspicious_download_keeps_the_list(tmp_path):
    def offline():
        raise OSError("no network")

    directory = directory_with(tmp_path, offline, lambda: 0.0)
    assert not directory.refresh_if_due() and len(directory.entries) == 60
    for data in (big_list(10), big_list(60, shift=5.0), b"<html>not a list</html>"):
        directory = directory_with(tmp_path, lambda d=data: d, lambda: 0.0)
        assert not directory.refresh_if_due() and len(directory.entries) == 60


def test_after_a_failure_it_tries_again_sooner_and_sooner_then_hourly(tmp_path):
    now = [0.0]
    calls = []

    def offline():
        calls.append(now[0])
        raise OSError("no network")

    directory = directory_with(tmp_path, offline, lambda: now[0])
    for _ in range(20):
        directory.refresh_if_due()
        now[0] += 30
    gaps = [b - a for a, b in zip(calls, calls[1:])]
    assert gaps[:3] == [60, 120, 240]
    now[0] += georelays.RETRY_MAX_S
    directory.refresh_if_due()
    assert calls[-1] == now[0]
