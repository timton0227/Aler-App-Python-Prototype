"""Tests for alertmesh.mesh_sim (new code: no Swift tests to port).

The rules being checked come from the Swift app; each test says which one.
"""
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from alertmesh import geohash, mesh_sim, reports, wire
from alertmesh.alert_store import IngestResult
from alertmesh.mesh_sim import COMMUNITY_REPORT_TYPE, OFFICIAL_ALERT_TYPE, Mesh, Phone
from alertmesh.proximity import ReasonKind, Urgency
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


# --- Only verified packets relay (step 7.3)


def forged_warning(mesh):
    """Structurally perfect, signed by an attacker's key instead of the publisher's."""
    attacker = OfficialAlertSigner(Ed25519PrivateKey.generate().private_bytes_raw())
    draft = WarningDraft(HazardType.BUSHFIRE, Severity.EMERGENCY_WARNING, "Fake fire - leave now",
                         "Drive south.", 6, [geohash.encode(*KATHERINE, 5)])
    return attacker.sign(draft, new_alert_id(), mesh.now_ms)


def test_forged_warning_is_refused_by_the_senders_own_store():
    mesh, phones = chain(5)
    assert mesh.send(phones[0], OFFICIAL_ALERT_TYPE, wire.encode(forged_warning(mesh))) is IngestResult.REJECTED
    assert all(p.alert_store.live_alerts() == [] for p in phones)


def test_forged_warning_from_a_modified_phone_stops_at_the_first_hop():
    # A modified phone skips its own store and floods anyway: its neighbour hears
    # it, rejects it, and passes nothing on.
    mesh, phones = chain(5)
    reached = mesh.broadcast(phones[0], OFFICIAL_ALERT_TYPE, wire.encode(forged_warning(mesh)))
    assert reached == 1
    assert all(p.alert_store.live_alerts() == [] and p.alert_store.sync_candidates() == [] for p in phones)
    assert all(not p.first_heard_ms for p in phones)


def test_forged_tampered_copy_of_a_real_warning_goes_nowhere():
    mesh, phones = chain(5)
    real = signed_warning(mesh, Severity.EMERGENCY_WARNING)
    downgraded = wire.OfficialAlert(real.alert_id, real.hazard_code, Severity.ADVICE, real.area_cells,
                                    real.headline, real.action_text, real.issued_at, real.expires_at, real.signature)
    assert mesh.broadcast(phones[0], OFFICIAL_ALERT_TYPE, wire.encode(downgraded)) == 1
    assert all(p.alert_store.live_alerts() == [] for p in phones)


def test_forged_report_claiming_someone_elses_key_goes_nowhere():
    mesh, phones = chain(5)
    victim_sos = phones[4].author.sos(phones[4].geohash(), "help", mesh.now_ms)
    fake = reports.CommunityReport(reports.ReportKind.SAFE, victim_sos.report_id, victim_sos.geohash, 0, None, "",
                                   victim_sos.author_signing_key, "tim", mesh.now_ms + 1, mesh.now_ms + 60_000,
                                   bytes(64))
    assert mesh.broadcast(phones[0], COMMUNITY_REPORT_TYPE, reports.encode(fake)) == 1
    assert all(p.report_store.live_reports() == [] for p in phones)


def test_forged_the_real_warning_still_spreads_alongside():
    mesh, phones = chain(5)
    mesh.broadcast(phones[0], OFFICIAL_ALERT_TYPE, wire.encode(forged_warning(mesh)))
    real = signed_warning(mesh)
    mesh.send(phones[0], OFFICIAL_ALERT_TYPE, wire.encode(real))
    assert all([a.alert_id for a in p.alert_store.live_alerts()] == [real.alert_id] for p in phones)


# --- Carrying: sync and moving phones (step 7.4)


def two_camps(gap_m=5_000):
    """Camp A (3 phones) and camp B (3 phones), `gap_m` apart: no Bluetooth path between them."""
    mesh = Mesh(start_ms=T0)
    a = [mesh.add_phone(f"a{i}", *mesh_sim.offset_m(*KATHERINE, 0, i * 20)) for i in range(3)]
    b = [mesh.add_phone(f"b{i}", *mesh_sim.offset_m(*KATHERINE, 0, gap_m + i * 20)) for i in range(3)]
    return mesh, a, b


def test_carry_a_group_out_of_range_hears_nothing_without_a_carrier():
    mesh, a, b = two_camps()
    alert = signed_warning(mesh)
    mesh.send(a[0], OFFICIAL_ALERT_TYPE, wire.encode(alert))
    mesh.run(3600)
    assert all(holds(p, alert) for p in a)
    assert not any(holds(p, alert) for p in b)


