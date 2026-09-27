# Progress — Swift to Python port

This is the checklist for the Python prototype. Each step is small: usually one function
or one group of rules, plus its tests. Take the next unticked step, follow the rules at
the bottom, and record the result in [`CHANGELOG.md`](CHANGELOG.md).

All paths under **Swift** are relative to `../alert-mesh/`. Run every **Verify** command
from this folder (`python-prototype/`).

Legend: `[ ]` todo · `[~]` in progress · `[x]` done and verified · `[!]` blocked (reason on the line)

## Status

| Phase | Done | Total |
|---|---|---|
| 0 Setup | 3 | 3 |
| 1 Geohash | 4 | 4 |
| 2 Official alert format | 10 | 10 |
| 3 Community reports | 4 | 4 |
| 4 Proximity | 3 | 3 |
| 5 Stores | 5 | 5 |
| 6 Places | 3 | 3 |
| 7 Mesh simulation | 8 | 8 |
| 8 Metrics | 3 | 3 |
| 9 Notebook | 8 | 8 |
| 10 Streamlit | 4 | 4 |
| 11 Final check | 3 | 3 |
| 12 Desktop app | 4 | 5 |
| 13 Two apps: phone app and warning app | 6 | 9 |
| **All** | **68** | **72** |

**Next step:** 12.4

---

## Phase 0 — Setup

- [x] 0.1 Folder, `README.md`, `requirements.txt`, `.gitignore`
      Done when: the folder exists and the README explains setup and running
      Verify: `python3 -m pip install -r requirements.txt` succeeds
- [x] 0.2 `PROGRESS.md` (this file) and `CHANGELOG.md`
      Done when: every step below is listed with its Swift source and verify command
      Verify: read this file
- [x] 0.3 `.vscode/` settings and launch file, empty `alertmesh` package, smoke test, `tools/update_status.py`
      Done when: VS Code finds the tests, the package imports, and the Status table recounts itself
      Verify: `python3 -m pytest -q` shows 1 passed

## Phase 1 — Geohash

Swift: `AlertMesh/Protocols/Geohash.swift` · tests: `AlertMeshTests/LocationChannelsTests.swift`

- [x] 1.1 Alphabet and `is_valid`
      Done when: the alphabet has no `a`, `i`, `l`, `o`; empty and bad characters are invalid
      Verify: `python3 -m pytest tests/test_geohash.py -k valid`
- [x] 1.2 `encode(lat, lon, precision)`
      Done when: known cells match, and shorter precisions are prefixes of longer ones
      Verify: `python3 -m pytest tests/test_geohash.py -k encode`
- [x] 1.3 `decode_bounds` and `decode_center`
      Done when: decoding the encoded point gives a box that contains it
      Verify: `python3 -m pytest tests/test_geohash.py -k decode`
- [x] 1.4 `neighbors`
      Done when: 8 neighbours away from the poles; fewer near a pole; wraps at longitude ±180
      Verify: `python3 -m pytest tests/test_geohash.py -k neighbors`

## Phase 2 — Official alert format

Swift: `AlertMesh/AlertMesh/Protocols/AlertPackets.swift` · spec: `docs/ALERT-WIRE-FORMAT.md` ·
tests: `AlertMeshTests/AlertMesh/Protocols/AlertPacketsTests.swift`

- [x] 2.1 Constants, hazard and severity values (frozen)
      Done when: every value matches the spec tables and the Swift constants
      Verify: `python3 -m pytest tests/test_wire.py -k constants`
- [x] 2.2 TLV reader and writer
      Done when: unknown types are skipped; a repeated field is rejected, except the area cell
      Verify: `python3 -m pytest tests/test_wire.py -k tlv`
- [x] 2.3 Alert data class and field validation
      Done when: every receipt rule in the spec rejects a bad alert
      Verify: `python3 -m pytest tests/test_wire.py -k validation`
- [x] 2.4 Alert signing bytes
      Done when: the first 22 bytes are the frozen context prefix
      Verify: `python3 -m pytest tests/test_wire.py -k signing_bytes`
- [x] 2.5 Encode an alert
      Done when: the first 151 bytes equal the frozen 215-byte vector
      Verify: `python3 -m pytest tests/test_wire.py -k frozen_vector_prefix`
- [x] 2.6 Decode an alert and verify its signature
      Done when: the Swift-made frozen vector decodes and verifies against the dev public key; the Swift decode tests pass
      Verify: `python3 -m pytest tests/test_wire.py -k decode`
