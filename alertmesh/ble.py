"""The Bluetooth link: the only part of the phone app that touches the radio.

Modelled on: ../alert-mesh/AlertMesh/Services/BLE/BLEService+LinkLayerCentralRole.swift
             (scan, connect, write) and BLEService+LinkLayerPeripheralRole.swift
             (advertise, receive), and the iPhone app's fragments (MessageType.fragment).

Each laptop does both jobs, like the iPhone app:
- it advertises the Alert Mesh service, whose one characteristic ("inbox") other
  laptops write frames to (library: `bless`);
- it scans for other laptops advertising that service, connects to them, and writes
  each frame to their inbox (library: `bleak`).

A Bluetooth write carries only about 20 to 500 bytes, depending on the two laptops, so
each frame is cut into pieces, each with a 6-byte label (a random 4-byte tag for the
frame, the piece number and the piece count), and put back together on arrival.
Pieces of a frame that never completes are dropped after 10 seconds.

Bluetooth runs in a separate small process (`BluetoothProcess`), because on a Mac the
program that runs Python needs Bluetooth permission, and macOS stops any program whose
app does not say why it uses Bluetooth (see tools/ble_probe.py). If that happens, only
the Bluetooth process stops, and the phone app says why instead of vanishing. The two
talk through the child's standard input and output. Inside the child, `BleLink` runs
the radio on an asyncio loop.

This is free and unencumbered software released into the public domain.
"""
import asyncio
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass

# Alert Mesh's own IDs: not the iPhone app's, so iPhones running it ignore these laptops.
SERVICE_UUID = "aa857bb9-f31d-4aa0-8eb7-1f871477f392"
INBOX_UUID = "dc246a61-32ff-4d2f-9f03-0c1d30343d78"

PIECE_LABEL_LENGTH = 6
# The smallest write every Bluetooth LE device must take (23-byte link, minus 3).
MIN_WRITE = 20
# Used when a link does not say how big its writes can be. Laptops usually allow more.
DEFAULT_WRITE = 180
PARTIAL_TIMEOUT_S = 10.0
# A laptop not heard advertising for this long is out of range.
DEVICE_GONE_S = 30.0
CONNECT_TIMEOUT_S = 10.0
# After a laptop fails to connect, leave it alone this long before trying again.
RETRY_AFTER_S = 15.0


# --- Pieces -------------------------------------------------------------------


def split(frame: bytes, write_size: int) -> list[bytes]:
    """Cut a frame into pieces that each fit one write of `write_size` bytes."""
    room = max(write_size, MIN_WRITE) - PIECE_LABEL_LENGTH
    chunks = [frame[i:i + room] for i in range(0, len(frame), room)] or [b""]
    if len(chunks) > 255:
        raise ValueError("frame too big to send in pieces")
    tag = os.urandom(4)
    return [tag + bytes([index, len(chunks)]) + chunk for index, chunk in enumerate(chunks)]


@dataclass
class _Partial:
    pieces: dict[int, bytes]
    count: int
    started: float


