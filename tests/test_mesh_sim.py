"""Tests for alertmesh.mesh_sim (new code: no Swift tests to port).

The rules being checked come from the Swift app; each test says which one.
"""
from alertmesh import geohash, mesh_sim, wire
from alertmesh.alert_store import IngestResult
from alertmesh.mesh_sim import OFFICIAL_ALERT_TYPE, Mesh, Phone
from alertmesh.signer import OfficialAlertSigner, WarningDraft, new_alert_id
from alertmesh.wire import HazardType, Severity

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


# --- Mesh, flooding, 7-hop limit (step 7.2)


def signed_warning(mesh, severity=Severity.WATCH_AND_ACT, cells=None):
    draft = WarningDraft(HazardType.FLOOD, severity, "Flooding at Katherine", "Move to higher ground.", 6,
                         cells or [geohash.encode(*KATHERINE, 5)])
    return OfficialAlertSigner().sign(draft, new_alert_id(), mesh.now_ms)


def chain(n, spacing_m=50.0, **mesh_options):
    """n phones in a straight line, `spacing_m` apart (each links only to its neighbours)."""
    mesh = Mesh(start_ms=T0, **mesh_options)
    phones = [mesh.add_phone(f"p{i}", *mesh_sim.offset_m(*KATHERINE, 0, i * spacing_m)) for i in range(n)]
    return mesh, phones


def holds(phone, alert):
    return any(a.alert_id == alert.alert_id for a in phone.alert_store.live_alerts())


def test_ttl_a_chain_carries_a_warning_exactly_seven_hops():
    mesh, phones = chain(10)
    alert = signed_warning(mesh)
    assert mesh.send(phones[0], OFFICIAL_ALERT_TYPE, wire.encode(alert)) is IngestResult.ACCEPTED
    assert [holds(p, alert) for p in phones] == [True] * 8 + [False] * 2  # sender + 7 hops


def test_ttl_neighbours_are_within_range_only():
    mesh, phones = chain(3, spacing_m=50, bluetooth_range_m=60)
    assert {p.id for p in mesh.neighbours(phones[1])} == {"p0", "p2"}
    assert {p.id for p in mesh.neighbours(phones[0])} == {"p1"}
    phones[1].bluetooth_on = False
    mesh._grid = None
    assert mesh.neighbours(phones[1]) == []
    assert mesh.neighbours(phones[0]) == []


def test_ttl_relay_rule_matches_relay_controller():
    rt = mesh_sim.relay_ttl
    assert rt(1, 2, False) is None                 # last hop
    assert rt(7, 2, False) == 6                    # thin chain: full depth
    assert rt(7, 4, False) == 5 and rt(7, 4, True) == 6  # middle: 6, urgent 7
    assert rt(7, 6, True) == 4                     # dense: capped at 5
    assert rt(9, 1, False) == 6                    # never above the default of 7
    assert rt(2, 8, False) == 1                    # dense but at least 2


def test_ttl_each_phone_handles_a_packet_once():
    mesh = Mesh(start_ms=T0)
    for i in range(12):  # a tight crowd: everyone hears everyone
        mesh.add_phone(f"c{i}", *mesh_sim.offset_m(*KATHERINE, i, i))
    alert = signed_warning(mesh)
    sender = mesh.phones["c0"]
    sender.receive(OFFICIAL_ALERT_TYPE, wire.encode(alert))
    assert mesh.broadcast(sender, OFFICIAL_ALERT_TYPE, wire.encode(alert)) == 11


def test_ttl_first_heard_is_recorded_once():
    mesh, phones = chain(3)
    alert = signed_warning(mesh)
    mesh.send(phones[0], OFFICIAL_ALERT_TYPE, wire.encode(alert))
    assert phones[2].first_heard_ms[alert.alert_id] == T0
    mesh.run(60)
    mesh.send(phones[0], OFFICIAL_ALERT_TYPE, wire.encode(alert))  # sent again later
    assert phones[2].first_heard_ms[alert.alert_id] == T0