def test_carry_a_driving_phone_brings_the_warning_to_the_other_camp():
    mesh, a, b = two_camps(gap_m=5_000)
    car = mesh.add_phone("car", *mesh_sim.offset_m(*KATHERINE, 0, 30),
                         route=[mesh_sim.offset_m(*KATHERINE, 0, 5_000 + 30)], speed_mps=15)
    alert = signed_warning(mesh)
    mesh.send(a[0], OFFICIAL_ALERT_TYPE, wire.encode(alert))
    assert holds(car, alert)  # in range at the start: flooded
    assert not any(holds(p, alert) for p in b)
    mesh.run(5 * 60)  # 5 km at 15 m/s is about 5.6 minutes
    assert not any(holds(p, alert) for p in b)
    mesh.run(2 * 60)
    assert all(holds(p, alert) for p in b)  # carried, then synced
    arrived = min(p.first_heard_ms[alert.alert_id] for p in b)
    assert 5 * 60_000 < arrived - T0 <= 7 * 60_000


def test_carry_sync_reaches_a_phone_that_was_off_during_the_flood():
    mesh, phones = chain(3)
    phones[2].bluetooth_on = False
    mesh._grid = None
    alert = signed_warning(mesh)
    mesh.send(phones[0], OFFICIAL_ALERT_TYPE, wire.encode(alert))
    assert not holds(phones[2], alert)
    phones[2].bluetooth_on = True
    mesh._grid = None
    mesh.step()  # newly linked pair syncs at once
    assert holds(phones[2], alert)


def test_carry_sync_replies_are_not_flooded_onward():
    # p2 is off during the flood. When it comes back it syncs from p1, but does not
    # flood: p3, which is also new, only gets it from p2 by sync, one hop per sync.
    mesh, phones = chain(4)
    for p in phones[2:]:
        p.bluetooth_on = False
    mesh._grid = None
    alert = signed_warning(mesh)
    mesh.send(phones[0], OFFICIAL_ALERT_TYPE, wire.encode(alert))
    for p in phones[2:]:
        p.bluetooth_on = True
    mesh._grid = None
    before = mesh._next_packet_id
    mesh.step()
    assert mesh._next_packet_id == before  # no new broadcast was made
    assert holds(phones[2], alert)


def test_carry_periodic_sync_runs_every_60_seconds():
    mesh, phones = chain(2)
    mesh.step()  # first links recorded
    alert = signed_warning(mesh)
    phones[0].receive(OFFICIAL_ALERT_TYPE, wire.encode(alert))  # held but never broadcast
    for _ in range(4):
        mesh.step()
    assert not holds(phones[1], alert)  # 50 s: not yet
    mesh.step()
    mesh.step()
    assert holds(phones[1], alert)  # by 60 s


# --- Internet (step 7.5)


def test_internet_phones_online_receive_a_published_warning_at_once():
    mesh, a, b = two_camps()
    b[1].has_internet = True
    alert = signed_warning(mesh)
    mesh.publish(wire.encode(alert))
    assert holds(b[1], alert)
    assert not any(holds(p, alert) for p in a)


def test_internet_one_connected_phone_warns_its_whole_camp_over_bluetooth():
    mesh, a, b = two_camps()
    b[1].has_internet = True
    alert = signed_warning(mesh)
    mesh.publish(wire.encode(alert))
    assert all(holds(p, alert) for p in b)
    assert all(p.first_heard_ms[alert.alert_id] == T0 for p in b)


def test_internet_a_phone_that_comes_online_later_catches_up():
    mesh, a, b = two_camps()
    alert = signed_warning(mesh)
    mesh.publish(wire.encode(alert))
    assert not any(holds(p, alert) for p in a + b)
    a[2].has_internet = True
    mesh.step()
    assert all(holds(p, alert) for p in a)


def test_internet_forged_warnings_on_the_internet_are_dropped():
    mesh, a, b = two_camps()
    for p in a:
        p.has_internet = True
    mesh.publish(wire.encode(forged_warning(mesh)))
    assert all(p.alert_store.live_alerts() == [] for p in a + b)


def test_internet_cancellation_reaches_phones_through_the_same_route():
    mesh, a, b = two_camps()
    b[0].has_internet = True
    signer = OfficialAlertSigner()
    alert = signed_warning(mesh)
    mesh.publish(wire.encode(alert))
    mesh.run(60)
    mesh.publish(wire.encode(signer.cancel(alert.alert_id, mesh.now_ms)))
    assert all(p.alert_store.live_alerts() == [] for p in b)


# --- Loud or quiet on each phone (step 7.6)


