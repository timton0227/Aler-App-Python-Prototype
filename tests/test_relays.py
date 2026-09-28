"""Tests for alertmesh.relays, against a relay run inside the tests (fake_relay.py).

The real relays are checked by hand and by tools/nostr_live_check.py (step 15.7).
"""
import json
import socket
import time

import pytest

pytest.importorskip("websockets")

from alertmesh import nostr, relays  # noqa: E402
from fake_relay import FakeRelay  # noqa: E402


def wait_for(condition, seconds=5):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    return condition()


@pytest.fixture
def relay():
    r = FakeRelay()
    yield r
    r.close()


@pytest.fixture
def pool():
    p = relays.RelayPool()
    yield p
    p.close()


def test_publish_reaches_the_relay_and_its_answer_is_kept(relay, pool):
    event = nostr.sign_event(1403, [["g", "r7"]], "abc")
    pool.publish(event, [relay.url])
    assert wait_for(lambda: pool.results(event.id) == {relay.url: (True, "")})
    assert relay.events == [event.to_dict()]
    assert pool.status() == (1, 1)


def test_a_refused_event_is_reported_with_the_reason(relay, pool):
    event = nostr.sign_event(1, [], "x")
    forged = nostr.Event(event.id, event.pubkey, event.created_at, event.kind, event.tags, "changed", event.sig)
    pool.publish(forged, [relay.url])
    assert wait_for(lambda: pool.results(forged.id) == {relay.url: (False, "invalid: bad signature")})


def test_an_event_published_before_the_relay_is_up_is_sent_once_it_is(pool, monkeypatch):
    monkeypatch.setattr(relays, "BACKOFF_INITIAL_S", 0.05)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    url = f"ws://127.0.0.1:{port}"
    event = nostr.sign_event(1, [], "waiting")
    pool.publish(event, [url])
    assert wait_for(lambda: pool._relays[url].error is not None)  # nothing listens there yet
    assert pool.results(event.id) == {} and pool.status() == (0, 1)
    relay = FakeRelay(port=port)
    assert wait_for(lambda: pool.results(event.id) == {url: (True, "")}, seconds=10)
    assert relay.events == [event.to_dict()]
    relay.close()


def test_subscribe_gets_stored_and_new_events_once_each(relay, pool):
    stored = nostr.sign_event(1403, [], "stored")
    relay.store(stored.to_dict())
    got = []
    pool.subscribe("alerts", nostr.official_alerts_filter(), [relay.url], got.append)
    assert wait_for(lambda: got == [stored])
    new = nostr.sign_event(1403, [], "new")
    other_kind = nostr.sign_event(1402, [], "a report")
    pool.publish(new, [relay.url])
    pool.publish(other_kind, [relay.url])
    assert wait_for(lambda: got == [stored, new])
    time.sleep(0.3)
    assert got == [stored, new]


def test_an_event_from_two_relays_is_handed_on_once(pool):
    first, second = FakeRelay(), FakeRelay()
    got = []
    pool.subscribe("alerts", nostr.official_alerts_filter(), [first.url, second.url], got.append)
    assert wait_for(lambda: pool.status() == (2, 2) and len(first.requests) == len(second.requests) == 1)
    event = nostr.sign_event(1403, [], "both")
    first.store(event.to_dict())
    second.store(event.to_dict())
    assert wait_for(lambda: got == [event])
    time.sleep(0.3)
    assert got == [event]
    first.close()
    second.close()


def test_forged_and_malformed_events_are_dropped_and_do_not_block_the_genuine_one(relay, pool):
    got = []
    pool.subscribe("alerts", nostr.official_alerts_filter(), [relay.url], got.append)
    assert wait_for(lambda: len(relay.requests) == 1)
    genuine = nostr.sign_event(1403, [], "genuine")
    forged = dict(genuine.to_dict(), content="forged")  # the genuine ID, other content
    relay.send_raw("alerts", forged)
    relay.send_raw("alerts", {"id": "x"})
    relay.send_raw("alerts", dict(genuine.to_dict(), tags=[["t", "x"]] * 65))
    relay.send_raw("alerts", genuine.to_dict())
    assert wait_for(lambda: got == [genuine])


def test_events_for_an_unknown_subscription_are_ignored(relay, pool):
    got = []
    pool.subscribe("alerts", nostr.official_alerts_filter(), [relay.url], got.append)
    assert wait_for(lambda: len(relay.requests) == 1)
    relay._clients[0][1]["other"] = {}
    relay.send_raw("other", nostr.sign_event(1403, [], "x").to_dict())
    time.sleep(0.3)
    assert got == []


def test_changing_a_subscription_sends_a_new_request_and_unsubscribing_closes_it(relay, pool):
    pool.subscribe("reports", nostr.community_reports_filter(["r7hg"]), [relay.url], lambda e: None)
    assert wait_for(lambda: len(relay.requests) == 1)
    pool.subscribe("reports", nostr.community_reports_filter(["r7hu"]), [relay.url], lambda e: None)
    assert wait_for(lambda: len(relay.requests) == 2)
    assert relay.requests[1][2]["#g"] == ["r7hu"]
    pool.unsubscribe("reports")
    assert wait_for(lambda: relay.requests[-1] == ["CLOSE", "reports"])


def test_moving_a_subscription_to_other_relays_closes_it_on_the_old_one(pool):
    old, new = FakeRelay(), FakeRelay()
    pool.subscribe("reports", nostr.community_reports_filter(["r7hg"]), [old.url], lambda e: None)
    assert wait_for(lambda: len(old.requests) == 1)
    pool.subscribe("reports", nostr.community_reports_filter(["qd66"]), [new.url], lambda e: None)
    assert wait_for(lambda: len(new.requests) == 1 and old.requests[-1] == ["CLOSE", "reports"])
    old.close()
    new.close()


def test_after_a_drop_it_reconnects_and_asks_again(relay, pool, monkeypatch):
    monkeypatch.setattr(relays, "BACKOFF_INITIAL_S", 0.05)
    got = []
    pool.subscribe("alerts", nostr.official_alerts_filter(), [relay.url], got.append)
    assert wait_for(lambda: relay.connections == 1 and len(relay.requests) == 1)
    relay.drop_connections()
    assert wait_for(lambda: relay.connections == 2 and len(relay.requests) == 2, seconds=10)
    event = nostr.sign_event(1403, [], "after the drop")
    pool.publish(event, [relay.url])
    assert wait_for(lambda: got == [event])


def test_without_the_websockets_library_nothing_connects():
    pool = relays.RelayPool(connect=None)
    pool._connect = None
    pool.publish(nostr.sign_event(1, [], "x"), ["ws://127.0.0.1:9"])
    pool.subscribe("a", {}, ["ws://127.0.0.1:9"], print)
    assert not pool.available and pool.status() == (0, 0)


def test_messages_that_are_not_nostr_are_ignored(relay, pool):
    r = relays._Relay(pool, relay.url)
    for raw in ("not json", "{}", "[]", json.dumps(["OK"]), json.dumps(["EVENT", 5, {}]), json.dumps(["NOTICE", "hi"])):
        pool._take(r, raw)
