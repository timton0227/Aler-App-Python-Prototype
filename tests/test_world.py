"""The page's simulated town: the console sends into the mesh from the evacuation centre."""
from alertmesh import labels, metrics, places, world
from alertmesh.console import Action
from alertmesh.proximity import Decision, Match, Reason, ReasonKind, Urgency
from alertmesh.signer import WarningDraft
from alertmesh.wire import HazardType, Severity

SMALL = metrics.Scenario(n_phones=60, area_m=600, share_online=0.1, seed=2)


def warning(w: world.World, severity=Severity.EMERGENCY_WARNING) -> WarningDraft:
    return WarningDraft(HazardType.FLOOD, severity, "Flooding - leave now", "Go to the evacuation centre.",
                        6, w.town_cells())


def test_the_town_has_the_scenario_phones_and_the_centre():
    w = world.build(SMALL)
    assert len(w.mesh.phones) == SMALL.n_phones + 1
    assert w.hub is w.mesh.phones[world.HUB_ID]
    assert w.hub.has_internet and w.online
    assert w.minutes == 0


def test_the_same_scenario_gives_the_same_town():
    a, b = world.build(SMALL), world.build(SMALL)
    assert [(p.lat, p.lon, p.has_internet) for p in a.mesh.phones.values()] == \
           [(p.lat, p.lon, p.has_internet) for p in b.mesh.phones.values()]


def test_a_warning_from_the_console_is_live_at_the_centre_and_spreads():
    w = world.build(SMALL)
    alert = w.console.issue(warning(w))

    assert w.live_warnings() == [alert]
    assert w.sent[alert.alert_id] == alert
    assert alert.issued_at == w.mesh.now_ms
    assert w.console.last_outcome.action is Action.ISSUED
    assert w.console.last_outcome.posted_online
    w.advance(10)
    assert w.minutes == 10
    warned = sum(alert.alert_id in p.first_heard_ms for p in w.mesh.phones.values())
    assert warned > SMALL.n_phones // 2


def test_offline_the_console_still_warns_over_bluetooth():
    w = world.build(SMALL)
    w.set_online(False)
    alert = w.console.issue(warning(w))

    assert not w.console.last_outcome.posted_online
    assert w.mesh.internet_feed == []
    assert alert.alert_id in w.hub.first_heard_ms
    # Phones with internet heard nothing from the internet; any copy came over Bluetooth.
    assert all(msg != "internet" for _, _, msg, _ in w.mesh.log)


def test_a_cancellation_takes_the_warning_off_the_list():
    w = world.build(SMALL)
    alert = w.console.issue(warning(w))
    w.console.cancel(alert)

    assert w.live_warnings() == []
    assert alert.alert_id in w.sent  # still known, so the map can show where it went


def test_the_town_cells_cover_every_phone():
    w = world.build(SMALL)
    cells = w.town_cells()
    for phone in w.mesh.phones.values():
        assert any(phone.geohash().startswith(c) for c in cells)


# --- Words (AlertsViewLogicTests.proximityWordingCoversEveryReason) ---


def test_proximity_wording_covers_every_reason():
    reasons = [
        Reason(ReasonKind.INSIDE_AREA, "r7hg"), Reason(ReasonKind.ADJACENT_TO_AREA, "r7hg"),
        Reason(ReasonKind.WATCHED_PLACE_INSIDE_AREA, "r7hg", "r7hg5"),
        Reason(ReasonKind.WATCHED_PLACE_NEAR_AREA, "r7hg", "r7hg5"),
        Reason(ReasonKind.OUTSIDE_AREA), Reason(ReasonKind.LOCATION_UNKNOWN),
    ]
    words = [labels.proximity(Decision(Urgency.QUIET, Match.INSIDE, r)) for r in reasons]
    assert all(words)
    # Inside and watched-inside read the same; near and watched-near too.
    assert words[0] == words[2]
    assert words[1] == words[3]
    assert len(set(words)) == 4


def test_until_shows_the_date_only_on_a_later_day():
    now = 1_700_000_000_000
    same_day = labels.until(now + 60_000, now)
    next_week = labels.until(now + 6 * 24 * 3_600_000, now)
    assert same_day.startswith("Until")
    assert len(next_week) > len(same_day)