def town_with_outsider(outsider_km=50):
    """Three phones in town and one far away, all with internet, so each hears every warning."""
    mesh = Mesh(start_ms=T0)
    town = [mesh.add_phone(f"t{i}", *mesh_sim.offset_m(*KATHERINE, 0, i * 30)) for i in range(3)]
    far = mesh.add_phone("far", *mesh_sim.offset_m(*KATHERINE, outsider_km * 1000, 0), has_internet=True)
    for p in town:
        p.has_internet = True
    return mesh, town, far


def test_urgency_inside_the_area_at_watch_and_act_is_loud_elsewhere_quiet():
    mesh, town, far = town_with_outsider()
    alert = signed_warning(mesh, Severity.WATCH_AND_ACT, cells=[geohash.encode(*KATHERINE, 5)])
    mesh.publish(wire.encode(alert))
    assert all(p.loudest(alert.alert_id) is Urgency.LOUD for p in town)
    assert town[0].notifications[0].reason.kind is ReasonKind.INSIDE_AREA
    assert far.loudest(alert.alert_id) is Urgency.QUIET  # everyone hears, far away gently
    assert far.notifications[0].reason.kind is ReasonKind.OUTSIDE_AREA


def test_urgency_advice_inside_is_quiet():
    mesh, town, far = town_with_outsider()
    alert = signed_warning(mesh, Severity.ADVICE)
    mesh.publish(wire.encode(alert))
    assert all(p.loudest(alert.alert_id) is Urgency.QUIET for p in town)


def test_urgency_a_version_notifies_once_per_level_and_an_update_notifies_again():
    mesh, town, far = town_with_outsider()
    alert = signed_warning(mesh, Severity.WATCH_AND_ACT)
    mesh.publish(wire.encode(alert))
    mesh.run(120)
    assert len(town[0].notifications) == 1
    signer = OfficialAlertSigner()
    draft = WarningDraft.updating(alert, mesh.now_ms)
    draft.severity = Severity.EMERGENCY_WARNING
    mesh.publish(wire.encode(signer.sign(draft, alert.alert_id, mesh.now_ms)))
    assert len(town[0].notifications) == 2


def test_urgency_driving_into_the_area_raises_quiet_to_loud():
    mesh = Mesh(start_ms=T0)
    target = geohash.encode(*KATHERINE, 5)
    start = mesh_sim.offset_m(*KATHERINE, 0, -20_000)  # 20 km west
    car = mesh.add_phone("car", *start, has_internet=True, route=[KATHERINE], speed_mps=25)
    alert = signed_warning(mesh, Severity.EMERGENCY_WARNING, cells=[target])
    mesh.publish(wire.encode(alert))
    assert car.loudest(alert.alert_id) is Urgency.QUIET
    mesh.run(20 * 60)
    assert car.loudest(alert.alert_id) is Urgency.LOUD
    assert [n.urgency for n in car.notifications] == [Urgency.QUIET, Urgency.LOUD]


def test_urgency_location_off_uses_bookmarks_or_the_remembered_area():
    mesh, town, far = town_with_outsider()
    town[0].location_on = False                      # remembers Katherine's rough area
    town[1].location_on = False
    town[1].remembered_cell = None
    town[1].bookmarks = (geohash.encode(*KATHERINE, 6),)  # watches their suburb
    town[2].location_on = False
    town[2].remembered_cell = None                   # knows nothing
    alert = signed_warning(mesh, Severity.EMERGENCY_WARNING)
    mesh.publish(wire.encode(alert))
    assert town[0].notifications[0].reason.kind is ReasonKind.LAST_KNOWN_AREA
    assert town[1].notifications[0].reason.kind is ReasonKind.WATCHED_PLACE_INSIDE_AREA
    assert town[0].loudest(alert.alert_id) is town[1].loudest(alert.alert_id) is Urgency.LOUD
    assert town[2].loudest(alert.alert_id) is Urgency.QUIET  # never silent
    assert town[2].notifications[0].reason.kind is ReasonKind.LOCATION_UNKNOWN


# --- SOS and reports through the same mesh (step 7.7)


def test_sos_floods_and_nearby_phones_are_told_loudly():
    mesh, phones = chain(5)
    sos = mesh.send_sos(phones[0], "Trapped on roof")
    assert sos is not None and sos.geohash == phones[0].geohash()[:7]
    for p in phones[1:]:
        assert [r.kind for r in p.report_store.live_reports()] == [reports.ReportKind.SOS]
        assert p.report_notifications[-1].urgency is Urgency.LOUD
    assert phones[0].report_notifications == []  # not told about its own SOS


