"""Bluetooth check with an iPhone: does the iPhone app see this laptop, and this laptop
the iPhone?

    python3 tools/ble_probe.py              (runs 60 seconds)
    python3 tools/ble_probe.py 180          (runs 3 minutes)
    python3 tools/ble_probe.py --warning    (also sends a TEST warning, then cancels it)

Needs an iPhone nearby with the Alert Mesh app open (a Debug build: it uses the
"testnet" Bluetooth service; ALERTMESH_BLE_NETWORK=release for a Release build).

The probe connects to the iPhone as the iPhone app would connect to another iPhone
(the `bleak` library), in the iPhone app's own packet format (alertmesh/bitchat.py):
1. It finds devices advertising the iPhone app's service, connects, and subscribes.
2. It sends a signed announce (who this laptop is), then a short message and a long
   one (over 100 bytes, so it is compressed; cut into fragments if the link is small).
   With --warning, a TEST warning signed with the development key, cancelled 20 s later.
3. It prints everything the iPhone sends, checking each signature: its announce, its
   messages, warnings and calls for help.

What to look for on the iPhone: this laptop's name among the people nearby, and the two
messages in the public chat. The probe uses the phone app's saved nickname and keys.

On a Mac, run it from VS Code's terminal: macOS stops any program that uses Bluetooth
unless the app running it says why, and Terminal and iTerm do not.

This is free and unencumbered software released into the public domain.
"""
import asyncio
import platform
import sys
import time
from pathlib import Path

from bleak import BleakClient, BleakScanner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from alertmesh import bitchat, phone, reports, wire  # noqa: E402
from alertmesh.bitchat import MessageType, Packet  # noqa: E402
from alertmesh.chat import Identity  # noqa: E402
from alertmesh.signer import OfficialAlertSigner, WarningDraft, new_alert_id  # noqa: E402

ANNOUNCE_EVERY_S = 10
SCAN_S = 10
MAX_DEVICES = 3
SHORT = "Hello from a laptop running the Alert Mesh prototype"
LONG = ("This is a longer message from the laptop, sent to check that compressed packets work: "
        "flood water is over the causeway, take the high road north to the school instead.")


def now_ms() -> int:
    return int(time.time() * 1000)


def stamp() -> str:
    return time.strftime("%H:%M:%S")


class Probe:
    def __init__(self, identity: Identity):
        self.me = identity
        self.keys: dict[bytes, bytes] = {}  # peer ID -> signing key, from verified announces
        self.names: dict[bytes, str] = {}
        self.seen: set[str] = set()
        self.assembler = bitchat.FragmentAssembler(time.monotonic)

    # --- Sending ---

    def packet(self, kind: int, payload: bytes, ttl: int = 7) -> Packet:
        return self.me.sign_packet(Packet(kind, self.me.peer_id, now_ms(), payload, ttl))

    def announce(self) -> Packet:
        return self.packet(MessageType.ANNOUNCE, bitchat.encode_announcement(bitchat.Announcement(
            self.me.nickname, self.me.chat_key, self.me.signing_key, laptop=True)))

    async def send(self, client: BleakClient, packet: Packet, label: str) -> None:
        limit = max(client.mtu_size - 3, 20)
        whole = bitchat.encode(packet)
        if whole is None:
            print(f"{stamp()}  could not encode {label}")
            return
        pieces = [whole] if len(whole) <= limit else [
            bitchat.encode(f) for f in bitchat.split(packet, bitchat.chunk_size_for(limit))]
        for piece in pieces:
            await client.write_gatt_char(bitchat.CHARACTERISTIC_UUID, piece, response=True)
            if len(pieces) > 1:
                await asyncio.sleep(0.03)
        how = f"{len(pieces)} fragments" if len(pieces) > 1 else "whole"
        print(f"{stamp()}  sent {label} ({len(whole)} bytes, {how}, link takes {limit})")

    # --- Receiving ---

    def take(self, raw: bytes, via: str) -> None:
        p = bitchat.decode(raw)
        if p is None:
            print(f"{stamp()}  {via}: {len(raw)} bytes that are not a packet")
            return
        if p.type == MessageType.FRAGMENT:
            whole = self.assembler.add(p)
            if whole is not None:
                self.take(whole, via + " (from fragments)")
            return
        key = bitchat.dedup_key(p)
        if key in self.seen:
            return
        self.seen.add(key)
        age = (now_ms() - p.timestamp) / 1000
        who = self.names.get(p.sender_id, p.sender_id.hex())
        head = f"{stamp()}  {via}: from {who}, TTL {p.ttl}, {age:+.1f} s old"
        if p.type == MessageType.ANNOUNCE:
            a = bitchat.decode_announcement(p.payload)
            ok = (a is not None and bitchat.peer_id(a.noise_key) == p.sender_id
                  and bitchat.verify(p, a.signing_key))
            if ok:
                self.keys[p.sender_id], self.names[p.sender_id] = a.signing_key, a.nickname
            kind = "laptop" if a and a.laptop else "iPhone"
            print(f"{head}\n    ANNOUNCE {a.nickname if a else '?'!r} ({kind}), signature "
                  f"{'OK' if ok else 'NOT OK'}")
        elif p.type == MessageType.MESSAGE:
            key_ = self.keys.get(p.sender_id)
            check = "OK" if key_ and bitchat.verify(p, key_) else ("no announce yet" if not key_ else "NOT OK")
            print(f"{head}\n    MESSAGE {p.payload.decode(errors='replace')!r}, signature {check}"
                  + (", came compressed" if p.compressed else ""))
        elif p.type == MessageType.OFFICIAL_ALERT:
            item = wire.decode(p.payload)
            ok = item is not None and wire.verify_pinned(item)
            what = getattr(item, "headline", "cancellation")
            print(f"{head}\n    WARNING {what!r}, publisher signature {'OK' if ok else 'NOT OK'}")
        elif p.type == MessageType.COMMUNITY_REPORT:
            r = reports.decode(p.payload)
            ok = r is not None and reports.verify(r)
            print(f"{head}\n    REPORT {r.kind.name if r else '?'} {r.note if r else ''!r}, "
                  f"author signature {'OK' if ok else 'NOT OK'}")
        elif p.type == MessageType.REQUEST_SYNC:
            print(f"{head}\n    CATCH-UP REQUEST (the probe does not answer)")
        else:
            name = MessageType(p.type).name if p.type in MessageType._value2member_map_ else hex(p.type)
            print(f"{head}\n    {name}, {len(p.payload)} bytes (not handled by the probe)")