- [x] 2.7 Attack tests
      Done when: moving bytes between headline and action fails; adding an area cell fails
      Verify: `python3 -m pytest tests/test_wire.py -k attack`
- [x] 2.8 Cancellation: signing bytes, encode, decode
      Done when: the first 37 bytes equal the frozen 101-byte vector, and its signature verifies
      Verify: `python3 -m pytest tests/test_wire.py -k cancellation`
- [x] 2.9 Size budget
      Done when: a maximal alert encodes to 370 bytes, within the 383-byte budget
      Verify: `python3 -m pytest tests/test_wire.py -k budget`
- [x] 2.10 Warning draft checks and dev signer
      Swift: `AlertMesh/AlertMesh/Services/OfficialAlertSigning.swift` (`WarningDraft.problems`, `OfficialAlertSigner`)
      Done when: a draft with a problem cannot be signed; a good draft signs and verifies
      Verify: `python3 -m pytest tests/test_signer.py`

## Phase 3 — Community reports

Swift: `AlertMesh/AlertMesh/Protocols/CommunityReportPackets.swift` ·
tests: `AlertMeshTests/AlertMesh/Protocols/CommunityReportPacketsTests.swift`

- [x] 3.1 Kinds, severities, constants
      Done when: values match the spec table
      Verify: `python3 -m pytest tests/test_reports.py -k constants`
- [x] 3.2 Report signing bytes
      Done when: the kind is signed, so an SOS cannot be replayed as "safe"
      Verify: `python3 -m pytest tests/test_reports.py -k signing`
- [x] 3.3 Encode, decode and validate
      Done when: SOS/safe geohash is 7 characters or fewer; lifetime ≤ 24 h hazard, ≤ 6 h SOS/safe
      Verify: `python3 -m pytest tests/test_reports.py -k "encode or validation"`
- [x] 3.4 Sign and verify with the author's own key
      Done when: a changed field fails; a report fits the 383-byte budget (maximal = 344)
      Verify: `python3 -m pytest tests/test_reports.py`

## Phase 4 — Proximity (loud or quiet)

Swift: `AlertMesh/AlertMesh/Services/AlertProximity.swift` ·
tests: `AlertMeshTests/AlertMesh/Services/AlertProximityTests.swift`

- [x] 4.1 `match` for one place
      Done when: inside by prefix; adjacent only at precision 5 or finer; coarse place containing the warning = adjacent
      Verify: `python3 -m pytest tests/test_proximity.py -k match`
- [x] 4.2 `decide` with device location and bookmarks
      Done when: inside + Watch and Act or above = loud; everything else = quiet
      Verify: `python3 -m pytest tests/test_proximity.py -k decide`
- [x] 4.3 Remembered area and unknown location
      Done when: no location = quiet, never silent; remembered area can make it loud, never quieter
      Verify: `python3 -m pytest tests/test_proximity.py`

## Phase 5 — Stores

Swift: `AlertMesh/AlertMesh/Services/OfficialAlertStore.swift`, `AlertMesh/AlertMesh/Services/CommunityReportStore.swift` ·
tests: `OfficialAlertStoreTests.swift`, `CommunityReportStoreTests.swift`

- [x] 5.1 Alert store: accept, duplicate, reject by `issuedAt`
      Done when: newer replaces, equal is a duplicate, older is rejected; bad signature rejected
      Verify: `python3 -m pytest tests/test_alert_store.py -k versions`
- [x] 5.2 Time rules
      Done when: expired dropped; issued more than 1 h in the future dropped; lifetime over 7 days dropped
      Verify: `python3 -m pytest tests/test_alert_store.py -k time`
- [x] 5.3 Cancellations
      Done when: a cancellation removes the alert; a stale one is rejected; an orphan waits; a later alert reinstates
      Verify: `python3 -m pytest tests/test_alert_store.py -k cancel`
- [x] 5.4 500-alert cap
      Done when: the oldest-issued alerts go first
      Verify: `python3 -m pytest tests/test_alert_store.py`
- [x] 5.5 Report store
      Done when: same ID + same author + later time replaces; a stranger cannot mark someone safe
      Verify: `python3 -m pytest tests/test_report_store.py`

## Phase 6 — Places

Swift: `AlertMesh/AlertMesh/Utils/AustralianPlacesData.swift`, `AustralianPlaces.swift` ·
tests: `AlertMeshTests/AlertMesh/Utils/AustralianPlacesTests.swift`

- [x] 6.1 Read the towns straight from the Swift data file
      Done when: 996 towns and 3,396 smaller places load, with coordinates in degrees, all inside Australia
      Verify: `python3 -m pytest tests/test_places.py -k load`