def test_sos_far_away_is_quiet_and_im_safe_follows_it():
    mesh = Mesh(start_ms=T0)
    caller = mesh.add_phone("caller", *KATHERINE)
    relays = [mesh.add_phone(f"r{i}", *mesh_sim.offset_m(*KATHERINE, 0, (i + 1) * 50)) for i in range(6)]
    far = relays[-1]
    far.location_on = False  # nothing to compare against
    mesh.send_sos(caller, "Car stuck in floodwater")
    assert far.report_notifications[-1].urgency is Urgency.QUIET
    mesh.run(60)
    mesh.send_safe(caller, "Rescued")
    assert [r.kind for r in far.report_store.live_reports()] == [reports.ReportKind.SAFE]
    assert far.report_notifications[-1].kind is reports.ReportKind.SAFE
    assert far.report_notifications[-1].note == "Rescued"


def test_sos_a_phone_that_never_heard_the_sos_is_not_told_about_the_safe():
    mesh, phones = chain(3)
    phones[2].bluetooth_on = False
    mesh._grid = None
    mesh.send_sos(phones[0], "help")
    phones[2].bluetooth_on = True
    phones[2].report_store.wipe()
    safe = phones[0].author.safe(None, "", mesh.now_ms)
    phones[2].receive(COMMUNITY_REPORT_TYPE, reports.encode(safe))
    assert phones[2].report_notifications == []


def test_sos_needs_a_location_and_hazards_do_not_notify():
    mesh, phones = chain(3)
    phones[0].location_on = False
    assert mesh.send_sos(phones[0], "help") is None
    phones[0].location_on = True
    report = mesh.send_hazard(phones[0], HazardType.FLOOD, reports.ReportSeverity.HIGH, "Causeway under water")
    assert report is not None and len(report.geohash) == 8
    assert all(len(p.report_store.live_reports()) == 1 for p in phones)
    assert all(p.report_notifications == [] for p in phones)


def test_sos_is_carried_by_a_driving_phone_to_a_camp_out_of_range():
    mesh, a, b = two_camps(gap_m=5_000)
    car = mesh.add_phone("car", *mesh_sim.offset_m(*KATHERINE, 0, 30),
                         route=[mesh_sim.offset_m(*KATHERINE, 0, 5_030)], speed_mps=15)
    mesh.send_sos(a[0], "Snake bite, need help")
    assert car.report_store.live_reports()
    mesh.run(7 * 60)
    assert all(p.report_store.live_reports() for p in b)
    assert all(p.report_notifications for p in b)


def test_sos_gets_the_extra_hop_in_a_middle_density_mesh():
    assert mesh_sim.is_urgent(COMMUNITY_REPORT_TYPE, reports.encode(
        reports.ReportAuthor().sos("r7hg5x2", "", T0)))
    assert not mesh_sim.is_urgent(COMMUNITY_REPORT_TYPE, reports.encode(
        reports.ReportAuthor().safe("r7hg5x2", "", T0)))


# --- Sync sends only what is missing (step 7.8)


def test_sync_skips_what_the_other_phone_already_holds():
    mesh, phones = chain(2)
    alert = signed_warning(mesh)
    mesh.send(phones[0], OFFICIAL_ALERT_TYPE, wire.encode(alert))
    calls = []
    original = phones[1].receive
    phones[1].receive = lambda *args: calls.append(args) or original(*args)
    assert mesh.sync_pair(phones[0], phones[1]) == 0
    assert calls == []  # nothing offered: phone 1 already holds it


def test_sync_still_delivers_what_is_missing_and_newer_versions():
    mesh, phones = chain(2)
    phones[1].bluetooth_on = False
    mesh._grid = None
    alert = signed_warning(mesh)
    mesh.send(phones[0], OFFICIAL_ALERT_TYPE, wire.encode(alert))
    draft = WarningDraft.updating(alert, mesh.now_ms)
    draft.severity = Severity.EMERGENCY_WARNING
    update = OfficialAlertSigner().sign(draft, alert.alert_id, mesh.now_ms + 1)
    phones[0].receive(OFFICIAL_ALERT_TYPE, wire.encode(update))
    phones[1].receive(OFFICIAL_ALERT_TYPE, wire.encode(alert))  # holds the old version only
    assert mesh.sync_pair(phones[0], phones[1]) == 1
    assert phones[1].alert_store.live_alerts()[0].severity is Severity.EMERGENCY_WARNING


def test_sync_large_run_is_fast():
    import random
    import time

    rng = random.Random(1)
    mesh = Mesh(start_ms=T0)
    for i in range(500):
        mesh.add_phone(f"p{i}", *mesh_sim.offset_m(*KATHERINE, rng.uniform(-500, 500), rng.uniform(-500, 500)))
    alert = signed_warning(mesh, Severity.EMERGENCY_WARNING)
    mesh.send(mesh.phones["p0"], OFFICIAL_ALERT_TYPE, wire.encode(alert))
    start = time.perf_counter()
    mesh.run(3600)
    assert time.perf_counter() - start < 6  # was 12 s before this step
    assert sum(1 for p in mesh.phones.values() if p.first_heard_ms) == 461  # same result as before
