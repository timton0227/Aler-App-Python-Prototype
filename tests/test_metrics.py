"""Tests for alertmesh.metrics (new code: no Swift tests to port)."""
from alertmesh import geohash, metrics, places
from alertmesh.metrics import Scenario

SMALL = Scenario(n_phones=120, area_m=500, share_online=0.1, duration_s=600, sample_s=60, seed=3)


def test_coverage_warning_cells_cover_the_whole_square():
    lat, lon = places.find("Katherine").latitude, places.find("Katherine").longitude
    for area_m in (500, 1_000, 4_000, 10_000):
        cells = metrics.area_cells(lat, lon, area_m)
        assert 1 <= len(cells) <= 4
        mesh, alert = metrics.build(Scenario(n_phones=200, area_m=area_m, seed=7))
        assert all(metrics._inside(p, alert) for p in mesh.phones.values()), area_m


def test_coverage_same_seed_same_layout_and_signed_warning():
    a_mesh, a_alert = metrics.build(SMALL)
    b_mesh, b_alert = metrics.build(SMALL)
    assert [(p.lat, p.lon, p.has_internet) for p in a_mesh.phones.values()] == \
           [(p.lat, p.lon, p.has_internet) for p in b_mesh.phones.values()]
    assert a_alert == b_alert
    assert metrics.wire.verify_pinned(a_alert)


def test_coverage_curve_starts_with_the_online_phones_and_never_falls():
    result = metrics.run(SMALL)
    mesh, _ = metrics.build(SMALL)
    online = sum(p.has_internet for p in mesh.phones.values())
    assert result.times_s == [60.0 * i for i in range(11)]
    assert result.warned_share[0] >= online / SMALL.n_phones  # online phones + their flood
    assert all(b >= a for a, b in zip(result.warned_share, result.warned_share[1:]))
    assert result.in_area == SMALL.n_phones
    assert 0.0 <= result.loud_share <= 1.0


def test_coverage_everyone_warned_is_told_loudly_inside_the_area():
    result = metrics.run(SMALL)
    assert abs(result.loud_share - result.final_share) < 1e-9  # inside + Emergency Warning = loud


def test_coverage_time_to_share():
    result = metrics.run(SMALL)
    assert result.time_to_share(0.0) == 0.0
    assert result.time_to_share(1.01) is None
    t = result.time_to_share(result.final_share)
    assert t is not None and t <= SMALL.duration_s
