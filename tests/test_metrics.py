"""Tests for alertmesh.metrics (new code: no Swift tests to port)."""
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from alertmesh import metrics, places
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


# --- With vs without the mesh (step 8.2)


def test_compare_same_people_same_places():
    on, _ = metrics.build(replace(SMALL, mesh_on=True))
    off, _ = metrics.build(replace(SMALL, mesh_on=False))
    assert [(p.lat, p.lon, p.has_internet) for p in on.phones.values()] == \
           [(p.lat, p.lon, p.has_internet) for p in off.phones.values()]
    assert all(p.bluetooth_on for p in on.phones.values())
    assert not any(p.bluetooth_on for p in off.phones.values())


def test_compare_internet_only_reaches_exactly_the_online_phones():
    comparison = metrics.compare(SMALL)
    mesh, _ = metrics.build(SMALL)
    online = sum(p.has_internet for p in mesh.phones.values()) / SMALL.n_phones
    assert comparison.without_mesh.warned_share == [online] * len(comparison.without_mesh.times_s)


def test_compare_the_mesh_never_does_worse_and_here_does_better():
    comparison = metrics.compare(SMALL)
    for w, wo in zip(comparison.with_mesh.warned_share, comparison.without_mesh.warned_share):
        assert w >= wo
    assert comparison.with_mesh.final_share > comparison.without_mesh.final_share


def test_compare_summary_has_both_rows():
    s = metrics.compare(SMALL).summary()
    assert set(s) == {"with mesh", "internet only"}
    assert set(s["with mesh"]) == {"warned after 10 min", "warned at end", "minutes to 80%", "told loudly"}
    assert s["internet only"]["warned after 10 min"] == s["internet only"]["warned at end"]


# --- Sweeps (step 8.3)

QUICK = Scenario(n_phones=150, area_m=800, share_online=0.1, duration_s=1_800, sample_s=300, seed=11)


def test_sweep_has_one_row_per_run_and_repeats_exactly():
    rows = metrics.sweep(QUICK, "n_phones", [50, 150], repeats=2)
    assert [(r["n_phones"], r["seed"]) for r in rows] == [(50, 11), (50, 12), (150, 11), (150, 12)]
    assert rows == metrics.sweep(QUICK, "n_phones", [50, 150], repeats=2)  # fixed seeds


def test_sweep_more_people_close_together_reach_more_of_them():
    table = metrics.means(metrics.sweep(QUICK, "n_phones", [40, 300], repeats=2), "n_phones")
    assert [row["n_phones"] for row in table] == [40, 300]
    assert table[1]["with mesh"] > table[0]["with mesh"]


def test_sweep_longer_bluetooth_range_reaches_more():
    table = metrics.means(metrics.sweep(QUICK, "bluetooth_range_m", [20, 100], repeats=2), "bluetooth_range_m")
    assert table[1]["with mesh"] > table[0]["with mesh"]


def test_sweep_people_moving_about_carry_the_warning_further():
    base = replace(QUICK, n_phones=80, speed_mps=5.0)
    table = metrics.means(metrics.sweep(base, "share_moving", [0.0, 0.5], repeats=2), "share_moving")
    assert table[1]["with mesh"] > table[0]["with mesh"]


def test_sweep_everyone_online_is_everyone_warned_either_way():
    rows = metrics.sweep(QUICK, "share_online", [1.0], repeats=1)
    assert rows[0]["with mesh"] == rows[0]["internet only"] == 1.0


def test_sweep_rejects_an_unknown_parameter():
    with pytest.raises(ValueError):
        metrics.sweep(QUICK, "colour", [1])


def test_results_are_the_same_in_every_python_run():
    """Python shuffles set order per run (PYTHONHASHSEED). Results must not depend on it."""
    code = ("from alertmesh import metrics; r = metrics.run(metrics.Scenario(n_phones=200, area_m=1000, "
            "share_online=0.1, share_moving=0.3, speed_mps=1.4, seed=4, duration_s=600)); print(r.warned_share)")
    outputs = {
        subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                       env={"PYTHONHASHSEED": seed, "PATH": ""}, cwd=str(Path(__file__).parents[1])).stdout
        for seed in ("1", "2", "3")
    }
    assert len(outputs) == 1, outputs
