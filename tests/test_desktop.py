"""The desktop launcher (desktop.py), without opening a window.

The window itself (pywebview) is checked by eye; these check the part that can go
wrong silently: starting and stopping the server that feeds the window.
"""
import os
import subprocess
import sys
import textwrap
import time
import urllib.request

import pytest

import desktop


def test_a_free_port_is_on_this_computer_and_usable():
    port = desktop.free_port()
    assert 1024 <= port <= 65535


def test_the_server_command_in_development_and_in_the_packaged_app(monkeypatch):
    dev = desktop.server_command(8765)
    assert dev[:2] == [sys.executable, str(desktop.Path(desktop.__file__).resolve())]
    assert dev[2:] == ["--serve", "8765", "--parent", str(os.getpid())]
    monkeypatch.setattr(desktop, "FROZEN", True)
    assert desktop.server_command(8765) == [sys.executable, "--serve", "8765", "--parent", str(os.getpid())]


def test_streamlit_is_told_to_stay_on_this_computer_and_off_development_mode():
    args = desktop.streamlit_args(8765)
    assert args[:3] == ["streamlit", "run", str(desktop.APP)]
    assert "--server.port=8765" in args
    assert "--server.address=127.0.0.1" in args
    assert "--global.developmentMode=false" in args
    assert "--server.headless=true" in args


def get(port: int, path: str) -> int:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as reply:
        return reply.status


def test_the_server_starts_answers_and_stops():
    port = desktop.free_port()
    server = subprocess.Popen(desktop.server_command(port), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert desktop.wait_until_up(port, server, timeout=60)
        assert get(port, "/") == 200
    finally:
        desktop.stop(server)
    assert server.returncode is not None
    assert not desktop.wait_until_up(port, timeout=1)


def test_nothing_to_wait_for_when_the_server_has_stopped():
    stopped = subprocess.Popen([sys.executable, "-c", "pass"])
    stopped.wait()
    started = time.monotonic()
    assert not desktop.wait_until_up(desktop.free_port(), stopped, timeout=30)
    assert time.monotonic() - started < 5


@pytest.mark.skipif(sys.platform == "win32", reason="the Windows branch cannot be tested here")
def test_the_server_stops_when_the_window_process_dies():
    """If the window's process is killed, the server must not keep running on its own."""
    port = desktop.free_port()
    parent_code = textwrap.dedent(f"""
        import subprocess, sys, time
        sys.path.insert(0, {str(desktop.HERE)!r})
        import desktop
        server = subprocess.Popen(desktop.server_command({port}), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(server.pid, flush=True)
        time.sleep(120)
    """)
    parent = subprocess.Popen([sys.executable, "-c", parent_code], stdout=subprocess.PIPE, text=True)
    server_pid = int(parent.stdout.readline())
    try:
        assert desktop.wait_until_up(port, timeout=60)
        parent.kill()
        parent.wait()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and alive(server_pid):
            time.sleep(0.2)
        assert not alive(server_pid)
    finally:
        if alive(server_pid):
            os.kill(server_pid, 9)


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # An exited child not yet reaped by its new parent still has an entry; ask ps.
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith("Z")


# --- The self-check the build runs on the finished app (step 12.3) ---


def test_the_self_check_passes_here():
    out = subprocess.run([sys.executable, str(desktop.HERE / "desktop.py"), "--check"],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout.startswith("ok:") and "996 towns" in out.stdout


def test_the_self_check_fails_when_a_part_is_missing(tmp_path):
    """Like the first Mac build: app.py is there, but the alertmesh code is not
    (only the town-list folder alertmesh/data/ is)."""
    (tmp_path / "alertmesh" / "data").mkdir(parents=True)
    for name in ("desktop.py", "app.py"):
        (tmp_path / name).write_text((desktop.HERE / name).read_text(encoding="utf-8"), encoding="utf-8")
    out = subprocess.run([sys.executable, str(tmp_path / "desktop.py"), "--check"], cwd=tmp_path,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 1
    assert out.stdout.startswith("missing: alertmesh.")


def test_the_self_check_works_without_text_output():
    """A Windows window app has no text output (sys.stdout is None): the check must
    still finish and leave its result in a file for the build script."""
    desktop.CHECK_RESULT.unlink(missing_ok=True)
    code = ("import sys; sys.stdout = None; sys.path.insert(0, %r); import desktop; sys.exit(desktop.check())"
            % str(desktop.HERE))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert desktop.CHECK_RESULT.read_text(encoding="utf-8").startswith("ok:")
