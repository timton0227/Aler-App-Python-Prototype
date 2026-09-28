"""Tests for alertmesh.ble, without a radio.

The radio itself is checked by hand with an iPhone and with two laptops (PROGRESS.md
16.10, README). These tests cover everything around it with stand-ins for the devices
and for the Bluetooth server: which devices are connected to, packets written whole or
in fragments sized to each link, notifications read back as a stream, notifying the
devices subscribed to us, and the separate Bluetooth process.
"""
import asyncio
import os
import sys
import time

import pytest

from alertmesh import ble, bitchat, node
from alertmesh.bitchat import MessageType, Packet
from alertmesh.chat import Identity

SERVICE = bitchat.service_uuid()
ME = Identity("Me")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def packet(size: int) -> bytes:
    return bitchat.encode(ME.sign_packet(Packet(MessageType.OFFICIAL_ALERT, ME.peer_id, 1, os.urandom(size), 7)))


class Device:
    def __init__(self, address):
        self.address = address


class Advert:
    def __init__(self, uuids=(), apple=False, rssi=-50):
        self.service_uuids = list(uuids)
        self.manufacturer_data = {ble.APPLE: b"\x10"} if apple else {}
        self.rssi = rssi


class Characteristic:
    def __init__(self, uuid):
        self.uuid = uuid


class Service:
    def __init__(self, *uuids):
        self.characteristics = [Characteristic(u) for u in uuids]


class FakeClient:
    """A device this laptop connects to: an iPhone with the app, unless told otherwise."""

    made = []

    def __init__(self, device, on_disconnect, ours=True, fail=False, mtu=104):
        self.device, self.on_disconnect, self.fail = device, on_disconnect, fail
        self.services = [Service(bitchat.CHARACTERISTIC_UUID.upper() if ours else "2a00")]
        self.mtu_size = mtu
        self.writes, self.notify, self.disconnected = [], None, False
        FakeClient.made.append(self)

    async def connect(self):
        if self.fail:
            raise OSError("out of range")

    async def start_notify(self, uuid, callback):
        assert uuid == bitchat.CHARACTERISTIC_UUID
        self.notify = callback

    async def write_gatt_char(self, uuid, data, response):
        assert uuid == bitchat.CHARACTERISTIC_UUID and response  # the iPhone answers every write
        self.writes.append(bytes(data))

    async def disconnect(self):
        self.disconnected = True


class FakeServer:
    """Our own Bluetooth server: remembers every notification sent, and can be full."""

    def __init__(self, subscribed=(), full_for=0):
        self.characteristic = type("C", (), {"value": None})()
        self.peripheral_manager_delegate = type("D", (), {"_central_subscriptions": {c: [] for c in subscribed}})()
        self.full_for, self.sent = full_for, []

    def get_characteristic(self, uuid):
        return self.characteristic

    def update_value(self, service, uuid):
        if self.full_for:
            self.full_for -= 1
            return False
        self.sent.append(bytes(self.characteristic.value))
        return True


@pytest.fixture(autouse=True)
def fresh_fakes():
    FakeClient.made = []


def link_with(factory=FakeClient, clock=None, got=None, links=None):
    return ble.BleLink((got if got is not None else []).append, client_factory=factory, clock=clock or Clock(),
                       on_link=lambda: links.append(1) if links is not None else None)


def whole(writes: list[bytes]) -> bytes | None:
    """The packet a list of writes carries: itself, or its fragments put back together."""
    if len(writes) == 1:
        return writes[0]
    assembler = bitchat.FragmentAssembler(time.monotonic)
    results = [assembler.add(bitchat.decode(w)) for w in writes]
    return results[-1]


# --- Which devices


def test_devices_offering_the_service_and_close_apple_devices_are_kept():
    link = link_with()
    link.seen(Device("iphone"), Advert([SERVICE.upper()]))
    link.seen(Device("background"), Advert(apple=True, rssi=-40))
    link.seen(Device("far apple"), Advert(apple=True, rssi=-80))
    link.seen(Device("headphones"), Advert(["0000180f-0000-1000-8000-00805f9b34fb"]))
    assert set(link._devices) == {"iphone", "background"}