- [x] 6.2 Town lookup and geohash, plus the GeoNames credit
      Done when: known towns give the expected geohash prefix
      Verify: `python3 -m pytest tests/test_places.py -k lookup`
- [x] 6.3 Rough place in words ("Near Katherine", "About 60 km south of Katherine")
      Swift: `AustralianPlaces.describe`, `label(forGeohash:)`, `roundedKm`, `distanceKm`, `compassPoint`
      Done when: the Swift rules and examples give the same answers
      Verify: `python3 -m pytest tests/test_places.py`

## Phase 7 — Mesh simulation (new, no Swift equivalent)

Values from `AlertMesh/Services/TransportConfig.swift` (`messageTTLDefault = 7`).

- [x] 7.1 Phone model: position, internet on/off, Bluetooth range, own stores
      Verify: `python3 -m pytest tests/test_mesh_sim.py -k phone`
- [x] 7.2 One tick: hand packets to phones in range, 7-hop limit
      Verify: `python3 -m pytest tests/test_mesh_sim.py -k ttl`
- [x] 7.3 Only verified packets relay
      Done when: a forged warning never spreads
      Verify: `python3 -m pytest tests/test_mesh_sim.py -k forged`
- [x] 7.4 Moving phones carry warnings
      Done when: a warning reaches a group out of range only after a phone drives there
      Verify: `python3 -m pytest tests/test_mesh_sim.py -k carry`
- [x] 7.5 Phones with internet receive directly
      Verify: `python3 -m pytest tests/test_mesh_sim.py -k internet`
- [x] 7.6 Each phone's loud/quiet decision
      Verify: `python3 -m pytest tests/test_mesh_sim.py -k urgency`
- [x] 7.7 SOS and reports travel through the same mesh
      Verify: `python3 -m pytest tests/test_mesh_sim.py`
- [x] 7.8 Sync sends only what the other phone lacks
      Swift: `GossipSyncManager` (a filter of held packet IDs; the reply holds only what is missing)
      Done when: same results as before, much faster; 500 phones for 1 simulated hour well under the 12 s it took
      Verify: `python3 -m pytest tests/test_mesh_sim.py -k sync`

## Phase 8 — Metrics (new)

- [x] 8.1 Share of phones in the area warned over time
      Verify: `python3 -m pytest tests/test_metrics.py -k coverage`
- [x] 8.2 With mesh vs without mesh
      Verify: `python3 -m pytest tests/test_metrics.py -k compare`
- [x] 8.3 Sweeps over phone density, Bluetooth range, share offline (fixed random seed)
      Verify: `python3 -m pytest tests/test_metrics.py`

## Phase 9 — Notebook (`demo.ipynb`)

Verify each step: `jupyter nbconvert --to notebook --execute demo.ipynb --output /tmp/demo-run.ipynb` runs with no errors.

- [x] 9.1 Issue a signed bushfire warning
- [x] 9.2 A forged or edited warning is rejected
- [x] 9.3 Watch the warning spread on a map
- [x] 9.4 Who gets a loud alert, who gets a quiet one, and why
- [x] 9.5 Update, then cancel, the warning
- [x] 9.6 SOS, then "I'm safe"; a stranger cannot fake "safe"
- [x] 9.7 Community hazard report
- [x] 9.8 Charts: with vs without mesh

## Phase 10 — Streamlit (`app.py`)

Renamed in step 13.7: `app.py` is now `warning_app.py` and `tests/test_app.py` is
`tests/test_warning_app.py`; the Phone view tab was replaced by the phone app (`phone_app.py`).

