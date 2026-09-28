"""This Mac's own position, from Location Services, in a process of its own.

Based on: alert-mesh/AlertMesh/AlertMesh/Services/LocationStateManager.swift, which
asks for permission once, then for one coarse fix at a time (`requestLocation`,
accuracy 100 m) rather than following the phone around.

Why a separate process, as for Bluetooth (alertmesh/ble.py): Location Services needs a
macOS run loop of its own, and macOS only asks for permission for a program that is
an app with its own words for the question. The packaged phone app is such an app, and
its location process is a second copy of it, so macOS asks once and remembers. A plain
`python` or `streamlit run` is not an app: macOS never asks, and the phone app falls
back to a pin or the town.

Messages between the app and its location process, as for Bluetooth (1-byte type,
2-byte length, data):
- P  a fix, as JSON {"lat", "lon", "accuracy", "at"} (the app turns it into a geohash
     at once, so raw coordinates go no further);
- S  status words;
- R  (app to process) take a fresh fix now.

This is free and unencumbered software released into the public domain.
"""
import importlib.util
import json
import os
import signal
import subprocess
import sys
import threading
import time

from alertmesh.ble import _message, _read_message
from alertmesh.position import Fix

FIX, STATUS, REFRESH = b"P", b"S", b"R"
# A laptop moves less than a phone: a fresh fix every 5 minutes, and whenever asked
# (the call for help asks as it opens).
REFRESH_EVERY_S = 5 * 60
# macOS asks the person at most once. With no answer after this long, the words say
# where to allow it.
PERMISSION_WAIT_S = 30

# CLAuthorizationStatus
NOT_DETERMINED, RESTRICTED, DENIED, AUTHORIZED_ALWAYS, AUTHORIZED_WHEN_IN_USE = range(5)

SETTINGS = "System Settings > Privacy & Security > Location Services"
NOT_HERE = "not on this computer: drop a pin instead"


def available() -> bool:
    """Location Services is a Mac's, through the pyobjc CoreLocation library."""
    return sys.platform == "darwin" and importlib.util.find_spec("CoreLocation") is not None


def status_words(services_on: bool, authorization: int, has_fix: bool, asked_s: float, failed: bool) -> str:
    """What the location switch shows under it. "on" only once there is a fix."""
    if not services_on:
        return f"off: Location Services is turned off ({SETTINGS})"
    if authorization in (RESTRICTED, DENIED):
        return f"off: not allowed. Allow Alert Mesh in {SETTINGS}"
    if authorization == NOT_DETERMINED:
        if asked_s < PERMISSION_WAIT_S:
            return "asking macOS for permission"
        return (f"off: macOS has not allowed it. Allow Alert Mesh in {SETTINGS} "
                "(only the packaged app can ask)")
    if has_fix:
        return "on"
    return "on, but no fix right now (is Wi-Fi on?)" if failed else "on, waiting for a first fix"


def location_command() -> list[str]:
    """How to start the location process. The packaged app is its own Python."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--location"]
    return [sys.executable, "-m", "alertmesh.location"]


def child_main() -> None:  # pragma: no cover - needs macOS Location Services; checked by hand
    """The location process: fixes and status words out on standard output, "take a
    fix now" in on standard input. Stops when the app closes its end."""
    import CoreLocation
    from Foundation import NSDate, NSObject, NSRunLoop

    out = sys.stdout.buffer
    out_lock = threading.Lock()
    state = {"fix": False, "failed": False, "wanted": True, "last_status": None}
    started = time.monotonic()

    def write(kind: bytes, data: bytes) -> None:
        with out_lock:
            out.write(_message(kind, data))
            out.flush()

    class Delegate(NSObject):
        def locationManager_didUpdateLocations_(self, manager, locations):
            reading = locations[-1]
            point = reading.coordinate()
            state["fix"], state["failed"] = True, False
            write(FIX, json.dumps({"lat": point.latitude, "lon": point.longitude,
                                   "accuracy": reading.horizontalAccuracy(),
                                   "at": int(reading.timestamp().timeIntervalSince1970() * 1000)}).encode())

        def locationManager_didFailWithError_(self, manager, error):
            state["failed"] = True  # kCLErrorLocationUnknown: tried and found nothing; tries again later

        def locationManagerDidChangeAuthorization_(self, manager):
            state["wanted"] = True

    manager = CoreLocation.CLLocationManager.alloc().init()
    delegate = Delegate.alloc().init()
    manager.setDelegate_(delegate)
    manager.setDesiredAccuracy_(CoreLocation.kCLLocationAccuracyHundredMeters)
    manager.requestWhenInUseAuthorization()

    def listen() -> None:
        while (message := _read_message(sys.stdin.buffer)) is not None:
            if message[0] == REFRESH:
                state["wanted"] = True
        os._exit(0)

    threading.Thread(target=listen, daemon=True).start()
    last_request = 0.0
    while True:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.5))
        authorization = manager.authorizationStatus()
        allowed = authorization in (AUTHORIZED_ALWAYS, AUTHORIZED_WHEN_IN_USE)
        now = time.monotonic()
        if allowed and (state["wanted"] or now - last_request >= REFRESH_EVERY_S):
            state["wanted"], last_request = False, now
            manager.requestLocation()
        words = status_words(CoreLocation.CLLocationManager.locationServicesEnabled(), authorization,
                             state["fix"], now - started, state["failed"])
        if words != state["last_status"]:
            state["last_status"] = words
            write(STATUS, words.encode())


class LocationProcess:
    """The app's side: starts the location process, keeps its latest fix and status,
    and asks it for a fresh fix when told to."""

    def __init__(self, on_fix=None, command: list[str] | None = None):
        self.on_fix = on_fix or (lambda fix: None)
        self.fix: Fix | None = None
        self.status = "starting"
        self._lock = threading.Lock()
        self._process = subprocess.Popen(command or location_command(), stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        threading.Thread(target=self._listen, name="location-reader", daemon=True).start()

    def refresh(self) -> None:
        """Ask for a fresh fix. Never waits for it."""
        with self._lock:
            try:
                self._process.stdin.write(_message(REFRESH, b""))
                self._process.stdin.flush()
            except (OSError, ValueError):  # the process has stopped; `status` says why
                try:
                    self._process.stdin.close()  # drops the request that could not be sent
                except OSError:
                    pass

    def stop(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            self._process.wait(5)

    def _listen(self) -> None:
        while (message := _read_message(self._process.stdout)) is not None:
            kind, data = message
            if kind == FIX:
                fix = self._fix_from(data)
                if fix is not None:
                    self.fix = fix
                    self.on_fix(fix)
            elif kind == STATUS:
                self.status = data.decode(errors="replace")
        code = self._process.wait()
        if code == -signal.SIGABRT:
            self.status = f"off: macOS stopped it. Use the packaged app, and allow it in {SETTINGS}"
        elif not self.status.startswith("off"):
            self.status = f"off: location stopped (exit code {code})"

    @staticmethod
    def _fix_from(data: bytes) -> Fix | None:
        try:
            reading = json.loads(data)
            return Fix.from_point(float(reading["lat"]), float(reading["lon"]),
                                  float(reading["accuracy"]), int(reading["at"]))
        except (ValueError, KeyError, TypeError):
            return None


if __name__ == "__main__":
    child_main()
