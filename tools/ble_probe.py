"""Bluetooth trial: can this computer both be found and find others?

    python3 tools/ble_probe.py            (scan for 15 seconds)
    python3 tools/ble_probe.py 60         (scan for 60 seconds)

Does the two things the phone app's Bluetooth link needs:
1. Advertises the Alert Mesh service, with one characteristic other laptops can write
   messages to (the `bless` library). Anything written to it is printed.
2. Scans for nearby Bluetooth devices (the `bleak` library), and says which ones
   advertise the Alert Mesh service, that is, other laptops running this probe or the
   phone app.

Run it on two laptops a few metres apart: each should list the other under "Alert Mesh
laptops", and each writes a hello to the other. One laptop alone only checks that
advertising starts and that scanning finds something.

The first run asks for Bluetooth permission for the program that runs Python
(Terminal, VS Code, ...). If it is refused, allow it in System Settings > Privacy &
Security > Bluetooth, then run again.

This is free and unencumbered software released into the public domain.
"""
import asyncio
import platform
import sys
from pathlib import Path

from bleak import BleakClient, BleakScanner
from bless import (
    BlessServer,
    GATTAttributePermissions,
    GATTCharacteristicProperties,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from alertmesh.ble import INBOX_UUID, SERVICE_UUID  # noqa: E402


def on_write(characteristic, value: bytearray) -> None:
    print(f"  received {len(value)} bytes: {bytes(value)!r}")


async def advertise() -> BlessServer:
    server = BlessServer(name="AlertMesh")
    server.read_request_func = lambda characteristic, **_: characteristic.value
    server.write_request_func = on_write
    await server.add_new_service(SERVICE_UUID)
    await server.add_new_characteristic(
        SERVICE_UUID,
        INBOX_UUID,
        GATTCharacteristicProperties.write,
        None,
        GATTAttributePermissions.writeable,
    )
    await server.start()
    return server


async def main(seconds: float) -> int:
    print(f"{platform.system()} {platform.release()}, Python {platform.python_version()}")
    print("1. Advertising the Alert Mesh service")
    try:
        server = await advertise()
    except Exception as error:  # the library raises plain Exceptions
        print(f"   FAILED: {type(error).__name__}: {error}")
        return 1
    print(f"   advertising: {await server.is_advertising()}")

    print(f"2. Scanning for {seconds:g} seconds")
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    ours = [(device, adv) for device, adv in found.values()
            if SERVICE_UUID in [uuid.lower() for uuid in adv.service_uuids]]
    print(f"   {len(found)} Bluetooth devices nearby")
    print(f"   Alert Mesh laptops: {len(ours)}")
    for device, adv in ours:
        print(f"   - {device.address} signal {adv.rssi} dBm")
        try:
            async with BleakClient(device, timeout=15) as client:
                await client.write_gatt_char(INBOX_UUID, b"hello from " + platform.node().encode()[:40],
                                             response=True)
                print(f"     wrote a hello (link size {client.mtu_size} bytes)")
        except Exception as error:
            print(f"     could not write: {type(error).__name__}: {error}")

    print("3. Waiting 5 seconds for hellos from other laptops")
    await asyncio.sleep(5)
    await server.stop()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 15)))
