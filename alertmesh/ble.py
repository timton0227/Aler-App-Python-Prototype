"""The Bluetooth link: the only part of the phone app that touches the radio.

Modelled on: alert-mesh/AlertMesh/Services/BLE/BLEService+LinkLayerCentralRole.swift
             (scan, connect, subscribe, write), BLEService+LinkLayerPeripheralRole.swift
             (advertise, take writes, notify), BLEOutboundLinkPlanner.swift and
             BLEOutboundPacketPolicy.swift (fragments sized to each link).

Since Phase 16 the link uses the iPhone app's own service and characteristic, so
laptops and iPhones running Alert Mesh find each other. Each laptop does both jobs,
like the iPhone app:
- **as a central** (library `bleak`) it connects to devices nearby that offer the
  service, up to 6 at once, subscribes to their notifications, and writes each packet
  to them. An iPhone app in the background hides its service from a Mac's scan (iOS
  keeps it in an "overflow" area only iPhones read), so Apple devices this close are
  connected to once and kept if they have the characteristic;
- **as a peripheral** (library `bless`) it offers the service: devices connected to it
  write packets to the characteristic, and it sends packets to those subscribed by
  notifying.

Each write or notification carries one whole packet, as on the iPhone. A packet too big
for a link is cut into fragments first (bitchat.split), sized to that link: a
connection says how much one write carries; a notification is assumed to carry 182
bytes (bless does not say). Notifications that arrive are read as one stream and cut
back into packets (bitchat.NotificationStream).

Bluetooth runs in a separate small process (`BluetoothProcess`), because on a Mac the
program that runs Python needs Bluetooth permission, and macOS stops any program whose
app does not say why it uses Bluetooth. If that happens, only the Bluetooth process
stops, and the phone app says why instead of vanishing. The two talk through the
child's standard input and output. Inside the child, `BleLink` runs the radio on an
asyncio loop.

This is free and unencumbered software released into the public domain.
"""
import asyncio
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque

from alertmesh import bitchat

# The smallest write every Bluetooth LE device must take (23-byte link, minus 3).
MIN_WRITE = 20
# What one notification is assumed to carry: bless does not say per device.
NOTIFY_LIMIT = 182
# A notification the radio has no room for yet is tried again this often, this many
# times (BLEService: 25 ms, 80 tries).
NOTIFY_RETRY_S = 0.025
NOTIFY_TRIES = 80
MAX_CONNECTIONS = 6
# Apple's Bluetooth company ID, and how close an Apple device that does not show the
# service must be to be checked by connecting (an iPhone app in the background).
APPLE = 76
CLOSE_DBM = -60
# A device not heard advertising for this long is out of range.
DEVICE_GONE_S = 30.0
CONNECT_TIMEOUT_S = 10.0
# After a device fails to connect, leave it alone this long before trying again.
RETRY_AFTER_S = 15.0
# A device checked and found not to run Alert Mesh is not checked again for this long.
NOT_OURS_S = 300.0
CONNECT_EVERY_S = 1.0


# --- The link -----------------------------------------------------------------


def _bleak_client(device, on_disconnect):
    from bleak import BleakClient

    return BleakClient(device, timeout=CONNECT_TIMEOUT_S, disconnected_callback=on_disconnect)


class _Connection:
    """One device this laptop connected to: its client, and its notifications as a stream."""

    def __init__(self, client, clock):
        self.client = client
        self.stream = bitchat.NotificationStream(clock)

    @property
    def limit(self) -> int:
        return max((self.client.mtu_size or 23) - 3, MIN_WRITE)


def pieces(raw: bytes, limit: int) -> list[bytes]:
    """A packet as the writes one link can carry: whole, or in fragments sized to the link."""
    if len(raw) <= limit:
        return [raw]
    packet = bitchat.decode(raw)
    if packet is None:
        return []
    return [encoded for fragment in bitchat.split(packet, bitchat.chunk_size_for(limit))
            if (encoded := bitchat.encode(fragment)) is not None]