Verify each step two ways: its headless tests (`tests/test_app.py` runs the page with
Streamlit's test runner, no browser), then `streamlit run app.py` and check the tab by eye.

- [x] 10.1 Warning console tab (write, sign, send)
      Swift: `AlertMesh/AlertMesh/Services/OfficialAlertIssuer.swift`, `AlertMesh/AlertMesh/Views/IssueWarningView.swift`,
      `WarningAreaPicker` in `AlertMesh/AlertMesh/Views/WarningAreaMapView.swift` ·
      tests: `OfficialAlertIssuerTests.swift`, `IssueWarningViewTests.swift`
      Done when: a warning written on the page is signed, goes out over Bluetooth from the evacuation centre and to the internet, and is listed as live; update, send again and cancel work
      Verify: `python3 -m pytest tests/test_console.py tests/test_world.py tests/test_app.py`, then send a warning in the browser
- [x] 10.2 Map tab (phones light up as the warning spreads)
      Swift: none (the simulation view is new); it uses the step 9.3 map
      Done when: a sent warning's spread shows on the map with its area and the evacuation centre; "Let N minutes pass" records every minute and ▶ plays them; the counts match the phones
      Verify: `python3 -m pytest tests/test_world.py tests/test_app.py -k "map or spread or play"`, then send a warning and play 10 minutes in the browser
- [x] 10.3 Phone view tab (one phone's alerts and the loud/quiet reason)
      Swift: `AlertMesh/AlertMesh/Services/AlertNotificationContent.swift`, `SOSNotificationContent.swift`;
      screens `AlertsView.swift`, `CommunityReportsView.swift`, `SOSView.swift` ·
      tests: `AlertNotificationContentTests.swift`, content tests in `SOSNotificationsModelTests.swift`
      Done when: a chosen phone lists its warnings with "how close", why it is loud or quiet, and the notification it showed; its settings change what it decides; it can send a call for help, "I'm safe" and a hazard report
      Verify: `python3 -m pytest tests/test_notifications.py tests/test_world.py tests/test_app.py`, then check a phone in the browser
- [x] 10.4 Hub board tab (large-type board with the SOS list)
      Swift: `AlertMesh/AlertMesh/Views/HubBoardView.swift` · tests: `HubBoardViewTests.swift`
      Done when: the most serious live warning is in large type with up to 3 more under it, the footer counts devices nearby and any warnings that did not fit, and calls for help the centre heard are listed
      Verify: `python3 -m pytest tests/test_hub.py tests/test_world.py tests/test_app.py`, then check the board in the browser

## Phase 11 — Final check

- [x] 11.1 Cross-check with Swift: Python decodes a packet made by `scripts/sign-test-alert.swift`
      Swift: `scripts/sign-test-alert.swift` (signs); CryptoKit via `tools/verify_signature.swift` (verifies)
      Done when: fresh Swift-signed warnings and a cancellation decode, verify and match Python's bytes up to the signature; Python's signatures pass CryptoKit and a flipped bit fails
      Verify: `python3 tools/cross_check_swift.py` (Mac with Swift), or `python3 -m pytest tests/test_cross_check.py`
- [x] 11.2 README walk-through in a fresh clone
      Done when: in a fresh clone with a new environment, every README command works as written: install, tests, notebook, live page, cross-check
      Verify: clone the branch, follow README "Set up" and "Run" word for word
- [x] 11.3 `git status` shows no change under `alert-mesh/`
      Done when: no commit since the port began touches `alert-mesh/`, and the working tree has no change there
      Verify (from the repository root; 6ca96ca is the commit before step 0.1):
      `git diff --name-only 6ca96ca..HEAD -- alert-mesh`, `git log --oneline 6ca96ca..HEAD -- alert-mesh`
      and `git status --porcelain -- alert-mesh` all print nothing

## Phase 12 — Desktop app (no browser)

Added after Phase 11, at the user's request: a double-click app that shows the live
demo page in its own window, with no browser and no Python needed on the computer
that runs it. A launcher (`desktop.py`) runs the page in the background and shows it
with `pywebview`; `PyInstaller` bundles everything. Built and tested on a Mac (Apple
Silicon); the Windows build script cannot be tested on a Mac.

- [x] 12.1 Town list found inside the app
      Done when: development still reads the Swift app's file; with no Swift folder next to the package, a copy in `alertmesh/data/` is read; the error names every place looked
      Verify: `python3 -m pytest tests/test_places.py`
- [x] 12.2 Desktop launcher (`desktop.py`)
      Done when: `python desktop.py` opens a native window showing the page, served on 127.0.0.1 only; closing the window stops the server
      Verify: `python3 -m pytest tests/test_desktop.py`, then run `desktop.py` with the build tools installed and check by eye
- [x] 12.3 Mac app (`packaging/build_mac.sh`)
      Done when: the script builds `dist/Alert Mesh.app` and a zip; a copy opened outside the repo shows all four tabs working; quitting leaves no process
      Verify: `packaging/build_mac.sh`, then open a copy of the app from another folder
- [!] 12.4 Windows build script (`packaging/build_windows.ps1`) — blocked: written, but needs a Windows PC to run and check
      Done when: the script builds `dist\Alert Mesh\Alert Mesh.exe` and a zip on a Windows PC, and the app opens and works there
      Verify (on Windows): `powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1`, then open the .exe
- [x] 12.5 README: building the app, and opening it on another computer
      Done when: the README says how to build on each system and how to get past the first-open warnings
      Verify: read it against what was actually run

---

## Phase 13 — Two apps: phone app and warning app

Added after Phase 12, at the user's request, to make the prototype work like the iPhone
app: a **phone app** for texting people nearby, reading warnings and calling for help,
and a separate, simple **warning app** that sends warnings. The phone app has the
iPhone's three tabs (Now, Report, Chat) and talks to other laptops over real
Bluetooth; the warning app keeps the Warning console, Map and Hub board, and reaches
phone apps over the local Wi-Fi network. The Bluetooth format is our own: laptops talk
to laptops, not to iPhones.

- [x] 13.1 Bluetooth trial (`tools/ble_probe.py`)
      Swift: `AlertMesh/Services/BLE/BLEService.swift` (central + peripheral roles)
      Done when: on this Mac the probe advertises the Alert Mesh service and a scan finds nearby devices, with no error
      Verify: `python3 tools/ble_probe.py` from a program allowed to use Bluetooth (see the file)
- [x] 13.2 Chat messages (`alertmesh/chat.py`)
      Swift: `localPackages/BitFoundation/Sources/BitFoundation/MessageType.swift` (`message`, `noiseEncrypted`), `AlertMesh/Services/PrivateChatManager.swift`
      Done when: a signed Nearby message and an encrypted private message round-trip; a changed message, a wrong key and oversize text are refused
      Verify: `python3 -m pytest tests/test_chat.py`
- [x] 13.3 Mesh node (`alertmesh/node.py`)
      Swift: `AlertMesh/Services/BLE/BLEService.swift` (relay with TTL), `AlertMesh/Services/MessageDeduplicationService.swift`
      Done when: with a fake radio, A's message reaches C through B, never loops, stops at TTL 0, is shown once; SOS and warnings go through the existing stores; a forged warning is refused
      Verify: `python3 -m pytest tests/test_node.py`
- [!] 13.4 Bluetooth link (`alertmesh/ble.py`) — blocked: built and tested on one Mac; the two-laptop check needs a second computer
      Swift: `AlertMesh/Services/BLE/BLEService+LinkLayerCentralRole.swift`, `BLEService+LinkLayerPeripheralRole.swift`
      Done when: messages are cut into Bluetooth-sized pieces and put back together; two laptops running the phone app see each other and chat
      Verify: `python3 -m pytest tests/test_ble.py`; then the two-laptop check in the README
- [x] 13.5 Wi-Fi link (`alertmesh/lan.py`)
      Swift: `AlertMesh/AlertMesh/Services/OfficialAlertBridge.swift` (warnings over the internet)
      Done when: a warning sent on the local network arrives and is repeated; junk and oversize packets are ignored; packets do not leave the local network
      Verify: `python3 -m pytest tests/test_lan.py`
- [x] 13.6 Phone app (`phone_app.py`)
      Swift: `AlertMesh/AlertMesh/Views/EmergencyRootView.swift`, `NowView.swift`, `CommunityReportsView.swift`, `SOSView.swift`, `ChatInboxView.swift`
      Done when: Now, Report and Chat tabs work: a typed message appears and is sent; an incoming one raises the unread count; a call for help is sent
      Verify: `python3 -m pytest tests/test_phone_app.py`
- [x] 13.7 Warning app (`warning_app.py`)
      Swift: `AlertMesh/AlertMesh/Services/OfficialAlertIssuer.swift`, `AlertMesh/AlertMesh/Views/IssueWarningView.swift`
      Done when: the warning app has the Warning console, Map and Hub board; each warning, update and cancellation is also sent on the local network
      Verify: `python3 -m pytest tests/test_warning_app.py tests/test_console.py`
- [ ] 13.8 Two desktop apps
      Done when: `packaging/build_mac.sh` builds and checks `Alert Mesh.app` and `Alert Mesh Warnings.app`; a warning sent from one reaches the other on the same Mac
      Verify: `packaging/build_mac.sh`, then open both apps
- [ ] 13.9 README: the two apps and the two-laptop check
      Done when: the README says how to run both apps, what needs Wi-Fi and what needs Bluetooth, and how to test with two laptops
      Verify: read it against what was actually run

---

## Rules for every step

1. Mark the step `[~]`. Read the Swift file it names, and its Swift tests.
2. Write the Python code. Port the matching Swift test cases.
3. Run the step's **Verify** command. It must pass. Also run `python3 -m pytest -q` so
   nothing else broke.
4. Tick the box `[x]`, then run `python3 tools/update_status.py` to recount the Status
   table and **Next step**. Add a [`CHANGELOG.md`](CHANGELOG.md) entry.
5. Commit only that step's files, with a message that explains why.
