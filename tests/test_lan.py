"""Tests for alertmesh.lan, over this computer's own network (the loopback copy).

Two computers on one Wi-Fi are checked by hand (README, "Two-laptop check").
"""
import os
import socket
import threading
import time

import pytest

from alertmesh import lan, wire
from alertmesh.signer import OfficialAlertSigner, WarningDraft

HOUR_MS = 60 * 60 * 1000


def wait_for(condition, seconds=5):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    return condition()


@pytest.fixture
def port():
    # A port of our own, so a running phone app does not hear the tests.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture
def heard(port):
    got = []
    lock = threading.Lock()

    def add(payload):
        with lock:
            got.append(payload)

    listener = lan.Listener(add, port=port)
    yield got
    listener.close()


def make_alert(now_ms):
    draft = WarningDraft(headline="Flooding", action_text="Move to higher ground.",
                         duration_hours=1, area_cells=["r7hg"])
    return OfficialAlertSigner().sign(draft, os.urandom(16), now_ms)


def test_packets_carry_only_warning_bytes():
    assert lan.payload_of(lan.packet(b"abc")) == b"abc"
    assert lan.payload_of(b"hello") is None                     # someone else's packet
    assert lan.payload_of(lan.MAGIC) is None                    # empty
    assert lan.payload_of(lan.packet(bytes(lan.MAX_PACKET_BYTES))) is None  # oversize


def test_warning_arrives_on_this_computer(port, heard):
    broadcaster = lan.Broadcaster(port=port)
    payload = wire.encode(make_alert(int(time.time() * 1000)))
    broadcaster.send(payload)
    assert wait_for(lambda: payload in heard)
    broadcaster.close()


def test_two_listeners_on_one_computer_both_hear_it(port, heard):
    second = []
    other = lan.Listener(second.append, port=port)
    broadcaster = lan.Broadcaster(port=port)
    payload = wire.encode(make_alert(int(time.time() * 1000)))
    broadcaster.send(payload)
    assert wait_for(lambda: payload in heard and payload in second)
    broadcaster.close()
    other.close()


def test_junk_on_the_port_is_ignored(port, heard):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(lan.LOOPBACK))
        s.sendto(b"junk", (lan.GROUP, port))
        s.sendto(lan.packet(bytes(2000)), (lan.GROUP, port))
        s.sendto(lan.packet(b"ok"), (lan.GROUP, port))
    assert wait_for(lambda: b"ok" in heard)
    assert heard == [b"ok"] * len(heard)


def test_packets_do_not_leave_the_local_network():
    s = lan._sender_socket(None)
    assert s.getsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL) == 1
    s.close()


def test_warning_is_repeated_until_it_ends(port, heard):
    now = int(time.time() * 1000)
    broadcaster = lan.Broadcaster(port=port, repeat_s=0.1)
    payload = wire.encode(make_alert(now))
    broadcaster.send(payload)
    assert wait_for(lambda: heard.count(payload) >= 4)
    broadcaster.close()


def test_cancellation_replaces_its_warning_and_ended_ones_stop():
    clock_s = [time.time()]
    broadcaster = lan.Broadcaster(port=1, repeat_s=3600, clock=lambda: clock_s[0])
    now = int(clock_s[0] * 1000)
    alert = make_alert(now)
    other = make_alert(now)
    broadcaster.send(wire.encode(alert))
    broadcaster.send(wire.encode(other))
    cancel = wire.encode(OfficialAlertSigner().cancel(alert.alert_id, now + 1))
    broadcaster.send(cancel)
    assert sorted(broadcaster.live()) == sorted([cancel, wire.encode(other)])
    clock_s[0] += HOUR_MS / 1000 + 1  # both warnings have ended; so has the cancellation
    assert broadcaster.live() == []
    broadcaster.close()


def test_only_warnings_can_be_sent():
    broadcaster = lan.Broadcaster(port=1)
    with pytest.raises(ValueError):
        broadcaster.send(b"not a warning")
    broadcaster.close()
