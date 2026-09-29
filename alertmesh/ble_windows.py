"""The peripheral side of the Bluetooth link on Windows: offer the iPhone app's service,
take writes, and notify subscribers, straight on WinRT.

Modelled on: alert-mesh/AlertMesh/Services/BLE/BLEService+LinkLayerPeripheralRole.swift
             (advertise, take writes, notify).

On a Mac this is done by `bless`. On Windows `bless` 0.3 cannot be used: it pins WinRT
packages that are no longer on PyPI, and its Windows part imports `pysetupdi`, which is
not on PyPI at all. It also waits for advertising to start by blocking the asyncio loop,
which would stop scanning and sending too. This module does the same few things with the
WinRT packages `bleak` already installs.

Without this side, an iPhone whose app is in the background never links to a Windows
laptop: iOS hides the service of a background app from the laptop's scan, and only an
iPhone can connect to a laptop that offers the service.

WinRT calls the write and subscription handlers on its own threads. Writes are passed to
the link's asyncio loop, answered there, then handed to `on_write`.

This is free and unencumbered software released into the public domain.
"""
import asyncio
from uuid import UUID

# Status values of GattServiceProviderAdvertisementStatus: STARTED, and (newer Windows)
# STARTED_WITHOUT_ALL_ADVERTISEMENT_DATA, which still means devices can connect.
_ADVERTISING = (2, 4)
ADVERTISE_TIMEOUT_S = 10.0


class Peripheral:
    """One service with one characteristic (write, write without response, notify).

    `on_write(data)` gets the bytes of every write from a connected device.
    """

    def __init__(self, service_uuid: str, characteristic_uuid: str, on_write):
        self.service_uuid = service_uuid
        self.characteristic_uuid = characteristic_uuid
        self.on_write = on_write
        self._loop: asyncio.AbstractEventLoop | None = None
        self._provider = None
        self._characteristic = None
        self._tokens = []  # kept, or the handlers can be dropped

    async def start(self) -> None:
        """Offer the service and start advertising it. Raises if Windows refuses."""
        from winrt.windows.devices.bluetooth.genericattributeprofile import (
            GattCharacteristicProperties, GattLocalCharacteristicParameters, GattProtectionLevel,
            GattServiceProvider, GattServiceProviderAdvertisingParameters,
        )

        self._loop = asyncio.get_running_loop()
        result = await GattServiceProvider.create_async(UUID(self.service_uuid))
        if result.service_provider is None:
            raise RuntimeError(f"Windows would not offer the service (error {result.error})")
        self._provider = result.service_provider

        parameters = GattLocalCharacteristicParameters()
        parameters.characteristic_properties = (GattCharacteristicProperties.WRITE
                                                | GattCharacteristicProperties.WRITE_WITHOUT_RESPONSE
                                                | GattCharacteristicProperties.NOTIFY)
        parameters.write_protection_level = GattProtectionLevel.PLAIN
        parameters.read_protection_level = GattProtectionLevel.PLAIN
        made = await self._provider.service.create_characteristic_async(UUID(self.characteristic_uuid), parameters)
        if made.characteristic is None:
            raise RuntimeError(f"Windows would not make the characteristic (error {made.error})")
        self._characteristic = made.characteristic
        self._tokens.append(self._characteristic.add_write_requested(self._write_requested))

        advertising = GattServiceProviderAdvertisingParameters()
        advertising.is_connectable = True
        advertising.is_discoverable = True
        self._provider.start_advertising_with_parameters(advertising)
        # Status changes arrive on another thread; looking every 50 ms keeps the loop free.
        for _ in range(int(ADVERTISE_TIMEOUT_S / 0.05)):
            if int(self._provider.advertisement_status) in _ADVERTISING:
                return
            await asyncio.sleep(0.05)
        raise RuntimeError(f"advertising did not start (status {int(self._provider.advertisement_status)})")

    def stop(self) -> None:
        if self._provider is not None:
            self._provider.stop_advertising()

    # --- Writes ---

    def _write_requested(self, _sender, args) -> None:
        """On a WinRT thread: hold the request open and answer it on the link's loop."""
        deferral = args.get_deferral()
        asyncio.run_coroutine_threadsafe(self._take_write(args, deferral), self._loop)

    async def _take_write(self, args, deferral) -> None:
        from winrt.windows.devices.bluetooth.genericattributeprofile import GattWriteOption

        data = b""
        try:
            request = await args.get_request_async()
            if request is not None:
                data = bytes(request.value) if request.value is not None else b""
                if request.option == GattWriteOption.WRITE_WITH_RESPONSE:
                    request.respond()
        finally:
            deferral.complete()
        if data:
            self.on_write(data)

    # --- Subscribers and notifications ---

    def _clients(self) -> list:
        if self._characteristic is None:
            return []
        return list(self._characteristic.subscribed_clients or [])

    def subscribers(self) -> set[str]:
        """The devices subscribed to our notifications, by Windows' device ID."""
        return {client.session.device_id.id for client in self._clients()}

    async def notify(self, split) -> int:
        """Send a packet to every subscriber, cut by `split(limit)` into pieces each one's
        link carries (Windows says how much, per device). Returns how many took it all."""
        from winrt.windows.devices.bluetooth.genericattributeprofile import GattCommunicationStatus
        from winrt.windows.storage.streams import Buffer

        delivered = 0
        for client in self._clients():
            ok = True
            for piece in split(max(int(client.max_notification_size or 0), 20)):
                buffer = Buffer(len(piece))
                buffer.length = buffer.capacity
                with memoryview(buffer) as view:
                    view[:] = piece
                try:
                    result = await self._characteristic.notify_value_for_subscribed_client_async(buffer, client)
                except OSError:
                    ok = False
                    break
                if result is None or result.status != GattCommunicationStatus.SUCCESS:
                    ok = False
                    break
            delivered += ok
        return delivered
