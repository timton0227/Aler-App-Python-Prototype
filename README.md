# Alert Mesh — Python prototype

A computer-only version of the Alert Mesh iPhone app, for the competition demo. It
runs on laptops, in VS Code or as two double-click apps:

- the **phone app**, like the iPhone app: text people nearby, read official warnings,
  report hazards and call for help. Laptops pass messages to each other over **real
  Bluetooth**, hopping through laptops in between;
- the **warning app**, the Bureau's side: write and send official warnings, watch one
  spread through a simulated town, and show the evacuation centre's wall display.

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
- Chat: a Nearby conversation everyone in range reads, and private conversations only
  the other person can open, laptop to laptop over Bluetooth.
- Warnings from the warning app reach phone apps over the local network (Wi-Fi), and
  phone apps pass them on over Bluetooth to laptops without a network.
- The internet, when switched on: warnings and calls for help over Nostr relays, the
  same way the iPhone app sends them, so the Python apps and iPhones running Alert Mesh
  see each other's (see "The internet and iPhones").

Not covered: talking to real iPhones over Bluetooth (the laptops' Bluetooth format is
their own), chat over the internet, Tor, voice, images, read receipts.

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
Windows and Linux too, but that has not been tested (on Linux, Bluetooth needs BlueZ).

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
Time only moves when you press **+1**, **+5** or **+15** minutes at the foot of the
sidebar. **Simulated town**, under the tabs, builds a different town.

| Tab | What it does |
|---|---|
| Warning console | Write a warning, pick its area, check the preview (the warning as a phone in the area shows it), and send it. In the simulated town it goes out over Bluetooth from the evacuation centre and to the internet; it also goes to real phone apps on this network and, with **Send over the internet** on (in the sidebar), to real phone apps and iPhones anywhere. |
| Map | Watch a warning spread: blue phones read it on the internet, red phones got it over Bluetooth. |
| Hub board | The evacuation centre's wall display, in large type. It stays black whatever the system's light or dark setting, for a projector in a hall. |

The map needs internet for its street background. Without internet the phones
still show, on a blank background.

The simulated town keeps its own clock, which starts in 2023, so the copy sent to real
phone apps is signed again with the real time. Building a new town, opening a second
browser tab or reloading the page withdraws the warnings sent before: the new town
could not cancel them.

### The phone app

`streamlit run phone_app.py` (from VS Code's terminal, see below) opens the phone app.
Open **Settings** first (click your name at the foot of the sidebar) and say where you
are (see "Where you are" below). Your position decides which warnings are for you, and
a call for help or a report says you are there. Your nickname, town, pin, last position
and keys are kept in `~/Library/Application Support/Alert Mesh/` (Mac) or
`%APPDATA%\Alert Mesh` (Windows); messages are not kept.

| Tab | What it does |
|---|---|
| Now | A solid colour block when a warning covers your town, with what to do; otherwise "No current warnings" or "No warnings where you are". Then the other warnings, calls for help from people nearby, and how you're connected. The red **I need help** bar at the bottom opens the call for help (then **I'm safe now**). |
| Report | Tell people nearby about a hazard, and see what they report. Calls for help are red, everything else grey. Reports are not official warnings. |
| Chat | **Nearby**, which everyone in range reads, and private conversations, as bubbles. **People nearby** lists the laptops heard recently; **Message** opens a private conversation. |

Both apps take the iPhone app's look: the system typeface, system blue, rounded grey
cards, and the same light and dark colours. They follow the computer's light or dark
setting. A status bar along the bottom says whether Bluetooth, the local network and
the internet are on.

| Shortcut | Mac | Windows |
|---|---|---|
| Tab 1, 2, 3 | ⌘1, ⌘2, ⌘3 | Ctrl+1, Ctrl+2, Ctrl+3 |
| Settings (phone app) | ⌘, | Ctrl+, |
| I need help (phone app; opens the sheet, sends nothing) | ⌘⇧H | Ctrl+Shift+H |

What travels how:

