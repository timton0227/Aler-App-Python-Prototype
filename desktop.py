"""Alert Mesh desktop apps: a page in its own window, with no browser.

Two apps, one launcher:
- the phone app (phone_app.py): Now, Report and Chat, with real Bluetooth;
- the warning app (warning_app.py): Warning console, Map and Hub board.

Run from this folder, with the build tools installed (see packaging/requirements-build.txt):

    python desktop.py                  (the phone app)
    python desktop.py --app warning    (the warning app)

The packaged apps (packaging/build_mac.sh, packaging/build_windows.ps1) run this same
file, each through its own small start file in packaging/.

How it works. Streamlit's server and the window both need the program's main thread,
so this program starts a second copy of itself with `--serve PORT` to run the page,
and shows the page in a native window (pywebview: Safari's engine on a Mac, Edge's on
Windows). Closing the window stops the second copy; so does the first copy dying.
The page is served on 127.0.0.1 only, so no other computer can reach it.

This is free and unencumbered software released into the public domain.
"""
import argparse
import html
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

HOST = "127.0.0.1"
START_TIMEOUT_S = 60

# Inside the packaged app, PyInstaller unpacks its files into one folder and sets
# `sys.frozen`; otherwise the files sit next to this one.
FROZEN = getattr(sys, "frozen", False)
HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
LOG = Path(tempfile.gettempdir()) / "alert-mesh-server.log"
# --check also writes its result here: a Windows window app has no text output to print to.
CHECK_RESULT = Path(tempfile.gettempdir()) / "alert-mesh-check.txt"

# Passed on the command line, not read from .streamlit/config.toml: the packaged app
# starts in "/", where that file is not found.
STREAMLIT_FLAGS = {
    "server.headless": "true",          # no browser, no first-run e-mail prompt
    "server.address": HOST,             # this computer only
    "global.developmentMode": "false",  # a bundled Streamlit otherwise thinks it is in development
    "server.fileWatcherType": "none",
    "server.runOnSave": "false",
    "browser.gatherUsageStats": "false",
    "client.toolbarMode": "minimal",    # no Deploy button
}


@dataclass(frozen=True)
class Page:
    name: str
    file: str
    title: str
    size: tuple[int, int]
    # Modules the page loads only when it starts its links, so its own imports do not
    # name them; the self-check imports them too.
    also_needs: tuple[str, ...] = ()
    # Room for the sidebar, a chat list beside a conversation, and the status bar; still
    # fits a 1366 x 768 Windows laptop at 125% scaling (1093 x 614 usable).
    min_size: tuple[int, int] = (960, 600)

    @property
    def path(self) -> Path:
        return HERE / self.file


# The radio libraries each system uses (bleak and bless pick one when first used).
_RADIO = {
    "darwin": ("bleak.backends.corebluetooth.scanner", "bleak.backends.corebluetooth.client"),
    "win32": ("bleak.backends.winrt.scanner", "bleak.backends.winrt.client"),
}.get(sys.platform, ())

# The internet link loads these only when it starts, so the page's own imports do not show them.
_INTERNET = ("alertmesh.relays", "alertmesh.internet", "websockets.sync.client", "certifi")
# The pin map and the location process, loaded only when used.
_WHERE = ("pydeck", *(("CoreLocation", "Foundation") if sys.platform == "darwin" else ()))

PAGES = {
    "phone": Page("phone", "phone_app.py", "Alert Mesh", (1200, 760),
                  ("alertmesh.ble", "alertmesh.lan", "bleak", "bless", *_RADIO, *_INTERNET, *_WHERE)),
    "warning": Page("warning", "warning_app.py", "Alert Mesh Warnings", (1400, 900),
                    ("alertmesh.lan", *_INTERNET)),
}


def free_port() -> int:
    """A port nothing is using right now, on this computer only."""
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def server_command(port: int, page: Page) -> list[str]:
    """How to start the second copy that serves the page. Each packaged app is its own
    executable and knows its page; in development it is Python running this file."""
    if FROZEN:
        return [sys.executable, "--serve", str(port), "--parent", str(os.getpid())]
    return [sys.executable, str(Path(__file__).resolve()), "--app", page.name,
            "--serve", str(port), "--parent", str(os.getpid())]


def streamlit_args(port: int, page: Page) -> list[str]:
    # The iPhone app's colours, light and dark. Imported here, not at the top: the
    # self-check has to start and report a missing alertmesh, not crash on it.
    from alertmesh import style

    flags = {**STREAMLIT_FLAGS, **style.streamlit_flags()}
    return ["streamlit", "run", str(page.path), f"--server.port={port}",
            *(f"--{name}={value}" for name, value in flags.items())]


def serve(port: int, parent: int, page: Page) -> None:
    """The second copy: run the page until told to stop, or until the window's copy is gone."""
    threading.Thread(target=_exit_when_parent_dies, args=(parent,), daemon=True).start()
    from streamlit.web import cli

    sys.argv = streamlit_args(port, page)
    sys.exit(cli.main())


