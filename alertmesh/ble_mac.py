"""The peripheral side of the Bluetooth link on a Mac: who is subscribed, and notifying
each of them within its own limit, straight on CoreBluetooth.

Modelled on: alert-mesh/AlertMesh/Services/BLE/BLEService+LinkLayerPeripheralRole.swift
             (notify each subscribed central, sized to its maximumUpdateValueLength).

`bless` offers the service on a Mac, but it notifies every subscriber at once with one
value, so each notification had to fit an assumed 182 bytes, and it keeps subscribers
only in a private field. CoreBluetooth itself says both: the characteristic lists its
subscribed centrals, and each central how much one notification to it carries. This
module reads them from the server bless made, as `ble_windows.Peripheral` does on
Windows, so the link treats both systems the same way.

This is free and unencumbered software released into the public domain.
"""
import asyncio

from alertmesh.ble import MIN_WRITE, NOTIFY_RETRY_S, NOTIFY_TRIES


class Peripheral:
    """The bless server that offers the service, and its characteristic's subscribers.

    Raises if the server is not a CoreBluetooth one (the link then uses bless as it is).
    """

    def __init__(self, server, characteristic_uuid: str):
        self.server = server  # kept, or advertising stops when it is collected
        self._manager = server.peripheral_manager_delegate.peripheral_manager
        self._characteristic = server.get_characteristic(characteristic_uuid).obj
        if not hasattr(self._characteristic, "subscribedCentrals"):
            raise TypeError("not a CoreBluetooth characteristic")

    def _centrals(self) -> list:
        return list(self._characteristic.subscribedCentrals() or [])

    def subscribers(self) -> set[str]:
        """The devices subscribed to our notifications, by CoreBluetooth's identifier."""
        return {central.identifier().UUIDString() for central in self._centrals()}

    async def notify(self, split) -> int:
        """Send a packet to every subscriber, cut by `split(limit)` into pieces each one's
        link carries. Returns how many took it all."""
        delivered = 0
        for central in self._centrals():
            ok = True
            for piece in split(max(int(central.maximumUpdateValueLength() or 0), MIN_WRITE)):
                for _ in range(NOTIFY_TRIES):
                    if self._manager.updateValue_forCharacteristic_onSubscribedCentrals_(
                            piece, self._characteristic, [central]):
                        break
                    await asyncio.sleep(NOTIFY_RETRY_S)  # the radio's queue is full: wait for room
                else:
                    ok = False
                    break
            delivered += ok
        return delivered
