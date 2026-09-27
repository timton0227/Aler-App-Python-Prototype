# Alert Mesh — Python prototype

A computer-only version of the core ideas in the Alert Mesh iPhone app, for the
competition demo. It runs in VS Code (or Jupyter) on any laptop. It does not run on a
phone, and it does not use real Bluetooth.

The Swift app in `../alert-mesh/` is the **reference**. This folder never changes it.
Every Python module names the Swift file it was ported from, and every step of the port
is listed in [`PROGRESS.md`](PROGRESS.md) and recorded in [`CHANGELOG.md`](CHANGELOG.md).

## What it covers

- Official warnings: signed by the publisher, updated, cancelled — in the **same byte
  format** as the app, checked against the app's frozen test vectors.
- "Is this warning for me?" — the app's loud / quiet rule.
- SOS, "I'm safe" check-ins and community hazard reports.
- A simulation of phones on a map passing warnings to each other over Bluetooth range,
  up to 7 hops, including phones that carry a warning as they move.
- Numbers for judges: how many people get warned, and how fast, with and without the mesh.

Not covered: real Bluetooth, Tor, internet relays (Nostr), private chat, voice, images.

## Set up (once)

1. Check your Python. In a terminal, `python3 --version` must say **3.10 or newer**. A
   Mac's built-in Python is 3.9, which is too old: install a newer one from
   [python.org](https://www.python.org/downloads/). (On Windows, type `py` instead of
   `python3`.)
2. Open this folder (`python-prototype/`) in VS Code. Install the VS Code extensions
   **Python** and **Jupyter** if VS Code asks.
3. In VS Code's terminal, make a private Python environment for this folder and install
   the libraries into it:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python3 -m pip install -r requirements.txt
   ```

   On Windows, the middle line is `.venv\Scripts\activate`. Some systems refuse
   `pip install` outside such an environment, which is why it is used here.
4. In VS Code, choose **Python: Select Interpreter** and pick the one in `.venv`, so the
   notebook, the Testing panel and Run and Debug all use it.

Tested on macOS with Python 3.13 and 3.14, from a fresh clone. It should work on
Windows and Linux too, but that has not been tested.

## Run

| What | How |
|---|---|
| Tests | `python3 -m pytest -q`, or the Testing panel in VS Code |
| Story notebook | Open `demo.ipynb` in VS Code and choose **Run All** |
| Warning app (console, map, hub board) | `streamlit run warning_app.py`, or **Run and Debug → Warning app** in VS Code |
| Phone app (Now, Report, Chat) | `streamlit run phone_app.py`, or **Run and Debug → Phone app** in VS Code |
| Cross-check with the Swift app (Mac with Swift only) | `python3 tools/cross_check_swift.py` |

### The warning app

`streamlit run warning_app.py` opens a page in the browser with one simulated town: about 300
phones around Katherine, a few with internet, and an evacuation centre in the middle.
Time only moves when you press **+1**, **+5** or **+15** minutes in the sidebar, where
you can also build a different town.

| Tab | What it does |
|---|---|
| Warning console | Write a warning, pick its area, check the preview, and send it. In the simulated town it goes out over Bluetooth from the evacuation centre and to the internet; it also goes to real phone apps on this network. |
| Map | Watch a warning spread: blue phones read it on the internet, red phones got it over Bluetooth. |
| Hub board | The evacuation centre's wall display, in large type. |

The map needs internet for its street background. Without internet the phones
still show, on a blank background.

## Desktop app (no browser)

The live demo page can also be a double-click app: one window, no browser, and no
Python needed on the computer that opens it. `desktop.py` shows the page in its own
window; `PyInstaller` bundles everything into one app.

### Build it

Both builds need `../alert-mesh/` next to this folder: they copy the town list and the
icon from it. The first build downloads the build tools into a separate environment
(`packaging/.venv-mac` or `packaging\.venv-windows`); later builds take about a minute.

| Computer | Command, from this folder | Result |
|---|---|---|
| Mac (Apple Silicon) | `packaging/build_mac.sh` | `dist/Alert Mesh.app` (about 290 MB) and `dist/Alert-Mesh-mac.zip` (about 110 MB) |
| Windows | `powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1` | `dist\Alert Mesh\Alert Mesh.exe` and `dist\Alert-Mesh-windows.zip` |

The Mac build was tested with Python 3.14 from python.org. To choose a Python for the
first build, name it with `PYTHON`, for example:

```bash
PYTHON=/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 packaging/build_mac.sh
```

The Windows script has **not been run yet** (see step 12.4 in `PROGRESS.md`).

To try the window without building, install the build tools
(`python3 -m pip install -r packaging/requirements-build.txt`) and run
`python3 desktop.py`, or **Run and Debug → Desktop window** in VS Code.

### Open it on another computer

- **Mac:** copy `Alert-Mesh-mac.zip` over, double-click it to unzip, and open
  **Alert Mesh**. It runs on Apple Silicon Macs (M1 or later); it was tested on macOS 15.
  The app is not signed by a registered Apple developer, so a copy that arrived by
  download, AirDrop or e-mail is blocked the first time ("cannot be verified"). Click
  **Done**, then open **System Settings → Privacy & Security**, scroll down and click
  **Open Anyway**. This is needed once per computer. A copy from a USB stick usually
  opens straight away.
- **Windows:** unzip the whole folder and open **Alert Mesh.exe** inside it (it needs
  the other files in that folder). If Windows shows "Windows protected your PC",
  click **More info → Run anyway**.
- The map's street background needs internet; everything else works offline.
- The page is only reachable from the computer running the app, not from the network.
- If the window says the page did not start, the details are in
  `alert-mesh-server.log` in the computer's temporary folder (on a Mac: `open $TMPDIR`).

## For contributors

1. Open [`PROGRESS.md`](PROGRESS.md) and take the next unticked step.
2. Read the Swift file the step names, and its Swift tests.
3. Write the Python code and port the matching tests.
4. Run the step's **Verify** command. It must pass.
5. Tick the box, add a [`CHANGELOG.md`](CHANGELOG.md) entry, and commit only that step's files.

## The signing key in this folder

The prototype signs warnings with the **development key** published in
`../alert-mesh/docs/ALERT-WIRE-FORMAT.md`. Its private half is public on purpose, so
anyone can reproduce the test vectors. It must never sign a real warning.

## Credits

Town names and coordinates © GeoNames (https://www.geonames.org), CC BY 4.0, read from
the app's `AustralianPlacesData.swift`. Code is public domain, like the app it is based on.
