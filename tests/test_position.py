"""Tests for alertmesh.position: which position the phone app uses, and how exact it is.

Swift reference: alert-mesh/AlertMesh/AlertMesh/Services/LocationStateManager.swift
(the app has no pin and no town fallback; those are the laptop's).
"""
import math

import pytest

from alertmesh import geohash, places, position
from alertmesh.position import MAC, PIN, TOWN, Fix, Where

NOW = 1_790_000_000_000
KATHERINE = places.find("Katherine")
SPOT = (-14.4650, 132.2635)  # a street in Katherine


@pytest.mark.parametrize("accuracy, precision", [
    (5, 8), (40, 8), (41, 7), (65, 7), (150, 7), (151, 6), (1200, 6), (1201, 5), (50_000, 5),
])
def test_the_geohash_is_only_as_exact_as_the_fix(accuracy, precision):
    assert position.precision_for(accuracy) == precision
    assert len(Fix.from_point(*SPOT, accuracy, NOW).cell) == precision


def test_a_fix_holds_a_geohash_of_the_spot():
    fix = Fix.from_point(*SPOT, 65, NOW)
    assert fix == Fix(geohash.encode(*SPOT, 7), 65, NOW)


@pytest.mark.parametrize("accuracy", [-1, math.nan])
def test_a_reading_macos_marks_invalid_is_no_fix(accuracy):
    assert Fix.from_point(*SPOT, accuracy, NOW) is None


def test_a_fix_is_fresh_for_an_hour():
    fix = Fix("qvqj0cm", 65, NOW)
    assert fix.is_fresh(NOW + position.FIX_FRESH_MS)
    assert not fix.is_fresh(NOW + position.FIX_FRESH_MS + 1)
    assert fix.is_fresh(NOW - 5000)  # a clock that stepped back still counts


def test_the_pin_comes_first():
    fix = Fix.from_point(*SPOT, 65, NOW)
    assert position.choose("qvqj0cz", fix, KATHERINE, NOW) == Where("qvqj0cz", PIN)


def test_a_pin_is_cut_to_about_150_m_and_lower_case():
    assert position.choose("QVQJ0CZX", None, None, NOW).geohash == "qvqj0cz"


def test_a_broken_pin_is_skipped():
    fix = Fix.from_point(*SPOT, 65, NOW)
    assert position.choose("not a pin!", fix, None, NOW).source == MAC


def test_then_this_macs_fix():
    fix = Fix.from_point(*SPOT, 65, NOW)
    assert position.choose(None, fix, KATHERINE, NOW + 1000) == Where(fix.cell, MAC, 65)


def test_an_old_fix_falls_back_to_the_town():
    fix = Fix.from_point(*SPOT, 65, NOW)
    where = position.choose(None, fix, KATHERINE, NOW + position.FIX_FRESH_MS + 1)
    assert where == Where(places.geohash_of(KATHERINE), TOWN, "Katherine")


def test_nothing_known_is_none():
    assert position.choose(None, None, None, NOW) is None
    assert position.choose(None, Fix("qvqj0cm", 65, 0), None, NOW) is None


@pytest.mark.parametrize("metres, text", [
    (3, "about 10 m"), (64, "about 60 m"), (65, "about 60 m"), (66, "about 70 m"), (995, "about 1000 m"),
    (1000, "about 1 km"), (1450, "about 1.4 km"), (12_000, "about 12 km"),
])
def test_distance_words(metres, text):
    assert position.distance_words(metres) == text


def test_the_words_say_where_the_position_came_from():
    assert position.words(Where("qvqj0cm", MAC, 65)) == "at this Mac's location (about 60 m)"
    assert position.words(Where("qvqj0cz", PIN)) == "at the pin you dropped"
    assert position.words(Where("qvqj0cm", TOWN, "Katherine")) == \
        "at the centre of Katherine, the town in Settings"
