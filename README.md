# Alert Mesh

**Emergency warnings that keep working when the network doesn't.**

Alert Mesh gets flood and bushfire warnings to people in remote communities, even when the
mobile network and the internet are down. An official warning reaches whichever devices
can be reached. After that, each device **passes it to the devices around it over
Bluetooth**, one hop at a time, until everyone nearby has it. Calls for help and hazard
reports travel the same way in the other direction.

It runs on ordinary laptops, as two apps:

- the **phone app**, for people in the community: read warnings, report hazards, call for
  help, and chat with people nearby;
- the **warning app**, for the emergency service: write and send official warnings, watch
  one spread through a simulated town, and put up the evacuation centre's wall display.

---

## The problem

Many remote communities have no reliable internet or mobile coverage. When a flood or fire
is coming, the warning has to reach people anyway, and the moment it matters most is often
the moment the towers go down.

## The idea

Every device that has a warning hands it to every other device it comes near. No internet
is needed on either side. A neighbour who drove past, someone at the shop, a car passing
through: each one carries the warning a little further. Bluetooth reaches only 10 to 50
metres, so the network exists because people move around, not because the radio is strong.

Going the other way, a person with no signal can press **I need help**. The call hops
between devices until it reaches one with a connection, and every device it passes tells
its owner that someone nearby needs help.

## How a warning travels

1. The emergency service writes a warning in the **warning app** and picks the area it
   covers.
2. The warning is **signed** with the service's private key, so nobody can fake one.
3. It goes out to the devices that can be reached: over the internet, over the local
   network (Wi-Fi), and over Bluetooth.
4. Each device checks the signature. A warning that is forged, changed or signed by the
   wrong key is thrown away and **never passed on**.
5. From then on, every device that has the warning shares it over Bluetooth with every
   device it meets, up to 7 hops, until the warning expires. A device that arrives later
   still picks it up.
6. Each device compares the warning's area with where it is, and decides whether to alarm
   loudly, notify quietly, or stay silent.

A newer version of a warning replaces the old one, and a signed cancellation removes it
everywhere it went.

Warning levels follow the Australian Warning System: **Advice** (yellow), **Watch and
Act** (orange) and **Emergency Warning** (red). Red is only ever used for Emergency
Warning.

## What it does

- **Official warnings:** signed, updated and cancelled by the publisher. Forged, altered,
  expired and malformed warnings are rejected.
- **"Is this for me?":** the loud or quiet decision, based on where you are.
- **I need help / I'm safe now:** a call for help with your place to about 150 metres,
  close enough to find you without pinpointing your house. Only you can call it off,
  because "I'm safe" must be signed by the same key.
- **Hazard reports:** anyone can report a flooded causeway or a spot fire. Reports use
  their own words (Minor, Serious, Dangerous) and look different from official warnings,
  so a report can never be mistaken for one.
- **Chat:** a Nearby conversation that everyone in range reads, and private conversations
  that only the other person can open.
- **Evacuation centre board:** a laptop left at an evacuation centre, town hall or
  roadhouse shows the most serious warnings in type you can read across a hall.
- **A simulated town:** about 300 phones on a map, so you can watch a warning spread hop
  by hop, including phones that carry it as they move.
- **Numbers:** how many people get warned, and how fast, with and without the mesh.

---

## Set up (once)

1. Check your Python. In a terminal, `python3 --version` must say **3.10 or newer**. A
   Mac's built-in Python is 3.9, which is too old: install a newer one from
   [python.org](https://www.python.org/downloads/). (On Windows, type `py` instead of
   `python3`.)
2. Open this folder in VS Code. Install the VS Code extensions **Python** and **Jupyter**
   if VS Code asks.