| | Between laptops over Bluetooth | From the warning app over the local network | Over the internet, when switched on |
|---|---|---|---|
| Nearby and private messages | yes, up to 7 hops | no | no |
| Calls for help, "I'm safe" | yes, up to 7 hops | no | yes, to and from iPhones too |
| Hazard reports | yes, up to 7 hops | no | no (the iPhone app keeps them off too) |
| Official warnings | yes, passed on by any laptop that has one | yes, repeated every 30 s | yes, to iPhones too |

Bluetooth reaches about 10 m indoors. One computer cannot talk to itself over
Bluetooth, so trying the chat needs two laptops (see "Two-laptop check").

#### Where you are

The phone app uses the first of these it has:

1. **A pin** you dropped: **Settings → Drop a pin**. Pick a town, click the square of
   about 1 km you are in, then the square of about 150 m. Or type or paste coordinates,
   such as `-14.465, 132.263` from a map app. The pin stays until **Clear pin**.
2. **This Mac's own location** (**Use this Mac's location**, on by default). macOS asks
   once. It works in the packaged **Alert Mesh** app only: macOS never asks a plain
   `python` or `streamlit run`, and the switch's status says so. A position older than
   an hour is not used, as the laptop may have moved. It needs Wi-Fi on.
3. **Your town's centre**, as picked in Settings.

As on the iPhone, only a rough area leaves the laptop: a call for help and "I'm safe"
to about 150 m, a hazard report as exact as the position (at best about 40 m). The
last position is kept as that area code only, never as coordinates. The status bar
says which one is in use. The map comes from the internet; without it the squares and
town names still show, and typed coordinates always work.

### Bluetooth and network permission (Mac)

macOS stops any program that uses Bluetooth unless the app running it says why. VS
Code says why; **Terminal and iTerm do not**. So run the phone app from VS Code's
terminal or its Run and Debug panel, or use the packaged app. If it is run from
Terminal, the phone app still opens, but its status bar says "Bluetooth off" and why.

The first time, macOS asks to allow Bluetooth, and to find devices on the local
network. Allow both. Until the local network is allowed, macOS
quietly drops warnings between computers; on one computer they always arrive. To
change your mind later: **System Settings → Privacy & Security → Bluetooth** or
**Local Network**.

On Windows, allow the apps through Windows Firewall on private networks when asked.

### Two-laptop check

Not yet done: it needs two computers. On each laptop, open the phone app (the packaged
**Alert Mesh**, or `python3 desktop.py` from VS Code) and pick a town. Keep them within a
few metres. On one laptop, also open the warning app.

1. Within about 30 s, each phone app lists the other under **Chat → People nearby**,
   and the status bar says "Bluetooth on · 1 laptop nearby".
2. Write in **Nearby** on each laptop: the message appears on the other.
3. Press **Message** and write privately, both ways.
4. Send a call for help from one laptop (**I need help**): it appears under **Calls for help**
   on the other laptop's **Now**.
5. Send a warning from the warning app: both phone apps show it.
6. Turn Wi-Fi off on laptop 2 and send another warning: laptop 2 still gets it, over
   Bluetooth from laptop 1.

If step 1 fails, try `python3 tools/ble_probe.py` on both laptops (from VS Code's
terminal): each should list the other under "Alert Mesh laptops".

### The internet and iPhones

The iPhone app sends warnings and calls for help over the internet through Nostr, a
public network of relay servers. Both Python apps can do the same, so they and iPhones
running Alert Mesh see each other's warnings and calls for help. It is **off until
switched on**, because relays are public: anyone can read what is sent there.

- **Warning app:** **Send over the internet**, in the sidebar. Each warning, update and
  cancellation goes to the iPhone app's 4 built-in relays, which every phone listens
  on, and to the 5 relays nearest each area cell. Turning it on also sends the
  warnings already live. The status bar says how many relays took the last warning.
- **Phone app:** **Use the internet**, in Settings (kept between runs). The phone app
  then gets every warning, and calls for help around its town; and it puts its own
  calls for help, and ones it hears over Bluetooth, online on the 5 relays nearest
  their area. That is how the iPhone app does it, so the relays match. A call for help
  shows your nickname, your note and your place to about 150 m.

