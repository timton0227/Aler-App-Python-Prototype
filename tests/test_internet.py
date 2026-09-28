"""Tests for alertmesh.internet, against a relay run inside the tests (fake_relay.py).

Ported from: ../alert-mesh/AlertMeshTests/AlertMesh/Services/OfficialAlertBridgeTests.swift
             (aWarningIsPublishedWithItsAreaTagsAndExpiry, aCancellationIsTaggedWithTheWarningsArea,
             withNoRelaysNothingIsPublished).
"""
import time

import pytest

from alertmesh import georelays, internet, nostr, wire
from alertmesh.signer import OfficialAlertSigner, WarningDraft

NOW_MS = int(time.time() * 1000)


def warning(cells=("r7hg2bc", "r7hu")):
    draft = WarningDraft(headline="Flood", action_text="Move to higher ground", area_cells=list(cells))
    return OfficialAlertSigner().sign(draft, bytes(range(16)), NOW_MS)


class Recorder:
    """Stands in for the relay pool."""

    available = True

    def __init__(self):
        self.published = []

    def publish(self, event, urls):
        self.published.append((event, list(urls)))

    def results(self, event_id):
        return {}


class FakeDirectory:
    def relays_for(self, cell, count=5):
        return [f"wss://relay-{cell}.example"]

    def refresh_if_due(self):
        return False


def test_relays_for_a_warning_are_the_built_in_ones_and_each_cells_geo_relays():
    choice = internet.RelayChoice(["wss://built-in.example"], FakeDirectory())
    assert choice.for_warning(["r7hg2bc", "R7HU", "r"]) == [
        "wss://built-in.example", "wss://relay-r7hg.example", "wss://relay-r7hu.example"]
    assert choice.geo("r7hg2bc") == ["wss://relay-r7hg.example"]
    assert choice.for_warning([]) == []


def test_named_relays_replace_every_other(monkeypatch):
    monkeypatch.setenv(nostr.RELAYS_VARIABLE, "ws://127.0.0.1:1")
    choice = internet.RelayChoice.from_environment()
    assert choice.directory is None
    assert choice.for_warning(["r7hg"]) == ["ws://127.0.0.1:1"] and choice.geo("r7hg") == ["ws://127.0.0.1:1"]


def test_without_a_name_the_built_in_and_geo_relays_are_used(monkeypatch):
    monkeypatch.delenv(nostr.RELAYS_VARIABLE)
    choice = internet.RelayChoice.from_environment()
    assert choice.built_in == list(nostr.BUILT_IN_RELAYS)
    assert isinstance(choice.directory, georelays.Directory)


def sender():
    pool = Recorder()
    s = internet.WarningSender(pool, internet.RelayChoice(["wss://built-in.example"], FakeDirectory()))
    return s, pool


def test_nothing_is_published_while_off():
    s, pool = sender()
    assert not s.send(wire.encode(warning()))
    assert pool.published == [] and s.status() is None


def test_a_warning_is_published_with_its_area_tags_and_expiry():
    s, pool = sender()
    s.enabled = True
    alert = warning()
    assert s.send(wire.encode(alert))
    [(event, relays)] = pool.published
    assert event.kind == 1403 and event.is_valid()
    assert ("g", "r7hg") in event.tags and ("g", "r7hu") in event.tags
    assert ("expiration", str(alert.expires_at // 1000)) in event.tags
    assert nostr.payload_of(event, 1403) == wire.encode(alert)
    assert relays == ["wss://built-in.example", "wss://relay-r7hg.example", "wss://relay-r7hu.example"]
    assert s.status() == (0, 3)


def test_a_cancellation_is_tagged_with_the_warnings_area_even_if_sent_while_off():
    s, pool = sender()
    alert = warning()
    s.send(wire.encode(alert))  # off: remembered, not published
    s.enabled = True
    cancellation = OfficialAlertSigner().cancel(alert.alert_id, NOW_MS + 1)
    assert s.send(wire.encode(cancellation))
    [(event, _)] = pool.published
    assert ("g", "r7hg") in event.tags and ("expiration", str(alert.expires_at // 1000)) in event.tags


def test_a_cancellation_of_an_unknown_warning_or_garbage_is_not_published():
    s, pool = sender()
    s.enabled = True
    assert not s.send(wire.encode(OfficialAlertSigner().cancel(bytes(16), NOW_MS)))
    assert not s.send(b"garbage")
    assert pool.published == []


def test_with_no_relays_nothing_is_published():
    pool = Recorder()
    s = internet.WarningSender(pool, internet.RelayChoice([], None))
    s.enabled = True
    assert not s.send(wire.encode(warning()))
    assert pool.published == []


def test_a_warning_reaches_a_relay_and_its_answer_counts():
    pytest.importorskip("websockets")
    from alertmesh.relays import RelayPool
    from fake_relay import FakeRelay

    relay = FakeRelay()
    pool = RelayPool()
    s = internet.WarningSender(pool, internet.RelayChoice([relay.url], None))
    s.enabled = True
    alert = warning()
    assert s.send(wire.encode(alert))
    deadline = time.monotonic() + 5
    while s.status() != (1, 1) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert s.status() == (1, 1)
    [stored] = relay.events
    assert wire.decode(nostr.payload_of(nostr.Event.from_dict(stored), 1403)) == alert
    pool.close()
    relay.close()
