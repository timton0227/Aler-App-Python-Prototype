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


def test_area_map_draws_each_cell_and_the_centre():
    fig = viz.area_map(["qvqj9", "qvqjd"], "#BF1A1A", (-14.46, 132.26))
    outlines = [t for t in fig.data if t.fill == "toself"]
    assert len(outlines) == 2
    assert [t.showlegend for t in outlines] == [True, False]
    assert len(outlines[0].lat) == 5  # four corners, closed
    assert fig.data[-1].name == "Evacuation centre"


def test_fit_zoom_zooms_out_for_a_bigger_area():
    _, street = viz.fit_zoom([(-14.46, 132.26), (-14.45, 132.27)])
    _, region = viz.fit_zoom([(-14.0, 132.0), (-15.5, 133.5)])
    assert street > region


def test_every_frame_of_the_spread_map_has_the_same_traces():
    """Plotly animates by trace position. If a status is missing from one minute (nobody
    warned yet, or everybody warned), a frame with fewer traces would recolour or hide
    the phones. Every frame must list every status, in the same order."""
    import pandas as pd

    rows = []
    for minute, statuses in enumerate((["not warned yet"] * 3,
                                       ["warned by Bluetooth", "not warned yet", "not warned yet"],
                                       ["warned by internet", "warned by Bluetooth", "warned by Bluetooth"])):
        rows += [{"phone": f"p{i}", "lat": -14.46 + i / 1000, "lon": 132.26, "status": s, "moving": False,
                  "minute": minute} for i, s in enumerate(statuses)]
    fig = viz.spread_map(pd.DataFrame(rows))

    names = list(viz.STATUS_COLOURS)
    assert [t.name for t in fig.data[:3]] == names
    for frame in fig.frames:
        assert [t.name for t in frame.data] == names
    # Minute 2: nobody is left grey.
    assert len(fig.frames[2].data[2].lat) == 0
    assert len(fig.frames[2].data[1].lat) == 2