def _parent_alive(parent: int) -> bool:
    if sys.platform == "win32":
        # Windows keeps reporting the old parent ID, so ask whether that process still runs.
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x00100000, False, parent)  # SYNCHRONIZE
        if not handle:
            return False
        still_running = kernel32.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT
        kernel32.CloseHandle(handle)
        return still_running
    # Elsewhere an orphan is adopted by another process, so its parent ID changes.
    return os.getppid() == parent


def _exit_when_parent_dies(parent: int) -> None:
    while _parent_alive(parent):
        time.sleep(1)
    os._exit(0)


def wait_until_up(port: int, server: subprocess.Popen | None = None, timeout: float = START_TIMEOUT_S) -> bool:
    """True once the page answers; False if the server stopped or time ran out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server is not None and server.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"http://{HOST}:{port}/_stcore/health", timeout=1) as reply:
                if reply.read().strip() == b"ok":
                    return True
        except OSError:
            pass
        time.sleep(0.2)
    return False


def stop(server: subprocess.Popen) -> None:
    if server.poll() is None:
        server.terminate()
        try:
            server.wait(5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()


def check(page: Page) -> int:
    """Import everything the page imports and read the town and relay lists, without a window.
    The build runs this on the finished app, so an app with a missing part fails
    the build instead of showing an error page to whoever opens it."""
    import ast
    import importlib

    names = list(page.also_needs)
    for node in ast.walk(ast.parse(page.path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
            # `from package import module` names modules too; plain names are skipped below.
            names += [f"{node.module}.{alias.name}" for alias in node.names]
    for name in sorted(set(names)):
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as error:
            parent, _, attribute = name.rpartition(".")
            if not (parent and error.name == name and hasattr(importlib.import_module(parent), attribute)):
                return _report(f"missing: {name} ({error})", 1)
    from alertmesh import georelays, places

    relays = georelays.Directory().entries
    if not relays:
        return _report(f"missing: the relay list ({georelays.CSV_NAME})", 1)
    return _report(f"ok: {len(set(names))} imports of {page.file} load; {len(places.towns())} towns from "
                   f"{places.DATA_FILE}; {len(relays)} relays", 0)


def _report(message: str, code: int) -> int:
    CHECK_RESULT.write_text(message + "\n", encoding="utf-8")
    if sys.stdout is not None:
        print(message)
    return code


PAGE = """<html><body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
font-family:-apple-system,'Segoe UI',sans-serif;color:#333;background:#fff"><div style="text-align:center;max-width:600px">
<h2>Alert Mesh</h2><p>{message}</p></div></body></html>"""


def main(page: Page) -> None:
    try:
        import webview
    except ImportError:
        sys.exit("The desktop window needs pywebview. Install the build tools first:\n"
                 "  python3 -m pip install -r packaging/requirements-build.txt")

    port = free_port()
    with open(LOG, "w", encoding="utf-8") as log:
        extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
        server = subprocess.Popen(server_command(port, page), stdout=log, stderr=subprocess.STDOUT, **extra)
    width, height = page.size
    window = webview.create_window(page.title, html=PAGE.format(message="Starting…"),
                                   width=width, height=height, min_size=page.min_size)

    def show_page():
        if wait_until_up(port, server):
            window.load_url(f"http://{HOST}:{port}/")
        else:
            message = ("The demo page did not start. Details are in "
                       f"<code>{html.escape(str(LOG))}</code>.")
            window.load_html(PAGE.format(message=message))

    try:
        webview.start(show_page)
    finally:
        stop(server)


def run(app: str | None = None) -> None:
    """Start as told on the command line. The packaged apps pass their own `app`."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    if app is None:
        parser.add_argument("--app", choices=sorted(PAGES), default="phone", help="which app (default: phone)")
    parser.add_argument("--serve", type=int, metavar="PORT", help="run the page on this port (internal)")
    parser.add_argument("--parent", type=int, help="stop when this process ends (internal)")
    parser.add_argument("--bluetooth", action="store_true", help="be the phone app's Bluetooth process (internal)")
    parser.add_argument("--location", action="store_true", help="be the phone app's location process (internal)")
    parser.add_argument("--check", action="store_true", help="check the app has every part it needs, then exit")
    # Known arguments only: older macOS adds its own (-psn_…) when opening an app.
    options, _ = parser.parse_known_args()
    page = PAGES[app or options.app]
    if options.check:
        sys.exit(check(page))
    if options.bluetooth:
        from alertmesh.ble import child_main

        child_main()
    elif options.location:
        from alertmesh.location import child_main

        child_main()
    elif options.serve:
        serve(options.serve, options.parent or os.getppid(), page)
    else:
        main(page)


if __name__ == "__main__":
    run()
