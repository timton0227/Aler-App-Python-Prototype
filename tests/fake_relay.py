"""A small Nostr relay for the tests, on this computer only (127.0.0.1).

It keeps every event it is sent, answers OK, and serves subscriptions (kinds, "#g",
since and limit), like a real relay but without checking anything unless told to.
The tests use it so they never reach the real relays.
"""
import json
import threading

from websockets.sync.server import serve

from alertmesh.nostr import Event


def matches(subscription: dict, event: dict) -> bool:
    if "kinds" in subscription and event["kind"] not in subscription["kinds"]:
        return False
    if "since" in subscription and event["created_at"] < subscription["since"]:
        return False
    for key, values in subscription.items():
        if key.startswith("#"):
            tagged = {tag[1] for tag in event["tags"] if len(tag) > 1 and tag[0] == key[1:]}
            if not tagged & set(values):
                return False
    return True


class FakeRelay:
    def __init__(self, check_signatures: bool = True, port: int = 0):
        self.check_signatures = check_signatures
        self.events: list[dict] = []
        self.requests: list[list] = []  # every REQ and CLOSE, as sent
        self.connections = 0
        self._clients: list[tuple[object, dict]] = []  # (socket, its subscriptions)
        self._lock = threading.Lock()
        self._server = serve(self._handle, "127.0.0.1", port)
        self.url = f"ws://127.0.0.1:{self._server.socket.getsockname()[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()

    def drop_connections(self) -> None:
        """Close every client's connection, as a relay restart would."""
        with self._lock:
            clients = list(self._clients)
        for socket, _ in clients:
            socket.close()

    def _handle(self, socket) -> None:
        subscriptions: dict[str, dict] = {}
        with self._lock:
            self.connections += 1
            self._clients.append((socket, subscriptions))
        try:
            for raw in socket:
                message = json.loads(raw)
                if message[0] == "EVENT":
                    self._event(socket, message[1])
                elif message[0] == "REQ":
                    with self._lock:
                        self.requests.append(message)
                        subscriptions[message[1]] = message[2]
                        stored = [e for e in self.events if matches(message[2], e)]
                    if message[2].get("limit"):
                        stored = stored[-message[2]["limit"]:]
                    for event in stored:
                        socket.send(json.dumps(["EVENT", message[1], event]))
                    socket.send(json.dumps(["EOSE", message[1]]))
                elif message[0] == "CLOSE":
                    with self._lock:
                        self.requests.append(message)
                        subscriptions.pop(message[1], None)
        except Exception:
            pass
        finally:
            with self._lock:
                self._clients = [c for c in self._clients if c[0] is not socket]

    def _event(self, socket, event: dict) -> None:
        parsed = Event.from_dict(event)
        if self.check_signatures and (parsed is None or not parsed.is_valid()):
            socket.send(json.dumps(["OK", event.get("id", ""), False, "invalid: bad signature"]))
            return
        with self._lock:
            known = any(e["id"] == event["id"] for e in self.events)
            if not known:
                self.events.append(event)
            clients = list(self._clients)
        socket.send(json.dumps(["OK", event["id"], True, "duplicate:" if known else ""]))
        if known:
            return
        for client, subscriptions in clients:
            for sub_id, subscription in list(subscriptions.items()):
                if matches(subscription, event):
                    try:
                        client.send(json.dumps(["EVENT", sub_id, event]))
                    except Exception:
                        pass

    def store(self, event: dict) -> None:
        """Hold an event as if a client had sent it, and pass it to subscribers."""
        self._event(_Nowhere(), event)

    def send_raw(self, sub_id: str, event: dict) -> None:
        """Send an event to every client subscribed as `sub_id`, whatever it is."""
        with self._lock:
            clients = list(self._clients)
        for client, subscriptions in clients:
            if sub_id in subscriptions:
                client.send(json.dumps(["EVENT", sub_id, event]))


class _Nowhere:
    def send(self, message) -> None:
        pass
