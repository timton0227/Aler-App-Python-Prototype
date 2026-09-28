"""The relay link: talks to Nostr relays over WebSockets.

Ported from: ../alert-mesh/AlertMesh/Nostr/NostrRelayManager.swift (connect, sendEvent,
             subscribe, unsubscribe, the inbound checks, reconnect with backoff).

A relay speaks a small JSON protocol (NIP-01) over a WebSocket:
- ["EVENT", event] sends an event; the relay answers ["OK", id, true/false, why];
- ["REQ", id, filter] asks for stored and new events that match; the relay sends
  ["EVENT", id, event] for each, and ["EOSE", id] once the stored ones are done;
- ["CLOSE", id] ends a subscription.

`RelayPool` keeps one connection per relay, each in its own thread. Publishing and
subscribing only record what is wanted; each relay's thread sends it once connected,
and again after a reconnect, so nothing depends on the timing of the network. Events
from relays are checked (tags, ID and signature) before any handler sees them, and an
event several relays send is handed on once.

Needs the `websockets` library (in requirements.txt). Without it the pool says so in
`status` instead of connecting.

This is free and unencumbered software released into the public domain.
"""
import json
import random
import ssl
import threading
import time
from collections import OrderedDict

from alertmesh import georelays
from alertmesh.nostr import Event

# TransportConfig.nostrRelayInitialBackoffSeconds, MaxBackoffSeconds, BackoffMultiplier,
# BackoffJitterRatio.
BACKOFF_INITIAL_S = 1.0
BACKOFF_MAX_S = 300.0
BACKOFF_MULTIPLIER = 2.0
BACKOFF_JITTER = 0.2
OPEN_TIMEOUT_S = 10.0
POLL_S = 0.2  # how often a relay's thread looks for new things to send
MAX_MESSAGE_BYTES = 1 << 20
MAX_PENDING_EVENTS = 100  # per relay, while it cannot be reached
SEEN_CAPACITY = 2000  # event IDs remembered, so one sent by several relays is handed on once


def _connect_function():
    try:
        from websockets.sync.client import connect
    except ImportError:
        return None
    return connect


class _Relay:
    """One relay's connection, run by its own thread."""

    def __init__(self, pool: "RelayPool", url: str):
        self.pool = pool
        self.url = url
        self.connected = False
        self.error: str | None = None
        self.pending: OrderedDict[str, Event] = OrderedDict()  # sent until the relay answers OK
        self.thread = threading.Thread(target=self._run, name=f"relay {url}", daemon=True)

    def _run(self) -> None:
        attempts = 0
        while not self.pool._stopped.is_set():
            try:
                self._session()
                attempts = 0  # it connected, then dropped
            except Exception as error:  # refused, unreachable, closed, a bad certificate ...
                self.error = str(error) or type(error).__name__
                attempts += 1
            finally:
                self.connected = False
            if self.pool._stopped.is_set():
                return
            base = min(BACKOFF_INITIAL_S * BACKOFF_MULTIPLIER ** max(attempts - 1, 0), BACKOFF_MAX_S)
            self.pool._stopped.wait(base * (1 + random.uniform(-BACKOFF_JITTER, BACKOFF_JITTER)))

    def _session(self) -> None:
        options = {"open_timeout": OPEN_TIMEOUT_S, "max_size": MAX_MESSAGE_BYTES}
        if self.url.startswith("wss://"):
            options["ssl"] = self.pool._ssl_context()
        with self.pool._connect(self.url, **options) as socket:
            self.connected = True
            self.error = None
            sent_subscriptions: dict[str, str] = {}  # id -> the filter as sent
            sent_events: set[str] = set()
            while not self.pool._stopped.is_set():
                for message in self._outgoing(sent_subscriptions, sent_events):
                    socket.send(message)
                try:
                    raw = socket.recv(timeout=POLL_S)
                except TimeoutError:
                    continue
                self.pool._take(self, raw)

    def _outgoing(self, sent_subscriptions: dict, sent_events: set) -> list[str]:
        """What this connection has not sent yet: new or changed subscriptions, ended
        ones, and events waiting for this relay."""
        messages = []
        wanted = self.pool._subscriptions_for(self.url)
        for sub_id, subscription in wanted.items():
            text = json.dumps(subscription, sort_keys=True)
            if sent_subscriptions.get(sub_id) != text:
                messages.append(json.dumps(["REQ", sub_id, subscription]))
                sent_subscriptions[sub_id] = text
        for sub_id in [s for s in sent_subscriptions if s not in wanted]:
            messages.append(json.dumps(["CLOSE", sub_id]))
            del sent_subscriptions[sub_id]
        with self.pool._lock:
            events = [e for e in self.pending.values() if e.id not in sent_events]
        for event in events:
            messages.append(json.dumps(["EVENT", event.to_dict()]))
            sent_events.add(event.id)
        return messages


