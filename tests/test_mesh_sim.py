"""Tests for alertmesh.mesh_sim (new code: no Swift tests to port).

The rules being checked come from the Swift app; each test says which one.
"""
from alertmesh import geohash, mesh_sim
from alertmesh.mesh_sim import Phone

KATHERINE = (-14.465, 132.263)
T0 = 1_700_000_000_000


def clock():
    return T0


def test_phone_has_its_own_stores_and_area_code():
    phone = Phone("a", *KATHERINE, clock=clock)
    other = Phone("b", *KATHERINE, clock=clock)
    assert phone.alert_store is not other.alert_store
    assert phone.report_store is not other.report_store
    assert phone.geohash().startswith("qvqj9w")  # Katherine, checked in step 6.2
    assert phone.geohash() == geohash.encode(*KATHERINE, 8)
    assert phone.remembered_cell == phone.geohash()[:4]


def test_phone_with_location_off_has_no_area_code_but_keeps_the_remembered_one():
    phone = Phone("a", *KATHERINE, clock=clock)
    remembered = phone.remembered_cell
    phone.location_on = False
    phone.move(0)
    assert phone.geohash() is None
    assert phone.remembered_cell == remembered


def test_phone_moves_along_its_route_and_stops_at_the_end():
    start = KATHERINE
    end = mesh_sim.offset_m(*start, north_m=0, east_m=1000)
    phone = Phone("car", *start, clock=clock, route=[end], speed_mps=20)
    phone.move(10)  # 200 m
    assert abs(mesh_sim.flat_distance_m(*start, phone.lat, phone.lon) - 200) < 0.5
    phone.move(100)  # would be 2 km: stops at 1 km
    assert (phone.lat, phone.lon) == end
    assert phone.route == []


def test_phone_offset_and_distance_agree():
    lat, lon = mesh_sim.offset_m(*KATHERINE, north_m=300, east_m=400)
    assert abs(mesh_sim.flat_distance_m(*KATHERINE, lat, lon) - 500) < 0.5
