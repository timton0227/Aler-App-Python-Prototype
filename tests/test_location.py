"""Tests for alertmesh.location: the app's side of the location process, and the status
words. The process itself needs macOS Location Services and a packaged app, so these
use a stand-in process; the real one is checked by hand (PROGRESS.md 17.2 and 17.7).

Swift reference: ../alert-mesh/AlertMesh/AlertMesh/Services/LocationStateManager.swift
"""
import sys
import time

import pytest

from alertmesh import geohash, location
from alertmesh.location import AUTHORIZED_WHEN_IN_USE, DENIED, NOT_DETERMINED, RESTRICTED

# Stands in for the location process: sends one fix and a status, then answers every
# "take a fix now" with a status that counts them.
FAKE = r"""
import json, sys
def send(kind, data):
    sys.stdout.buffer.write(kind + len(data).to_bytes(2, "big") + data)
    sys.stdout.buffer.flush()
send(b"P", json.dumps({"lat": -14.465, "lon": 132.2635, "accuracy": 65, "at": 1790000000000}).encode())
send(b"P", b"not json")
send(b"P", json.dumps({"lat": 0, "lon": 0, "accuracy": -1, "at": 0}).encode())
send(b"S", b"on")
asked = 0
while True:
    head = sys.stdin.buffer.read(3)
    if len(head) < 3:
        break
    sys.stdin.buffer.read(int.from_bytes(head[1:], "big"))
    asked += 1
    send(b"S", f"asked {asked}".encode())
"""


def wait_for(condition, seconds=10):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.02)
    return condition()


def test_the_process_passes_fixes_as_geohashes_and_takes_refresh():
    got = []
    process = location.LocationProcess(got.append, [sys.executable, "-c", FAKE])
    try:
        assert wait_for(lambda: process.status == "on")
        assert [fix.cell for fix in got] == [geohash.encode(-14.465, 132.2635, 7)]  # broken readings skipped
        assert process.fix == got[0] and process.fix.accuracy_m == 65
        process.refresh()
        process.refresh()
        assert wait_for(lambda: process.status == "asked 2")
    finally:
        process.stop()


@pytest.mark.skipif(sys.platform == "win32", reason="SIGABRT is how macOS stops a program")
def test_a_process_stopped_by_macos_is_explained():
    process = location.LocationProcess(None, [sys.executable, "-c", "import os; os.abort()"])
    assert wait_for(lambda: process.status.startswith("off"))
    assert "Privacy & Security" in process.status
    process.refresh()  # must not raise
    assert process.fix is None


def test_a_process_that_ends_says_so():
    process = location.LocationProcess(None, [sys.executable, "-c", "raise SystemExit(3)"])
    assert wait_for(lambda: process.status.startswith("off"))
    assert "exit code 3" in process.status


def test_location_command():
    assert location.location_command()[-2:] == ["-m", "alertmesh.location"]


def test_status_words():
    words = location.status_words
    assert words(False, AUTHORIZED_WHEN_IN_USE, True, 0, False).startswith("off: Location Services is turned off")
    assert words(True, DENIED, False, 0, False).startswith("off: not allowed")
    assert words(True, RESTRICTED, False, 0, False).startswith("off: not allowed")
    assert words(True, NOT_DETERMINED, False, 5, False) == "asking macOS for permission"
    assert "only the packaged app can ask" in words(True, NOT_DETERMINED, False, location.PERMISSION_WAIT_S, False)
    assert words(True, AUTHORIZED_WHEN_IN_USE, False, 0, False) == "on, waiting for a first fix"
    assert words(True, AUTHORIZED_WHEN_IN_USE, False, 0, True).startswith("on, but no fix right now")
    assert words(True, AUTHORIZED_WHEN_IN_USE, True, 0, True) == "on"


def test_available_only_on_a_mac_with_the_library(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert not location.available()
