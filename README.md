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
| Live demo page | `streamlit run app.py`, or **Run and Debug → Streamlit demo** in VS Code |
| Cross-check with the Swift app (Mac with Swift only) | `python3 tools/cross_check_swift.py` |

### The live demo page

`streamlit run app.py` opens a page in the browser with one simulated town: about 300
phones around Katherine, a few with internet, and an evacuation centre in the middle.
Time only moves when you press **+1**, **+5** or **+15** minutes in the sidebar, where
you can also build a different town.

| Tab | What it does |
|---|---|
| Warning console | Write a warning, pick its area, check the preview, and send it. It goes out over Bluetooth from the evacuation centre and to the internet. |
| Map | Watch a warning spread: blue phones read it on the internet, red phones got it over Bluetooth. |
| Phone view | One phone's warnings, why each was loud or quiet, and its notifications. Send a call for help, "I'm safe" or a hazard report from it. |
| Hub board | The evacuation centre's wall display, in large type. |

The map needs internet for its street background. Without internet the phones
still show, on a blank background.

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