async def run(seconds: float, send_warning: bool) -> int:
    profile = phone.Profile.load(phone.home_folder())
    me = Identity(profile.nickname, profile.seed)
    probe = Probe(me)
    service = bitchat.service_uuid()
    print(f"{platform.system()} {platform.release()}, Python {platform.python_version()}")
    print(f"This laptop: {me.nickname!r}, peer ID {me.peer_id.hex()}; service {service}")
    print(f"Compression matches Apple's: {bitchat.APPLE_COMPRESSION_OK}")
    print(f"Scanning {SCAN_S} s for devices with the Alert Mesh app open ...")

    found = await BleakScanner.discover(timeout=SCAN_S, return_adv=True, service_uuids=[service])
    devices = sorted(found.values(), key=lambda d: -d[1].rssi)[:MAX_DEVICES]
    if not devices:
        print("None found. Is the iPhone app open, with Bluetooth on, and a Debug build?")
        return 1
    clients = []
    for device, adv in devices:
        print(f"Connecting to {device.address} ({adv.rssi} dBm) ...")
        client = BleakClient(device, timeout=15)
        try:
            await client.connect()
            stream = bitchat.NotificationStream(time.monotonic)
            label = device.address[-5:]

            def on_notify(_, data, stream=stream, label=label):
                for frame in stream.append(bytes(data)):
                    probe.take(frame, f"notify {label}")

            await client.start_notify(bitchat.CHARACTERISTIC_UUID, on_notify)
            clients.append(client)
            print(f"  connected, subscribed, link takes {client.mtu_size - 3} bytes")
        except Exception as error:
            print(f"  could not connect: {type(error).__name__}: {error}")
    if not clients:
        return 1

    async def to_all(packet: Packet, label: str) -> None:
        for client in clients:
            try:
                await probe.send(client, packet, label)
            except Exception as error:
                print(f"{stamp()}  could not send {label}: {type(error).__name__}: {error}")

    await to_all(probe.announce(), "announce")
    await asyncio.sleep(2)
    await to_all(probe.packet(MessageType.MESSAGE, SHORT.encode()), "short message")
    await asyncio.sleep(1)
    await to_all(probe.packet(MessageType.MESSAGE, LONG.encode()), "long message")
    alert = None
    if send_warning:
        await asyncio.sleep(1)
        alert = OfficialAlertSigner().sign(WarningDraft(
            headline="TEST - Alert Mesh laptop Bluetooth check", action_text="No action needed. Cancelled soon.",
            duration_hours=1, area_cells=["qvqj"]), new_alert_id(), now_ms())
        await to_all(probe.packet(MessageType.OFFICIAL_ALERT, wire.encode(alert)), "TEST warning")

    started = time.monotonic()
    last_announce = started
    cancelled = False
    while time.monotonic() - started < seconds:
        await asyncio.sleep(1)
        if time.monotonic() - last_announce >= ANNOUNCE_EVERY_S:
            last_announce = time.monotonic()
            await to_all(probe.announce(), "announce")
        if alert is not None and not cancelled and time.monotonic() - started > 20:
            cancelled = True
            cancel = OfficialAlertSigner().cancel(alert.alert_id, now_ms())
            await to_all(probe.packet(MessageType.OFFICIAL_ALERT, wire.encode(cancel)), "cancellation")
    for client in clients:
        try:
            await client.disconnect()
        except Exception:
            pass
    print("Done.")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(asyncio.run(run(float(args[0]) if args else 60, "--warning" in sys.argv)))
