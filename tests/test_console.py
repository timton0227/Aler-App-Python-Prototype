"""The warning console: sending both ways, and picking the area.

Ported from:
- ../alert-mesh/AlertMeshTests/AlertMesh/Services/OfficialAlertIssuerTests.swift
  (the send tests; the key-store tests are left out because the prototype always
  signs with the development key, and the draft and signing tests are in test_signer.py)
- ../alert-mesh/AlertMeshTests/AlertMesh/Views/IssueWarningViewTests.swift (map clicks)
"""
import pytest

from alertmesh import geohash, wire
from alertmesh.alert_store import AlertStore, IngestResult
from alertmesh.console import (AREA_SIZE_NAMES, Action, AreaSize, Console, IssueError, NetworkShare, Outcome,
                               corners, outcome_text, toggle_area)
from alertmesh.signer import Problem, WarningDraft
from alertmesh.wire import HazardType, Severity

NOW_MS = 1_700_000_000_000


class Recorder:
    def __init__(self):
        self.broadcast: list[bytes] = []
        self.published: list[tuple[bytes, tuple, int]] = []
        self.online = True
        self.peers = 2
        self.now_ms = NOW_MS


def make_console(recorder: Recorder) -> Console:
    def publish(payload, area, expires_at):
        recorder.published.append((payload, area, expires_at))
        return recorder.online

    return Console(
        broadcast=recorder.broadcast.append,
        publish=publish,
        connected_peer_count=lambda: recorder.peers,
        now_ms=lambda: recorder.now_ms,
    )


def draft() -> WarningDraft:
    return WarningDraft(HazardType.BUSHFIRE, Severity.EMERGENCY_WARNING, "  Bushfire at Mount Barker - leave now ",
                        "Travel north on Highway 1. Do not wait.", 6, ["R7HG", "r7hu"])


# --- Issue ---


def test_an_issued_warning_verifies_and_goes_both_ways():
    recorder = Recorder()
    console = make_console(recorder)

    alert = console.issue(draft())

    assert wire.verify_pinned(alert)
    assert alert.headline == "Bushfire at Mount Barker - leave now"
    assert alert.area_cells == ("r7hg", "r7hu")
    assert alert.issued_at == recorder.now_ms
    assert alert.expires_at == recorder.now_ms + 6 * 3_600_000
    assert len(recorder.broadcast) == 1
    assert wire.decode(recorder.broadcast[0]) == alert
    payload, area, expires_at = recorder.published[0]
    assert wire.decode(payload) == alert
    assert area == alert.area_cells
    assert expires_at == alert.expires_at
    assert console.last_outcome == Outcome(Action.ISSUED, alert.headline, 2, True)


def test_each_issue_is_a_new_event():
    console = make_console(Recorder())
    assert console.issue(draft()).alert_id != console.issue(draft()).alert_id


def test_offline_it_is_sent_over_bluetooth_only():
    """With no internet it still goes out over Bluetooth, and says so."""
    recorder = Recorder()
    recorder.online, recorder.peers = False, 0
    console = make_console(recorder)

    console.issue(draft())

    assert len(recorder.broadcast) == 1
    assert console.last_outcome.posted_online is False
    assert console.last_outcome.nearby_devices == 0


def test_an_invalid_draft_is_never_sent():
    recorder = Recorder()
    console = make_console(recorder)
    too_long = draft()
    too_long.headline = "é" * 51  # 102 bytes
    no_area = draft()
    no_area.area_cells = []

    assert too_long.problems == [Problem.HEADLINE_TOO_LONG]
    assert no_area.problems == [Problem.NO_AREA]
    for bad in (too_long, no_area):
        with pytest.raises(IssueError):
            console.issue(bad)
    assert recorder.broadcast == [] and recorder.published == []
    assert console.last_outcome is None


# --- Update, resend, cancel ---