3. In VS Code's terminal, make a private Python environment for this folder and install
   the libraries into it:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python3 -m pip install -r requirements.txt
   ```

   On Windows, the middle line is `.venv\Scripts\activate`.
4. In VS Code, choose **Python: Select Interpreter** and pick the one in `.venv`, so the
   notebook, the Testing panel and Run and Debug all use it.

Tested on macOS with Python 3.13 and 3.14. It should work on Windows and Linux too, but
that has not been tested (on Linux, Bluetooth needs BlueZ).

## Run

| What | How |
|---|---|
| Warning app (console, map, hub board) | `streamlit run warning_app.py`, or **Run and Debug → Warning app** in VS Code |
| Phone app (Now, Report, Chat) | `streamlit run phone_app.py`, or **Run and Debug → Phone app** in VS Code |
| Story notebook | Open `demo.ipynb` in VS Code and choose **Run All** |
| Tests | `python3 -m pytest -q`, or the Testing panel in VS Code |

### The warning app

`streamlit run warning_app.py` opens a page with one simulated town: about 300 phones
around Katherine, a few with internet, and an evacuation centre in the middle. Time only
moves when you press **+1**, **+5** or **+15** minutes at the foot of the sidebar.
**Simulated town**, under the tabs, builds a different town.

| Tab | What it does |
|---|---|
| Warning console | Write a warning, pick its area, check the preview (the warning as a phone in the area shows it), and send it. It goes out in the simulated town, to real phone apps on this network, and, with **Send over the internet** on, to phone apps anywhere. |
| Map | Watch a warning spread: blue phones read it on the internet, red phones got it over Bluetooth. |
| Hub board | The evacuation centre's wall display, in large type on black, for a projector in a hall. |

The map needs internet for its street background. Without internet the phones still show,
on a blank background.

The simulated town keeps its own clock, so the copy sent to real phone apps is signed
again with the real time. Building a new town, opening a second browser tab or reloading
the page withdraws the warnings sent before.

### The phone app

`streamlit run phone_app.py` (from VS Code's terminal, see "Bluetooth and network
permission") opens the phone app. Open **Settings** first (click your name at the foot of
the sidebar) and say where you are. Your nickname, town, pin, last position and keys are
kept in `~/Library/Application Support/Alert Mesh/` (Mac) or `%APPDATA%\Alert Mesh`
(Windows). Messages are not kept.

| Tab | What it does |
|---|---|
| Now | A solid colour block when a warning covers where you are, with what to do; otherwise "No current warnings" or "No warnings where you are". Then the other warnings, calls for help from people nearby, and how you're connected. The red **I need help** bar opens the call for help (then **I'm safe now**). |
| Report | Tell people nearby about a hazard, and see what they report. Calls for help are red, everything else grey. |
| Chat | **Nearby**, which everyone in range reads, and private conversations. **People nearby** lists the devices heard recently; **Message** opens a private conversation. |

Both apps follow the computer's light or dark setting. A status bar along the bottom says
whether Bluetooth, the local network and the internet are on.

| Shortcut | Mac | Windows |
|---|---|---|
| Tab 1, 2, 3 | ⌘1, ⌘2, ⌘3 | Ctrl+1, Ctrl+2, Ctrl+3 |
| Settings (phone app) | ⌘, | Ctrl+, |
| I need help (phone app; opens the sheet, sends nothing) | ⌘⇧H | Ctrl+Shift+H |

What travels how:

| | Between devices over Bluetooth | From the warning app over the local network | Over the internet, when switched on |
|---|---|---|---|
| Nearby and private messages | yes, up to 7 hops | no | no |
| Calls for help, "I'm safe" | yes, up to 7 hops | no | yes |
| Hazard reports | yes, up to 7 hops | no | no |
| Official warnings | yes, passed on by any device that has one | yes, repeated every 30 s | yes |

Bluetooth reaches about 10 m indoors. One computer cannot talk to itself over Bluetooth,
so trying the chat needs two laptops (see "Two-laptop check").

#### Where you are

The phone app uses the first of these it has:

1. **A pin** you dropped: **Settings → Drop a pin**. Pick a town, click the square of about
   1 km you are in, then the square of about 150 m. Or paste coordinates, such as
   `-14.465, 132.263` from a map app. The pin stays until **Clear pin**.
2. **This Mac's own location** (**Use this Mac's location**, on by default). macOS asks
   once. It works in the packaged **Alert Mesh** app only: macOS never asks a plain
   `python` or `streamlit run`, and the switch's status says so. A position older than an
   hour is not used, as the laptop may have moved.
3. **Your town's centre**, as picked in Settings.

Only a rough area leaves the laptop: a call for help and "I'm safe" to about 150 m, a
hazard report at best to about 40 m. The last position is kept as that area code only,
never as coordinates.

### Bluetooth and network permission (Mac)

macOS stops any program that uses Bluetooth unless the app running it says why. VS Code
says why; **Terminal and iTerm do not**. So run the phone app from VS Code's terminal or
its Run and Debug panel, or use the packaged app. Run from Terminal, the phone app still
opens, but its status bar says "Bluetooth off" and why.

The first time, macOS asks to allow Bluetooth, and to find devices on the local network.
Allow both. Until the local network is allowed, macOS quietly drops warnings between
computers. To change your mind later: **System Settings → Privacy & Security → Bluetooth**
or **Local Network**.

On Windows, allow the apps through Windows Firewall on private networks when asked.

### Two-laptop check

On each laptop, open the phone app (the packaged **Alert Mesh**, or `python3 desktop.py`
from VS Code) and pick a town. Keep them within a few metres. On one laptop, also open the
warning app.

1. Within about 30 s, each phone app lists the other under **Chat → People nearby**.
2. Write in **Nearby** on each laptop: the message appears on the other.
3. Press **Message** and write privately, both ways.
4. Send a call for help from one laptop: it appears under **Calls for help** on the other
   laptop's **Now**.
5. Send a warning from the warning app: both phone apps show it.
6. Turn Wi-Fi off on laptop 2 and send another warning: laptop 2 still gets it, over
   Bluetooth from laptop 1.

If step 1 fails, run `python3 tools/ble_probe.py` on both laptops (from VS Code's
terminal): each should list the other.

### The internet

Warnings and calls for help can also travel over the internet, through Nostr, a public
network of relay servers. This is **off until switched on**, because relays are public:
anyone can read what is sent there.

- **Warning app:** **Send over the internet**, in the sidebar. Each warning, update and
  cancellation goes to 4 fixed relays that every device listens on, and to the 5 relays
  nearest the warning's area. Turning it on also sends the warnings already live.
- **Phone app:** **Use the internet**, in Settings. The phone app then gets every warning,
  and calls for help around its town. It also puts its own calls for help, and ones it
  hears over Bluetooth, on the 5 relays nearest their area. That is how a device with a
  signal becomes the doorway for everyone around it.

To check the real relays (sends a short-lived test event; `--warning` and `--sos` add a
test warning and a test call for help, each withdrawn straight away):

```bash
python3 tools/nostr_live_check.py --warning --sos
```

---

## Desktop apps (no browser)

Both apps can also be double-click apps: one window each, no browser, and no Python needed
on the computer that opens them.

| Computer | Command, from this folder | Result |
|---|---|---|
| Mac (Apple Silicon) | `packaging/build_mac.sh` | `dist/Alert Mesh.app` (phone app) and `dist/Alert Mesh Warnings.app` |
| Windows | `powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1` | `dist\Alert Mesh\Alert Mesh.exe` and `dist\Alert Mesh Warnings\Alert Mesh Warnings.exe`, and a zip of each |

The first build downloads the build tools into a separate environment; later builds take
about a minute. To choose the Python for the first build, name it with `PYTHON`:

```bash
PYTHON=/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 packaging/build_mac.sh
```

The Windows script has not been run yet.

To try the windows without building, install the build tools
(`python3 -m pip install -r packaging/requirements-build.txt`) and run `python3 desktop.py`
(phone app) or `python3 desktop.py --app warning`.

### Open it on another computer

- **Mac:** copy the zip over, double-click to unzip, and open the app (Apple Silicon, M1 or
  later). The app is not signed by a registered Apple developer, so a downloaded copy is
  blocked the first time. Click **Done**, then open **System Settings → Privacy &
  Security**, scroll down and click **Open Anyway**. This is needed once per computer.
- **Windows:** unzip the whole folder and open **Alert Mesh.exe** inside it. If Windows
  shows "Windows protected your PC", click **More info → Run anyway**.
- Allow Bluetooth and the local network when asked.
- Each app's page is only reachable from the computer running it, not from the network.
- If the window says the page did not start, the details are in `alert-mesh-server.log`:
  on a Mac in `~/Library/Logs/Alert Mesh` (Console shows it), on Windows in the temporary
  folder. What Bluetooth drops, and why, is in `alert-mesh-bluetooth.log` next to it.

---

## Things to know

**A fake warning is worse than no app.** Signature checking is not optional, and community
reports are never allowed to look like official warnings.

**It only works where people are.** Bluetooth range is tens of metres. For empty country,
the answer is fixed anchor points: an always-on laptop at an evacuation centre, town hall
or roadhouse, and devices with a signal acting as the doorway for everyone around them.

**Not a replacement for 000.** A call for help reaches nearby devices and, eventually, the
internet. It is not an emergency call.

**The signing key here is for testing only.** Warnings are signed with a development key
(`alertmesh/signer.py`) whose private half is public on purpose, so anyone can reproduce
the tests. It must never sign a real warning.

## Project layout

```
warning_app.py     the warning app
phone_app.py       the phone app
desktop.py         opens either app in its own window
demo.ipynb         the story notebook
alertmesh/         the shared code: warnings, signing, the mesh, Bluetooth, the internet
tests/             the test suite
tools/             checks and helper scripts
packaging/         builds the desktop apps
PROGRESS.md        step-by-step build plan and status
CHANGELOG.md       what each step did and how it was checked
```

## Credits

Town names and coordinates © GeoNames (https://www.geonames.org), CC BY 4.0. The code is
public domain.