def test_a_device_is_connected_to_subscribed_and_greeted():
    links = []
    link = link_with(links=links)
    link.seen(Device("iphone"), Advert([SERVICE]))
    assert asyncio.run(link.connect_some()) == 1
    (client,) = FakeClient.made
    assert client.notify is not None and link.neighbours() == 1 and links == [1]
    assert asyncio.run(link.connect_some()) == 0  # already connected


def test_an_apple_device_without_the_app_is_left_alone():
    clock = Clock()
    link = link_with(lambda d, cb: FakeClient(d, cb, ours=False), clock)
    link.seen(Device("watch"), Advert(apple=True))
    assert asyncio.run(link.connect_some()) == 0
    assert FakeClient.made[0].disconnected and link.neighbours() == 0
    clock.now += ble.NOT_OURS_S - 1
    link.seen(Device("watch"), Advert(apple=True))
    asyncio.run(link.connect_some())
    assert len(FakeClient.made) == 1


def test_at_most_six_connections():
    link = link_with()
    for i in range(9):
        link.seen(Device(f"d{i}"), Advert([SERVICE]))
    asyncio.run(link.connect_some())
    assert link.neighbours() == ble.MAX_CONNECTIONS


def test_devices_offering_the_service_come_before_ones_being_checked():
    link = link_with()
    for i in range(6):
        link.seen(Device(f"apple{i}"), Advert(apple=True))
    link.seen(Device("iphone"), Advert([SERVICE]))
    asyncio.run(link.connect_some())
    assert FakeClient.made[0].device.address == "iphone"


def test_a_device_that_failed_is_left_alone_for_a_while():
    clock = Clock()
    link = link_with(lambda d, cb: FakeClient(d, cb, fail=True), clock)
    link.seen(Device("A"), Advert([SERVICE]))
    asyncio.run(link.connect_some())
    asyncio.run(link.connect_some())
    assert len(FakeClient.made) == 1
    clock.now += ble.RETRY_AFTER_S
    link.seen(Device("A"), Advert([SERVICE]))
    asyncio.run(link.connect_some())
    assert len(FakeClient.made) == 2


def test_an_apple_device_that_does_not_answer_is_not_tried_again_soon():
    clock = Clock()
    link = link_with(lambda d, cb: FakeClient(d, cb, fail=True), clock)
    link.seen(Device("mac"), Advert(apple=True))
    asyncio.run(link.connect_some())
    clock.now += ble.RETRY_AFTER_S
    link.seen(Device("mac"), Advert(apple=True))
    asyncio.run(link.connect_some())
    assert len(FakeClient.made) == 1


def test_several_devices_are_tried_at_once():
    started = []

    class Slow(FakeClient):
        async def connect(self):
            started.append(self.device.address)
            await asyncio.sleep(0.05)
            assert len(started) == 3  # all three began before any finished

    link = link_with(Slow)
    for name in ("A", "B", "C"):
        link.seen(Device(name), Advert([SERVICE]))
    assert asyncio.run(link.connect_some()) == 3


def test_devices_out_of_range_are_not_connected_to():
    clock = Clock()
    link = link_with(clock=clock)
    link.seen(Device("A"), Advert([SERVICE]))
    clock.now += ble.DEVICE_GONE_S + 1
    assert asyncio.run(link.connect_some()) == 0


def test_a_lost_connection_is_forgotten():
    link = link_with()
    link.seen(Device("A"), Advert([SERVICE]))
    asyncio.run(link.connect_some())
    FakeClient.made[0].on_disconnect(None)
    assert link.neighbours() == 0


# --- Sending


def test_a_packet_that_fits_goes_whole_to_every_connection():
    link = link_with()
    for name in ("A", "B"):
        link.seen(Device(name), Advert([SERVICE]))
    asyncio.run(link.connect_some())
    raw = packet(5)  # 91 bytes: fits a 104-byte link
    assert asyncio.run(link.deliver(raw)) == 2
    assert [c.writes for c in FakeClient.made] == [[raw], [raw]]