def test_an_update_keeps_the_event_and_moves_the_version_on():
    """Same millisecond: the version still moves on, so phones replace the warning."""
    recorder = Recorder()
    console = make_console(recorder)
    first = console.issue(draft())
    changed = WarningDraft.updating(first, recorder.now_ms)
    changed.headline = "Bushfire at Mount Barker - too late to leave"

    updated = console.update(first, changed)

    assert updated.alert_id == first.alert_id
    assert updated.issued_at > first.issued_at
    assert updated.hazard is HazardType.BUSHFIRE
    assert wire.verify_pinned(updated)
    assert console.last_outcome.action is Action.UPDATED


def test_resend_sends_the_same_signed_bytes():
    recorder = Recorder()
    console = make_console(recorder)
    alert = console.issue(draft())

    console.resend(alert)

    assert len(recorder.broadcast) == 2
    assert recorder.broadcast[0] == recorder.broadcast[1]
    assert console.last_outcome.action is Action.RESENT


def test_a_cancellation_verifies_and_carries_the_warnings_area():
    recorder = Recorder()
    console = make_console(recorder)
    alert = console.issue(draft())

    console.cancel(alert)

    payload, area, expires_at = recorder.published[-1]
    cancellation = wire.decode(payload)
    assert isinstance(cancellation, wire.AlertCancellation)
    assert cancellation.alert_id == alert.alert_id
    assert cancellation.issued_at > alert.issued_at
    assert wire.verify_pinned(cancellation)
    assert area == alert.area_cells
    assert expires_at == alert.expires_at
    assert wire.decode(recorder.broadcast[-1]) == cancellation
    assert console.last_outcome.action is Action.CANCELLED


def test_the_store_accepts_what_the_console_signs():
    """The store is what phones run: a cancellation from the console removes the warning."""
    recorder = Recorder()
    console = make_console(recorder)
    store = AlertStore(clock=lambda: recorder.now_ms)

    alert = console.issue(draft())
    assert store.ingest_payload(recorder.broadcast[-1]) is IngestResult.ACCEPTED
    console.cancel(alert)
    assert store.ingest_payload(recorder.broadcast[-1]) is IngestResult.ACCEPTED

    assert store.live_alerts() == []


def test_outcome_text():
    assert outcome_text(Outcome(Action.ISSUED, "Leave now", 3, True)) == (
        "Sent: Leave now — 3 devices connected over Bluetooth, handed to internet relays")
    assert outcome_text(Outcome(Action.CANCELLED, "Leave now", 0, False)) == (
        "Cancellation sent: Leave now — 0 devices connected over Bluetooth, not online: no relay")
    assert "1 device connected" in outcome_text(Outcome(Action.RESENT, "Leave now", 1, True))



def test_outcome_text_says_whether_phone_apps_got_it():
    assert outcome_text(Outcome(Action.ISSUED, "Leave now", 3, True, True)).endswith(
        ", sent to phone apps on the local network")
    assert outcome_text(Outcome(Action.ISSUED, "Leave now", 3, True, False)).endswith(
        ", not sent to the local network")


# --- The real-time copy for phone apps (NetworkShare; new, no Swift test) ---

REAL_MS = 1_790_000_000_000


@pytest.fixture
def recorder():
    return Recorder()


def draft_saying(headline: str) -> WarningDraft:
    d = draft()
    d.headline = headline
    return d


def shared_console(recorder: Recorder):
    """A console whose warnings also go to a phone app's store, on the real clock."""
    sent = []
    clock = {"now": REAL_MS}
    share = NetworkShare(lambda payload: sent.append(payload) or True, now_ms=lambda: clock["now"])
    console = make_console(recorder)
    console._share = share
    phone_store = AlertStore(clock=lambda: clock["now"])
    return console, share, sent, clock, phone_store