def test_every_level_and_hazard_has_words_and_colours():
    for severity in Severity:
        assert labels.SEVERITY_NAMES[severity] and labels.SEVERITY_FILL[severity]
    for hazard in HazardType:
        assert labels.hazard_name(hazard) != labels.UNKNOWN_HAZARD
    assert labels.hazard_name(None) == labels.UNKNOWN_HAZARD


# --- The map tab ---


def test_spread_counts_add_up():
    w = world.build(SMALL)
    alert = w.console.issue(warning(w))
    w.advance(5)
    counts = w.spread(alert.alert_id)
    statuses = counts["warned by internet"] + counts["warned by Bluetooth"] + counts["not warned yet"]
    assert statuses == counts["phones"] == SMALL.n_phones
    assert counts["in area"] == SMALL.n_phones  # the area covers the whole town
    assert counts["in area warned"] == SMALL.n_phones - counts["not warned yet"]
    assert 0 < counts["told loudly"] <= counts["in area warned"]


def test_play_records_each_minute_with_the_towns_own_minutes():
    w = world.build(SMALL)
    alert = w.console.issue(warning(w))
    w.advance(3)
    frames = w.play(alert.alert_id, 4)
    assert w.minutes == 7
    assert sorted(frames["minute"].unique()) == [3, 4, 5, 6, 7]
    assert world.HUB_ID not in set(frames["phone"])
    assert (frames.groupby("minute").size() == SMALL.n_phones).all()
    now = w.phones_now(alert.alert_id)
    assert set(now["minute"]) == {7}
    assert list(now["status"]) == list(frames[frames["minute"] == 7]["status"])


# --- The phone view tab ---


def test_a_phone_lists_the_warning_with_its_decision_and_notification():
    w = world.build(SMALL)
    alert = w.console.issue(warning(w))
    w.advance(10)
    phone = next(p for p in w.phones() if alert.alert_id in p.first_heard_ms)
    [item] = w.warnings_on(phone)
    assert item.alert == alert
    assert item.now.urgency is Urgency.LOUD
    assert item.notified.urgency is Urgency.LOUD
    content = item.notification()
    assert content.title == "🔴 Emergency Warning · Flood"
    assert content.body == "Flooding - leave now\nGo to the evacuation centre."


def test_bluetooth_off_takes_a_phone_out_of_the_mesh():
    w = world.build(SMALL)
    phone = next(p for p in w.phones() if not p.has_internet and not p.route and w.mesh.neighbours(p))
    w.set_phone(phone, bluetooth=False)
    assert w.mesh.neighbours(phone) == []
    alert = w.console.issue(warning(w))
    w.advance(10)
    assert alert.alert_id not in phone.first_heard_ms


def test_a_watched_place_makes_a_far_warning_loud_with_location_off():
    w = world.build(SMALL)
    phone = w.phones()[0]
    w.set_phone(phone, location=False)
    phone.remembered_cell = None  # nothing remembered: only the watched place can match
    darwin = places.find("Darwin")
    far = WarningDraft(HazardType.CYCLONE, Severity.EMERGENCY_WARNING, "Cyclone near Darwin", "Shelter now.", 6,
                       [places.geohash_of(darwin, 5)])
    alert = w.console.issue(far)
    item = next(i for i in w.warnings_on(w.hub) if i.alert == alert)
    assert item.now.reason.kind is ReasonKind.OUTSIDE_AREA  # the centre is in Katherine

    w.set_phone(phone, watched=darwin)
    assert phone.bookmarks == (places.geohash_of(darwin, world.WATCHED_PRECISION),)
    assert phone.decide(alert).urgency is Urgency.LOUD
    assert phone.decide(alert).reason.kind is ReasonKind.WATCHED_PLACE_INSIDE_AREA
    w.set_phone(phone, watched=None)
    assert phone.bookmarks == ()


# --- The hub board tab ---


def test_the_board_shows_the_centres_warnings_and_calls_for_help():
    w = world.build(SMALL)
    assert w.board().hero is None
    alert = w.console.issue(warning(w))
    # Calls for help travel over Bluetooth only, so the caller stands next to the centre.
    caller = w.mesh.neighbours(w.hub)[0]
    w.mesh.send_sos(caller, "Car stuck")
    w.advance(10)
    b = w.board()
    assert b.hero == alert
    assert b.peers == len(w.mesh.neighbours(w.hub))
    assert [r.note for r in b.sos] == ["Car stuck"]