@pytest.mark.parametrize("mtu", [104, 185, 517])
def test_a_big_packet_is_cut_into_fragments_sized_to_each_link(mtu):
    link = link_with(lambda d, cb: FakeClient(d, cb, mtu=mtu))
    link.seen(Device("A"), Advert([SERVICE]))
    asyncio.run(link.connect_some())
    raw = packet(600)
    asyncio.run(link.deliver(raw))
    (client,) = FakeClient.made
    assert whole(client.writes) == raw
    assert (len(client.writes) > 1) == (len(raw) > mtu - 3)
    assert all(len(w) <= mtu - 3 for w in client.writes)
    assert all(bitchat.decode(w).type == MessageType.FRAGMENT for w in client.writes if len(client.writes) > 1)


def test_a_failed_write_drops_the_connection():
    link = link_with()
    link.seen(Device("A"), Advert([SERVICE]))
    asyncio.run(link.connect_some())

    async def broken(*_, **__):
        raise OSError("gone")

    FakeClient.made[0].write_gatt_char = broken
    assert asyncio.run(link.deliver(packet(10))) == 0
    assert link.neighbours() == 0


def test_devices_subscribed_to_us_are_notified_in_pieces_they_can_take():
    link = link_with()
    link._server = FakeServer(subscribed=["central-1"])
    link.check_centrals()
    raw = packet(400)
    assert asyncio.run(link.deliver(raw)) == 1
    assert all(len(n) <= ble.NOTIFY_LIMIT for n in link._server.sent)
    assert whole(link._server.sent) == raw


def test_a_full_radio_queue_is_waited_for():
    link = link_with()
    link._server = FakeServer(subscribed=["central-1"], full_for=3)
    link.check_centrals()
    raw = packet(10)
    asyncio.run(link.deliver(raw))
    assert link._server.sent == [raw]


def test_a_new_subscriber_is_greeted_and_counted():
    links = []
    link = link_with(links=links)
    link._server = FakeServer(subscribed=["central-1"])
    link.check_centrals()
    link.check_centrals()
    assert links == [1] and link.neighbours() == 1
    link._server.peripheral_manager_delegate._central_subscriptions = {}
    link.check_centrals()
    assert link.neighbours() == 0


def test_without_blesss_private_field_the_link_still_works():
    link = link_with()
    link._server = type("S", (), {})()
    link.check_centrals()
    assert link.neighbours() == 0


# --- Receiving


def test_notifications_are_read_as_a_stream_of_packets():
    got = []
    link = link_with(got=got)
    link.seen(Device("A"), Advert([SERVICE]))
    asyncio.run(link.connect_some())
    one, two = packet(30), packet(50)
    stream = one + two
    notify = FakeClient.made[0].notify
    for i in range(0, len(stream), 40):
        notify(None, bytearray(stream[i:i + 40]))
    assert got == [one, two]


def test_a_write_to_our_characteristic_is_a_packet():
    got = []
    link = link_with(got=got)
    raw = packet(30)
    link.received(raw)
    link.received(b"")
    assert got == [raw]


def test_on_the_smallest_link_fragments_are_never_cut_below_64_bytes():
    """BLEOutboundPacketPolicy: chunk = max(64, link - 42). A write that is answered may
    be longer than the link; the system sends it in parts."""
    raw = packet(node.MAX_PACKET_BYTES - 200)
    fragments = ble.pieces(raw, ble.MIN_WRITE)
    assert whole(fragments) == raw
    assert {len(bitchat.fragment_header(bitchat.decode(f)).data) for f in fragments[:-1]} == {bitchat.MIN_CHUNK}


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


def test_the_process_says_when_a_device_links_up():
    links = []
    script = ("import sys\nfrom alertmesh import ble\nsys.stdout.buffer.write(ble._message(ble.LINK, b'') * 2)\n"
              "sys.stdout.buffer.flush()\nsys.stdin.buffer.read()")
    process = ble.BluetoothProcess(lambda f: None, [sys.executable, "-c", script], on_link=lambda: links.append(1))
    try:
        assert wait_for(lambda: links == [1, 1])
    finally:
        process.stop()