class Reassembler:
    """Puts pieces back into frames. Pieces may arrive from several laptops at once,
    so each frame is kept apart by its tag."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._partials: dict[bytes, _Partial] = {}

    def add(self, piece: bytes) -> bytes | None:
        """The whole frame once its last piece arrives, else None."""
        now = self.clock()
        for tag in [t for t, p in self._partials.items() if now - p.started > PARTIAL_TIMEOUT_S]:
            del self._partials[tag]
        if len(piece) < PIECE_LABEL_LENGTH:
            return None
        tag, index, count, chunk = piece[:4], piece[4], piece[5], piece[PIECE_LABEL_LENGTH:]
        if count == 0 or index >= count:
            return None
        partial = self._partials.setdefault(tag, _Partial({}, count, now))
        if partial.count != count:
            return None
        partial.pieces[index] = chunk
        if len(partial.pieces) < count:
            return None
        del self._partials[tag]
        return b"".join(partial.pieces[i] for i in range(count))


# --- The link -----------------------------------------------------------------


def _bleak_client(device):
    from bleak import BleakClient

    return BleakClient(device, timeout=CONNECT_TIMEOUT_S)


class BleLink:
    """Advertise, scan, connect and write, on a background thread.

    `status` says in plain words what Bluetooth is doing, for the page to show.
    `client_factory` makes the connection to one laptop; tests pass a fake.
    """

    def __init__(self, on_frame, name: str = "AlertMesh", client_factory=_bleak_client, clock=time.monotonic):
        self.on_frame = on_frame
        self.name = name
        self.client_factory = client_factory
        self.clock = clock
        self.status = "starting"
        self.reassembler = Reassembler(clock)
        self._devices: dict[str, tuple[object, float]] = {}  # address -> (device, last seen)
        self._clients: dict[str, object] = {}
        self._failed: dict[str, float] = {}  # address -> when it last failed
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None

    # --- Called from any thread ---

    def start(self) -> "BleLink":
        threading.Thread(target=self._run, name="bluetooth", daemon=True).start()
        return self

    def send(self, frame: bytes) -> None:
        if self._loop is not None and self._queue is not None:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, frame)

    def neighbours(self) -> int:
        now = self.clock()
        with self._lock:
            return sum(1 for _, seen in self._devices.values() if now - seen <= DEVICE_GONE_S)

    # --- The Bluetooth thread ---

    def _run(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception as error:  # the libraries raise plain Exceptions
            self.status = f"Bluetooth stopped: {error}"

    async def _main(self) -> None:
        from bleak import BleakScanner

        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        await self._advertise()
        scanner = BleakScanner(self._seen, service_uuids=[SERVICE_UUID])
        await scanner.start()
        self.status = "on"
        while True:
            await self.deliver(await self._queue.get())

    async def _advertise(self) -> None:
        from bless import BlessServer, GATTAttributePermissions, GATTCharacteristicProperties

        server = BlessServer(name=self.name)
        server.read_request_func = lambda characteristic, **_: characteristic.value
        server.write_request_func = lambda characteristic, value: self.received(bytes(value))
        await server.add_new_service(SERVICE_UUID)
        await server.add_new_characteristic(
            SERVICE_UUID, INBOX_UUID,
            GATTCharacteristicProperties.write | GATTCharacteristicProperties.write_without_response,
            None, GATTAttributePermissions.writeable,
        )
        await server.start()
        self._server = server  # kept, or advertising stops when it is collected

    def _seen(self, device, advertisement) -> None:
        with self._lock:
            self._devices[device.address] = (device, self.clock())

    def received(self, piece: bytes) -> None:
        """A piece written to our inbox."""
        frame = self.reassembler.add(piece)
        if frame is not None:
            self.on_frame(frame)

    async def deliver(self, frame: bytes) -> int:
        """Write one frame to every laptop in range. Returns how many took it."""
        now = self.clock()
        with self._lock:
            targets = [(address, device) for address, (device, seen) in self._devices.items()
                       if now - seen <= DEVICE_GONE_S
                       and now - self._failed.get(address, -RETRY_AFTER_S) >= RETRY_AFTER_S]
        delivered = 0
        for address, device in targets:
            try:
                client = self._clients.get(address)
                if client is None or not client.is_connected:
                    client = self.client_factory(device)
                    await client.connect()
                    self._clients[address] = client
                for piece in split(frame, client.mtu_size - 3 if client.mtu_size else DEFAULT_WRITE):
                    await client.write_gatt_char(INBOX_UUID, piece, response=True)
                delivered += 1
            except Exception:  # out of range, turned off, or refused: try again later
                self._clients.pop(address, None)
                self._failed[address] = now
        return delivered


# --- The Bluetooth process ----------------------------------------------------

# Messages between the app and its Bluetooth process: 1-byte type, 2-byte length, data.
FRAME, NEIGHBOURS, STATUS = b"F", b"N", b"S"
STATUS_EVERY_S = 1.0


def _message(kind: bytes, data: bytes) -> bytes:
    return kind + len(data).to_bytes(2, "big") + data


def _read_message(stream) -> tuple[bytes, bytes] | None:
    head = stream.read(3)
    if len(head) < 3:
        return None
    data = stream.read(int.from_bytes(head[1:], "big"))
    return head[:1], data


def bluetooth_command() -> list[str]:
    """How to start the Bluetooth process. The packaged app is its own Python."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--bluetooth"]
    return [sys.executable, "-m", "alertmesh.ble"]


def child_main(name: str = "AlertMesh") -> None:
    """The Bluetooth process: frames in on standard input, frames and news out on
    standard output. Stops when the app closes its end."""
    out = sys.stdout.buffer
    out_lock = threading.Lock()

    def write(kind: bytes, data: bytes) -> None:
        with out_lock:
            out.write(_message(kind, data))
            out.flush()

    link = BleLink(lambda frame: write(FRAME, frame), name)
    link.start()

    def report() -> None:
        while True:
            write(NEIGHBOURS, link.neighbours().to_bytes(2, "big"))
            write(STATUS, link.status.encode()[:500])
            time.sleep(STATUS_EVERY_S)

    threading.Thread(target=report, daemon=True).start()
    while (message := _read_message(sys.stdin.buffer)) is not None:
        if message[0] == FRAME:
            link.send(message[1])
    os._exit(0)


class BluetoothProcess:
    """The app's side: starts the Bluetooth process and talks to it. Same `send()` and
    `neighbours()` as a link, so the node does not know the difference."""

    def __init__(self, on_frame, command: list[str] | None = None):
        self.on_frame = on_frame
        self.status = "starting"
        self._neighbours = 0
        self._lock = threading.Lock()
        self._process = subprocess.Popen(command or bluetooth_command(), stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        threading.Thread(target=self._listen, name="bluetooth-reader", daemon=True).start()

    def send(self, frame: bytes) -> None:
        with self._lock:
            try:
                self._process.stdin.write(_message(FRAME, frame))
                self._process.stdin.flush()
            except (OSError, ValueError):  # the process has stopped; `status` says why
                try:
                    self._process.stdin.close()  # drops what could not be sent
                except OSError:
                    pass

    def neighbours(self) -> int:
        return self._neighbours

    def stop(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            self._process.wait(5)

    def _listen(self) -> None:
        while (message := _read_message(self._process.stdout)) is not None:
            kind, data = message
            if kind == FRAME:
                self.on_frame(data)
            elif kind == NEIGHBOURS:
                self._neighbours = int.from_bytes(data, "big")
            elif kind == STATUS:
                self.status = data.decode(errors="replace")
        code = self._process.wait()
        self._neighbours = 0
        if code == -signal.SIGABRT:
            self.status = ("off: macOS stopped Bluetooth because this program is not allowed to use it. "
                           "Run from VS Code or the packaged app, and allow Bluetooth in System Settings "
                           "> Privacy & Security > Bluetooth.")
        elif self.status in ("starting", "on"):
            self.status = f"off: Bluetooth stopped (exit code {code})"


if __name__ == "__main__":
    child_main()
