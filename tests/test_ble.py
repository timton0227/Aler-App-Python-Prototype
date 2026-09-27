"""Tests for alertmesh.ble, without a radio.

The radio itself can only be checked with two laptops (README, "Two-laptop check").
These tests cover everything around it: pieces, putting them back together, writing
to every laptop in range, and the separate Bluetooth process.
"""
import asyncio
import os
import sys
import time

import pytest

from alertmesh import ble, chat, node


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


# --- Pieces


@pytest.mark.parametrize("write_size", [20, 23, 180, 512])
def test_largest_frame_survives_being_cut_into_pieces(write_size):
    frame = os.urandom(node.MAX_FRAME_BYTES)
    pieces = ble.split(frame, write_size)
    assert all(len(p) <= write_size for p in pieces)
    r = ble.Reassembler()
    results = [r.add(p) for p in pieces]
    assert results[:-1] == [None] * (len(pieces) - 1)
    assert results[-1] == frame


def test_pieces_in_any_order_and_mixed_with_another_frame():
    one, two = os.urandom(400), os.urandom(300)
    a, b = ble.split(one, 100), ble.split(two, 100)
    r = ble.Reassembler()
    out = [r.add(p) for p in [a[2], b[0], a[0], b[3], a[4], b[1], a[1], b[2], a[3]]]
    assert [x for x in out if x is not None] == [two, one]


def test_small_frame_is_one_piece():
    assert len(ble.split(b"hi", 180)) == 1


def test_a_write_size_below_the_minimum_is_raised_to_it():
    assert all(len(p) <= ble.MIN_WRITE for p in ble.split(os.urandom(100), 5))


def test_incomplete_frames_are_dropped_after_a_while():
    clock = Clock()
    r = ble.Reassembler(clock)
    pieces = ble.split(os.urandom(300), 100)
    r.add(pieces[0])
    clock.now += ble.PARTIAL_TIMEOUT_S + 1
    r.add(b"junk!!")  # anything arriving sweeps out old partials
    assert r._partials == {}
    assert r.add(pieces[1]) is None


def test_junk_pieces_are_ignored():
    r = ble.Reassembler()
    assert r.add(b"") is None
    assert r.add(b"abcd\x05\x02x") is None  # piece 5 of 2
    assert r.add(b"abcd\x00\x00x") is None  # zero pieces


# --- Writing to laptops in range


class FakeClient:
    made = []

    def __init__(self, device, fail=False):
        self.device, self.fail = device, fail
        self.is_connected = False
        self.mtu_size = 104
        self.writes = []
        FakeClient.made.append(self)

    async def connect(self):
        if self.fail:
            raise OSError("out of range")
        self.is_connected = True

    async def write_gatt_char(self, uuid, data, response):
        assert uuid == ble.INBOX_UUID and response
        self.writes.append(data)


@pytest.fixture(autouse=True)
def fresh_fakes():
    FakeClient.made = []


def test_frame_goes_to_every_laptop_in_range_in_pieces():
    clock = Clock()
    link = ble.BleLink(lambda f: None, client_factory=FakeClient, clock=clock)
    link._seen(type("D", (), {"address": "A"})(), None)
    link._seen(type("D", (), {"address": "B"})(), None)
    frame = os.urandom(300)
    assert asyncio.run(link.deliver(frame)) == 2
    for client in FakeClient.made:
        r = ble.Reassembler()
        assert [r.add(p) for p in client.writes][-1] == frame
        assert all(len(p) <= 101 for p in client.writes)
    assert link.neighbours() == 2


def test_connections_are_reused():
    link = ble.BleLink(lambda f: None, client_factory=FakeClient, clock=Clock())
    link._seen(type("D", (), {"address": "A"})(), None)
    asyncio.run(link.deliver(b"one"))
    asyncio.run(link.deliver(b"two"))
    assert len(FakeClient.made) == 1


def test_laptops_out_of_range_are_skipped_and_forgotten():
    clock = Clock()
    link = ble.BleLink(lambda f: None, client_factory=FakeClient, clock=clock)
    link._seen(type("D", (), {"address": "A"})(), None)
    clock.now += ble.DEVICE_GONE_S + 1
    assert asyncio.run(link.deliver(b"x")) == 0
    assert link.neighbours() == 0


def test_a_failed_laptop_is_left_alone_for_a_while():
    clock = Clock()
    link = ble.BleLink(lambda f: None, client_factory=lambda d: FakeClient(d, fail=True), clock=clock)
    link._seen(type("D", (), {"address": "A"})(), None)
    assert asyncio.run(link.deliver(b"x")) == 0
    assert asyncio.run(link.deliver(b"y")) == 0
    assert len(FakeClient.made) == 1  # not tried again straight away
    clock.now += ble.RETRY_AFTER_S
    link._seen(type("D", (), {"address": "A"})(), None)
    asyncio.run(link.deliver(b"z"))
    assert len(FakeClient.made) == 2


def test_pieces_written_to_our_inbox_become_frames():
    got = []
    link = ble.BleLink(got.append)
    frame = os.urandom(250)
    for piece in ble.split(frame, 64):
        link.received(piece)
    assert got == [frame]


# --- The Bluetooth process

# A stand-in for the Bluetooth process: says it is on with 2 laptops nearby, and sends
# every frame it is given straight back, as if another laptop had replied.
ECHO = """
import sys
from alertmesh import ble
out = sys.stdout.buffer
out.write(ble._message(ble.NEIGHBOURS, (2).to_bytes(2, "big")) + ble._message(ble.STATUS, b"on"))
out.flush()
while (m := ble._read_message(sys.stdin.buffer)) is not None:
    out.write(ble._message(ble.FRAME, m[1][::-1]))
    out.flush()
"""


def wait_for(condition, seconds=10):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.02)
    return condition()


def test_bluetooth_process_passes_frames_both_ways():
    got = []
    process = ble.BluetoothProcess(got.append, [sys.executable, "-c", ECHO])
    try:
        assert wait_for(lambda: process.status == "on")
        assert process.neighbours() == 2
        process.send(b"hello")
        assert wait_for(lambda: got == [b"olleh"])
    finally:
        process.stop()


@pytest.mark.skipif(sys.platform == "win32", reason="SIGABRT is how macOS stops a program")
def test_bluetooth_process_stopped_by_macos_is_explained():
    process = ble.BluetoothProcess(lambda f: None, [sys.executable, "-c", "import os; os.abort()"])
    assert wait_for(lambda: process.status.startswith("off"))
    assert "Privacy & Security" in process.status
    assert process.neighbours() == 0
    process.send(b"nobody listening")  # must not raise


def test_bluetooth_process_that_ends_says_so():
    process = ble.BluetoothProcess(lambda f: None, [sys.executable, "-c", "raise SystemExit(3)"])
    assert wait_for(lambda: process.status.startswith("off"))
    assert "exit code 3" in process.status


def test_bluetooth_command():
    assert ble.bluetooth_command()[-2:] == ["-m", "alertmesh.ble"]


def test_frames_fit_well_within_the_piece_limit():
    assert len(ble.split(os.urandom(node.MAX_FRAME_BYTES), ble.MIN_WRITE)) <= 255
    assert node.MAX_FRAME_BYTES == node.HEADER_LENGTH + chat.SEALED_MAX_BYTES