Warnings are signed with the development key. Only an iPhone app built in **Debug**
trusts that key; a Release or TestFlight build shows no warnings at all until a real
key exists (see `../alert-mesh/AlertMesh/AlertMesh/Protocols/AlertPublisherKey.swift`).

Needs the `websockets` library (`python3 -m pip install -r requirements.txt` again if
you set up before it was added). Without it the switches are greyed out.

**Check with the real relays** (sends a short-lived test event; add `--warning` and
`--sos` for a test warning and a test call for help, each withdrawn straight away):

```bash
python3 tools/nostr_live_check.py --warning --sos
```

**Check with an iPhone** (not yet done):

1. Install the Alert Mesh iPhone app from Xcode (a Debug build), allow location, and
   give it internet.
2. Open the warning app, turn on **Send over the internet**, and send a warning for
   the town where the iPhone is. Every iPhone gets every warning, wherever it is; one
   for its own area is the loud one. It shows within a few seconds.
3. Open the phone app, turn on **Use the internet** in Settings, and pick the town
   where the iPhone is (the iPhone uses its GPS). Calls for help are shared within the
   same or a neighbouring area of about 40 × 20 km. Send a call for help from the
   iPhone: it appears under **Calls for help** on the phone app's **Now**.
4. Send a call for help from the phone app: the iPhone shows it.
5. Cancel the warning in the warning app: it goes from the iPhone.

## Desktop apps (no browser)

Both apps can also be double-click apps: one window each, no browser, and no Python
needed on the computer that opens them. The phone app's window opens at 1200 × 760;
neither can be made smaller than 960 × 600. `desktop.py` shows a page in its own window;
`PyInstaller` bundles everything.

### Build it

Both builds need `../alert-mesh/` next to this folder: they copy the town list and the
icon from it. The first build downloads the build tools into a separate environment
(`packaging/.venv-mac` or `packaging\.venv-windows`); later builds take about a minute.

| Computer | Command, from this folder | Result |
|---|---|---|
| Mac (Apple Silicon) | `packaging/build_mac.sh` | `dist/Alert Mesh.app`, the phone app (about 250 MB; zip about 100 MB), and `dist/Alert Mesh Warnings.app` (about 290 MB; zip about 110 MB) |
| Windows | `powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1` | `dist\Alert Mesh\Alert Mesh.exe` and `dist\Alert Mesh Warnings\Alert Mesh Warnings.exe`, and a zip of each |

The Mac build was tested with Python 3.14 from python.org. To choose a Python for the
first build, name it with `PYTHON`, for example:

```bash
PYTHON=/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 packaging/build_mac.sh
```

The Windows script has **not been run yet** (see step 12.4 in `PROGRESS.md`).

To try the windows without building, install the build tools
(`python3 -m pip install -r packaging/requirements-build.txt`) and run
`python3 desktop.py` (phone app) or `python3 desktop.py --app warning`, or
**Run and Debug → Desktop window: phone app / warning app** in VS Code.

### Open it on another computer

- **Mac:** copy `Alert-Mesh-mac.zip` (the phone app) and, where warnings are sent from,
  `Alert-Mesh-Warnings-mac.zip` over, double-click to unzip, and open the app. They run
  on Apple Silicon Macs (M1 or later); they were tested on macOS 15.
  The app is not signed by a registered Apple developer, so a copy that arrived by
  download, AirDrop or e-mail is blocked the first time ("cannot be verified"). Click
  **Done**, then open **System Settings → Privacy & Security**, scroll down and click
  **Open Anyway**. This is needed once per computer. A copy from a USB stick usually
  opens straight away.
- **Windows:** unzip the whole folder and open **Alert Mesh.exe** (or
  **Alert Mesh Warnings.exe**) inside it (it needs the other files in that folder). If Windows shows "Windows protected your PC",
  click **More info → Run anyway**.
- Allow Bluetooth and the local network when asked (see "Bluetooth and network permission").
- The map's street background needs internet; everything else works offline.
- Each app's page is only reachable from the computer running it, not from the network.
  What goes over the network is the signed warnings, and over Bluetooth the messages.
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