class BleLink:
    """Advertise, scan, connect, write and notify, on a background thread.

    `on_frame` gets every whole packet that arrives; `on_link` is told when a new device
    links up, so the node can announce at once. `status` says in plain words what
    Bluetooth is doing, for the page to show. `client_factory` makes the connection to
    one device; tests pass a fake, and a fake `server` for the peripheral side.
    """

    def __init__(self, on_frame, name: str = "AlertMesh", client_factory=_bleak_client, clock=time.monotonic,
                 on_link=None):
        self.on_frame = on_frame
        self.on_link = on_link or (lambda: None)
        self.name = name
        self.client_factory = client_factory
        self.clock = clock
        self.status = "starting"
        self.service = bitchat.service_uuid()
        self._devices: dict[str, tuple[object, float, bool, int]] = {}  # address -> (device, seen, advertises, rssi)
        self._trying: set[str] = set()
        self.events: deque[str] = deque(maxlen=50)  # what the link did lately, for a look by hand
        self._connections: dict[str, _Connection] = {}
        self._failed: dict[str, float] = {}  # address -> when it last failed
        self._not_ours: dict[str, float] = {}  # address -> when it was found not to run Alert Mesh
        self._centrals: set[str] = set()  # devices subscribed to our notifications
        self._server = None
        self.advertising: bool | str = False  # True once devices can connect to this laptop
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None

    # --- Called from any thread ---

    def start(self) -> "BleLink":
        threading.Thread(target=self._run, name="bluetooth", daemon=True).start()
        return self

    def send(self, raw: bytes) -> None:
        if self._loop is not None and self._queue is not None:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, raw)

    def neighbours(self) -> int:
        """Devices linked right now, either way (one linked both ways may count twice)."""
        with self._lock:
            return len(self._connections) + len(self._centrals)

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
        scanner = BleakScanner(self.seen)
        await scanner.start()
        self.status = "on"
        # Offering the service can take a while to start; finding and connecting to
        # devices does not wait for it.
        asyncio.create_task(self._keep_advertising())
        asyncio.create_task(self._keep_connecting())
        while True:
            await self.deliver(await self._queue.get())

    async def _keep_advertising(self) -> None:
        try:
            await self._advertise()
            self.advertising = True
        except Exception as error:  # still a central: it connects to devices, they cannot connect to it
            self.advertising = f"not offering the service: {error}"

    async def _advertise(self) -> None:
        from bless import BlessServer, GATTAttributePermissions, GATTCharacteristicProperties

        server = BlessServer(name=self.name)
        server.read_request_func = lambda characteristic, **_: characteristic.value
        server.write_request_func = lambda characteristic, value: self.received(bytes(value))
        await server.add_new_service(self.service)
        await server.add_new_characteristic(
            self.service, bitchat.CHARACTERISTIC_UUID,
            GATTCharacteristicProperties.read | GATTCharacteristicProperties.write
            | GATTCharacteristicProperties.write_without_response | GATTCharacteristicProperties.notify,
            None, GATTAttributePermissions.readable | GATTAttributePermissions.writeable,
        )
        await server.start()
        self._server = server  # kept, or advertising stops when it is collected

    async def _keep_connecting(self) -> None:
        while True:
            try:
                await self.connect_some()
                self.check_centrals()
            except Exception:  # one bad device must not stop the others
                pass
            await asyncio.sleep(CONNECT_EVERY_S)

    def seen(self, device, advertisement) -> None:
        """A device heard advertising: one offering the service, or an Apple device close
        enough to check (its app may be in the background)."""
        uuids = [u.lower() for u in (getattr(advertisement, "service_uuids", None) or [])]
        advertises = self.service in uuids
        close_apple = (APPLE in (getattr(advertisement, "manufacturer_data", None) or {})
                       and (getattr(advertisement, "rssi", None) or -127) > CLOSE_DBM)
        if advertises or close_apple:
            with self._lock:
                self._devices[device.address] = (device, self.clock(), advertises,
                                                  getattr(advertisement, "rssi", None) or -127)

    async def connect_some(self) -> int:
        """Connect to devices in range not connected yet, up to 6 in all, several at a time
        (a device that does not answer takes seconds to give up on). Returns how many
        linked up."""
        now = self.clock()
        with self._lock:
            targets = [(address, device, advertises, rssi)
                       for address, (device, seen, advertises, rssi) in self._devices.items()
                       if now - seen <= DEVICE_GONE_S and address not in self._connections
                       and address not in self._trying
                       and now - self._failed.get(address, -RETRY_AFTER_S) >= RETRY_AFTER_S
                       and now - self._not_ours.get(address, -NOT_OURS_S) >= NOT_OURS_S]
            room = MAX_CONNECTIONS - len(self._connections) - len(self._trying)
        # Devices that advertise the service first, then the closest others.
        targets.sort(key=lambda t: (not t[2], -t[3]))
        results = await asyncio.gather(*(self._connect(address, device, advertises, now)
                                         for address, device, advertises, _ in targets[:max(room, 0)]))
        return sum(results)

    async def _connect(self, address: str, device, advertises: bool, now: float) -> bool:
        self._trying.add(address)
        client = self.client_factory(device, lambda _, address=address: self._lost(address))
        try:
            await client.connect()
            characteristics = [c.uuid.lower() for s in client.services for c in s.characteristics]
            if bitchat.CHARACTERISTIC_UUID not in characteristics:
                self._not_ours[address] = now
                self.events.append(f"{address[-5:]}: not running Alert Mesh")
                await client.disconnect()
                return False
            connection = _Connection(client, self.clock)
            await client.start_notify(bitchat.CHARACTERISTIC_UUID,
                                      lambda _, data, c=connection: self._notified(c, bytes(data)))
        except Exception as error:  # out of range, turned off, or refused: try again later
            self._failed[address] = now
            if not advertises:
                self._not_ours[address] = now  # an Apple device being checked that does not answer: not soon
            self.events.append(f"{address[-5:]}: could not connect ({type(error).__name__})")
            return False
        finally:
            self._trying.discard(address)
        with self._lock:
            self._connections[address] = connection
        self.events.append(f"{address[-5:]}: linked, writes of {connection.limit} bytes")
        self.on_link()
        return True

    def check_centrals(self) -> None:
        """Devices subscribed to our notifications. bless keeps them in a private field;
        without it, the link still works but new subscribers are not greeted at once."""
        delegate = getattr(self._server, "peripheral_manager_delegate", None)
        subscribed = set(getattr(delegate, "_central_subscriptions", None) or {})
        with self._lock:
            new = subscribed - self._centrals
            self._centrals = subscribed
        if new:
            self.on_link()

    def _lost(self, address: str) -> None:
        with self._lock:
            self._connections.pop(address, None)

    def _notified(self, connection: _Connection, data: bytes) -> None:
        for packet in connection.stream.append(data):
            self.on_frame(packet)

    def received(self, data: bytes) -> None:
        """A packet written to our characteristic by a device connected to us."""
        if data:
            self.on_frame(data)

    async def deliver(self, raw: bytes) -> int:
        """Send one packet to every device linked, sized to each link. Returns how many took it."""
        with self._lock:
            connections = list(self._connections.items())
        delivered = 0
        for address, connection in connections:
            try:
                for piece in pieces(raw, connection.limit):
                    await connection.client.write_gatt_char(bitchat.CHARACTERISTIC_UUID, piece, response=True)
                delivered += 1
            except Exception:  # gone out of range: connect again when it is heard
                self._lost(address)
                self._failed[address] = self.clock()
        if self._server is not None and self._centrals:
            delivered += await self._notify(raw)
        return delivered

    async def _notify(self, raw: bytes) -> int:
        """Send a packet to every subscribed device by notifying, in pieces they can take."""
        characteristic = self._server.get_characteristic(bitchat.CHARACTERISTIC_UUID)
        for piece in pieces(raw, NOTIFY_LIMIT):
            characteristic.value = bytearray(piece)
            for _ in range(NOTIFY_TRIES):
                if self._server.update_value(self.service, bitchat.CHARACTERISTIC_UUID):
                    break
                await asyncio.sleep(NOTIFY_RETRY_S)  # the radio's queue is full: wait for room
            else:
                return 0
        return len(self._centrals)


# --- The Bluetooth process ----------------------------------------------------

# Messages between the app and its Bluetooth process: 1-byte type, 2-byte length, data.
# FRAME is a whole packet; LINK says a new device linked up.
FRAME, NEIGHBOURS, STATUS, LINK = b"F", b"N", b"S", b"L"
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
    """The Bluetooth process: packets in on standard input, packets and news out on
    standard output. Stops when the app closes its end."""
    out = sys.stdout.buffer
    out_lock = threading.Lock()

    def write(kind: bytes, data: bytes) -> None:
        with out_lock:
            out.write(_message(kind, data))
            out.flush()

    link = BleLink(lambda raw: write(FRAME, raw), name, on_link=lambda: write(LINK, b""))
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
    `neighbours()` as a link, so the node does not know the difference. `on_link` is
    told when a new device links up."""

    def __init__(self, on_frame, command: list[str] | None = None, on_link=None):
        self.on_frame = on_frame
        self.on_link = on_link or (lambda: None)
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
            elif kind == LINK:
                self.on_link()
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