def test_share_signs_a_real_time_copy(recorder):
    console, _, sent, _, phone_store = shared_console(recorder)
    alert = console.issue(draft())
    real = wire.decode(sent[0])
    assert real.alert_id == alert.alert_id and real.headline == alert.headline
    assert (real.issued_at, real.expires_at - real.issued_at) == (REAL_MS, alert.expires_at - alert.issued_at)
    assert console.last_outcome.shared is True
    # The town's copy is from 2023 and a phone app refuses it; the real copy is taken.
    assert phone_store.ingest_payload(recorder.broadcast[0]) is IngestResult.REJECTED
    assert phone_store.ingest_payload(sent[0]) is IngestResult.ACCEPTED


def test_share_update_resend_and_cancel(recorder):
    console, _, sent, clock, phone_store = shared_console(recorder)
    alert = console.issue(draft())
    phone_store.ingest_payload(sent[-1])
    updated = console.update(alert, draft_saying("Now leave by the south road"))
    assert phone_store.ingest_payload(sent[-1]) is IngestResult.ACCEPTED  # a later version, even in the same ms
    assert [a.headline for a in phone_store.live_alerts()] == ["Now leave by the south road"]
    console.resend(updated)
    assert sent[-1] == sent[-2]  # the same bytes again
    clock["now"] += 1000
    console.cancel(updated)
    assert phone_store.ingest_payload(sent[-1]) is IngestResult.ACCEPTED
    assert phone_store.live_alerts() == []


def test_withdraw_all_cancels_what_is_still_out(recorder):
    console, share, sent, _, phone_store = shared_console(recorder)
    for _ in range(2):
        console.issue(draft())
        phone_store.ingest_payload(sent[-1])
    share.withdraw_all()
    for payload in sent[2:]:
        phone_store.ingest_payload(payload)
    assert len(sent) == 4 and phone_store.live_alerts() == []


def test_cancelling_something_never_shared_sends_nothing():
    sent = []
    share = NetworkShare(sent.append, now_ms=lambda: REAL_MS)
    assert share(wire.AlertCancellation(bytes(16), REAL_MS, bytes(64))) is False
    assert sent == []


# --- Picking the area (map clicks in the app) ---

# Mount Barker, South Australia.
LAT, LON = -35.07, 138.86


def cell(size: AreaSize, lat: float = LAT, lon: float = LON) -> str:
    return geohash.encode(lat, lon, int(size))


def test_a_click_adds_the_cell_of_the_chosen_size():
    cells = toggle_area(LAT, LON, AreaSize.TOWN, [])
    assert cells == [cell(AreaSize.TOWN)]
    assert len(cells[0]) == 5


def test_a_click_inside_a_picked_cell_removes_it():
    assert toggle_area(LAT, LON, AreaSize.STREET, [cell(AreaSize.DISTRICT)]) == []


def test_a_larger_cell_replaces_smaller_ones_inside_it():
    """A larger cell swallows the smaller ones inside it, so the area never lists the
    same ground twice."""
    street = cell(AreaSize.STREET)
    district = street[:4]
    far = cell(AreaSize.TOWN, -12.46, 130.84)  # Darwin
    # A spot in the same district, outside the picked street cell.
    next_door = next(n for n in geohash.neighbors(street) if n.startswith(district))
    click = geohash.decode_center(next_door)

    assert toggle_area(*click, AreaSize.DISTRICT, [street, far]) == [far, district]


def test_the_fifth_cell_is_refused():
    picked = ["r3", "r4", "r5", "r6"]  # none covers Mount Barker (r1...)
    assert toggle_area(LAT, LON, AreaSize.DISTRICT, picked) == picked


def test_every_size_is_a_valid_area_cell():
    assert set(AREA_SIZE_NAMES) == set(AreaSize)
    for size in AreaSize:
        assert wire.AREA_GEOHASH_MIN_LENGTH <= int(size) <= wire.AREA_GEOHASH_MAX_LENGTH
        assert wire.is_valid_area_cell(cell(size))


def test_corners_are_the_cell_bounds():
    town = cell(AreaSize.TOWN)
    points = corners(town)
    lat_min, _, _, lon_max = geohash.decode_bounds(town)
    assert len(points) == 4
    assert min(lat for lat, _ in points) == lat_min
    assert max(lon for _, lon in points) == lon_max
