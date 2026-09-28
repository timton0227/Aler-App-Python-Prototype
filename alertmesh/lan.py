"""The Wi-Fi link: the warning app sends signed warnings to every phone app on the
same local network.

Stands in for: alert-mesh/AlertMesh/AlertMesh/Services/OfficialAlertBridge.swift,
which carries warnings over the internet (Nostr relays). Here the "internet" is the
local network: the warning app sends each signed warning or cancellation as a UDP
multicast packet, and every phone app on the same Wi-Fi (or the same computer) hears
it. The phone app checks the signature before showing it (`node.take_official`), so a
packet from anyone else on the network is refused like a forged Bluetooth one.

Packets are sent with TTL 1: routers do not pass them on, so they stay on the local
network. Each warning is sent again every 30 seconds until it ends, for phone apps
started later; a cancellation replaces its warning.

Every packet goes out twice: on the network, and inside this computer (the loopback
interface). On macOS 15 and later a program needs "Local Network" permission before
its network multicast is delivered (until then it is dropped without an error), but
the copy inside the computer always arrives, so both apps on one computer work
regardless. Phone apps get both copies; the store keeps one.

This is free and unencumbered software released into the public domain.
"""
import os
import socket
import struct
import threading
import time

from alertmesh import wire

# An "administratively scoped" group: for use inside one organisation's network only.
GROUP = "239.255.77.7"
PORT = 47147  # ALERTMESH_LAN_PORT overrides it (the tests use their own)
MAGIC = b"AMW1"  # Alert Mesh warning, format 1
MAX_PACKET_BYTES = 1024
REPEAT_S = 30.0


def configured_port() -> int:
    return int(os.environ.get("ALERTMESH_LAN_PORT", PORT))


def packet(payload: bytes) -> bytes:
    return MAGIC + payload


def payload_of(data: bytes) -> bytes | None:
    """The warning bytes in a packet, or None for anything else on the network."""
    if len(data) > MAX_PACKET_BYTES or not data.startswith(MAGIC) or len(data) == len(MAGIC):
        return None
    return data[len(MAGIC):]


LOOPBACK = "127.0.0.1"


def _sender_socket(interface: str | None) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    if interface:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(interface))
    return s


class Broadcaster:
    """The warning app's side. `send()` sends at once, then again every `repeat_s`
    until the warning ends. Times are milliseconds since 1970."""

    def __init__(self, group: str = GROUP, port: int | None = None, repeat_s: float = REPEAT_S, clock=time.time):
        self.address = (group, port or configured_port())
        self.repeat_s = repeat_s
        self.clock = clock
        self.status = "on"
        self._network = _sender_socket(None)  # the default interface: Wi-Fi or cable
        self._inside = _sender_socket(LOOPBACK)
        self._current: dict[bytes, tuple[bytes, int]] = {}  # alert_id -> (payload, expires_at)
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        threading.Thread(target=self._repeat, name="wifi-repeat", daemon=True).start()

    def send(self, payload: bytes) -> bool:
        """Send a signed warning or cancellation now and keep repeating it.
        False if the network would not take it (then `status` says why)."""
        item = wire.decode(payload)
        if item is None:
            raise ValueError("not a warning or cancellation")
        expires_at = getattr(item, "expires_at", None)
        with self._lock:
            held = self._current.get(item.alert_id)
            if expires_at is None:  # a cancellation lives as long as the warning it ends
                expires_at = held[1] if held else int(self.clock() * 1000) + wire.MAX_LIFETIME_MS
            self._current[item.alert_id] = (payload, expires_at)
        return self._send(payload)

    def live(self) -> list[bytes]:
        now = int(self.clock() * 1000)
        with self._lock:
            for alert_id in [a for a, (_, end) in self._current.items() if end <= now]:
                del self._current[alert_id]
            return [payload for payload, _ in self._current.values()]

    def close(self) -> None:
        self._stopped.set()
        self._network.close()
        self._inside.close()

    def _send(self, payload: bytes) -> bool:
        """True if it went on the network. The copy inside this computer is sent either way."""
        try:
            self._inside.sendto(packet(payload), self.address)
        except OSError:
            pass
        try:
            self._network.sendto(packet(payload), self.address)
            self.status = "on"
            return True
        except OSError as error:  # no network at all
            self.status = f"this computer only: {error.strerror or error}"
            return False

    def _repeat(self) -> None:
        while not self._stopped.wait(self.repeat_s):
            for payload in self.live():
                self._send(payload)


class Listener:
    """The phone app's side: hands every warning packet heard to `on_payload`.
    Several phone apps on one computer can listen at once."""

    def __init__(self, on_payload, group: str = GROUP, port: int | None = None):
        port = port or configured_port()
        self.on_payload = on_payload
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        s.bind(("", port))
        joined = 0
        for interface in ("0.0.0.0", LOOPBACK):  # the default interface, then inside this computer
            try:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                             struct.pack("4s4s", socket.inet_aton(group), socket.inet_aton(interface)))
                joined += 1
            except OSError:  # no network: this computer only
                pass
        if not joined:
            s.close()
            raise OSError("could not listen for warnings")
        self._socket = s
        threading.Thread(target=self._listen, name="wifi-listen", daemon=True).start()

    def close(self) -> None:
        self._socket.close()

    def _listen(self) -> None:
        while True:
            try:
                data, _ = self._socket.recvfrom(MAX_PACKET_BYTES + 1)
            except OSError:
                return  # closed
            payload = payload_of(data)
            if payload is not None:
                self.on_payload(payload)
