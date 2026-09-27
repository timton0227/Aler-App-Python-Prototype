"""Tests for alertmesh.viz (new code: no Swift tests to port)."""
from alertmesh import metrics, viz, wire
from alertmesh.metrics import Scenario

SMALL = Scenario(n_phones=60, area_m=400, share_online=0.2, share_moving=0.3, duration_s=300, sample_s=60, seed=5)


def published():
    mesh, alert = metrics.build(SMALL)
    mesh.publish(wire.encode(alert))
    return mesh, alert


def test_phone_status_matches_the_phones():
    mesh, alert = published()
    rows = viz.phone_status(mesh, alert.alert_id)
    assert len(rows) == 60
    for row in rows:
        phone = mesh.phones[row["phone"]]
        assert (row["status"] == "not warned yet") == (alert.alert_id not in phone.first_heard_ms)
        assert row["status"] != "warned by internet" or phone.has_internet


def test_spread_frames_record_every_phone_every_minute_and_never_go_backwards():
    mesh, alert = published()
    frames = viz.spread_frames(mesh, alert.alert_id, minutes=5)
    assert sorted(frames["minute"].unique()) == [0, 1, 2, 3, 4, 5]
    assert (frames.groupby("minute").size() == 60).all()
    shares = viz.share_by_minute(frames)["share warned"].tolist()
    assert all(b >= a for a, b in zip(shares, shares[1:]))


def test_figures_build():
    mesh, alert = published()
    frames = viz.spread_frames(mesh, alert.alert_id, minutes=2)
    assert len(viz.spread_map(frames).frames) == 3
    comparison = metrics.compare(SMALL)
    assert len(viz.curves_chart(comparison).data) == 2
    table = [{"n": 10, "with mesh": 0.5, "internet only": 0.2}]
    assert len(viz.sweep_chart(table, "n", "phones").data) == 2