class RelayPool:
    """Connections to any number of relays. `connect` is `websockets.sync.client.connect`
    unless a test passes its own."""

    def __init__(self, connect=None, ssl_context=None):
        self._connect = connect or _connect_function()
        self._ssl = ssl_context
        self._relays: dict[str, _Relay] = {}
        self._subscriptions: dict[str, tuple[dict, frozenset, object]] = {}  # id -> (filter, urls, handler)
        self._results: dict[str, dict[str, tuple[bool, str]]] = {}  # event id -> url -> (accepted, why)
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.RLock()
        self._stopped = threading.Event()

    @property
    def available(self) -> bool:
        return self._connect is not None

    # --- What the apps call ---

    def publish(self, event: Event, urls) -> None:
        """Send an event to these relays, now or once each can be reached."""
        if not self.available:
            return
        with self._lock:
            self._results.setdefault(event.id, {})
            for url in urls:
                relay = self._relay(url)
                relay.pending[event.id] = event
                while len(relay.pending) > MAX_PENDING_EVENTS:
                    relay.pending.popitem(last=False)

    def subscribe(self, sub_id: str, subscription: dict, urls, handler) -> None:
        """Ask these relays for events matching `subscription`, stored and new. Each
        verified event goes to `handler(event)`, once. Replaces a subscription of the
        same id (other relays, another filter)."""
        if not self.available:
            return
        with self._lock:
            self._subscriptions[sub_id] = (dict(subscription), frozenset(urls), handler)
            for url in urls:
                self._relay(url)

    def unsubscribe(self, sub_id: str) -> None:
        with self._lock:
            self._subscriptions.pop(sub_id, None)

    def results(self, event_id: str) -> dict[str, tuple[bool, str]]:
        """Each relay's answer to a published event so far: url -> (accepted, why)."""
        with self._lock:
            return dict(self._results.get(event_id, {}))

    def status(self) -> tuple[int, int]:
        """(relays connected, relays in use)."""
        with self._lock:
            return sum(r.connected for r in self._relays.values()), len(self._relays)

    def close(self) -> None:
        self._stopped.set()

    # --- Inside ---

    def _ssl_context(self) -> ssl.SSLContext:
        if self._ssl is None:
            self._ssl = georelays._https_context()
        return self._ssl

    def _relay(self, url: str) -> _Relay:
        relay = self._relays.get(url)
        if relay is None:
            relay = self._relays[url] = _Relay(self, url)
            relay.thread.start()
        return relay

    def _subscriptions_for(self, url: str) -> dict[str, dict]:
        with self._lock:
            return {sub_id: subscription for sub_id, (subscription, urls, _) in self._subscriptions.items()
                    if url in urls}

    def _take(self, relay: _Relay, raw) -> None:
        """One message from a relay."""
        try:
            message = json.loads(raw)
        except (ValueError, TypeError):
            return
        if not isinstance(message, list) or not message:
            return
        if message[0] == "OK" and len(message) >= 3 and isinstance(message[1], str):
            why = message[3] if len(message) > 3 and isinstance(message[3], str) else ""
            with self._lock:
                if message[1] in relay.pending:
                    del relay.pending[message[1]]
                    self._results.setdefault(message[1], {})[relay.url] = (message[2] is True, why)
        elif message[0] == "EVENT" and len(message) >= 3 and isinstance(message[1], str):
            with self._lock:
                entry = self._subscriptions.get(message[1])
            event = Event.from_dict(message[2]) if entry else None
            if event is None or event.id in self._seen:
                return
            # Checked before it is marked seen: a forged copy with a genuine event's ID
            # must not block the genuine one (deliverVerifiedInboundEvent).
            if not event.is_valid():
                return
            with self._lock:
                if event.id in self._seen:
                    return
                self._seen[event.id] = None
                while len(self._seen) > SEEN_CAPACITY:
                    self._seen.popitem(last=False)
            entry[2](event)
