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
| 13 Two apps: phone app and warning app | 8 | 9 |
| 14 Desktop look: the iPhone app's style, on Mac and Windows | 6 | 7 |
| 15 Internet link: warnings and calls for help reach iPhones | 8 | 9 |
| 16 One Bluetooth mesh with iPhones | 3 | 10 |
| **All** | **87** | **98** |

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
- [x] 13.8 Two desktop apps
      Done when: `packaging/build_mac.sh` builds and checks `Alert Mesh.app` and `Alert Mesh Warnings.app`; a warning sent from one reaches the other on the same Mac
      Verify: `packaging/build_mac.sh`, then open both apps
- [x] 13.9 README: the two apps and the two-laptop check
      Done when: the README says how to run both apps, what needs Wi-Fi and what needs Bluetooth, and how to test with two laptops
      Verify: read it against what was actually run

---

## Phase 14 — Desktop look: the iPhone app's style, on Mac and Windows

Added after Phase 13, at the user's request: both desktop apps take the iPhone app's
style (system typeface, system blue, rounded grey cards, the red "I need help" bar,
chat bubbles), with one layout that works on Mac and on Windows. The design, with the
Swift source of every rule, is in [`docs/desktop-design.md`](docs/desktop-design.md);
a clickable mockup is in [`docs/desktop-design-mockup.html`](docs/desktop-design-mockup.html).
How each page looks is checked by eye against the mockup, in light and dark.

- [x] 14.1 Colours, system typeface and dark mode for both apps
      Swift: `AlertMesh/Utils/Theme.swift` (`ThemePalette.alertMesh`), `AlertMesh/AlertMesh/Views/EmergencyLayout.swift`, `AlertMesh/AlertMesh/Views/ChatBubbleRow.swift` (`ChatBubbleStyle`)
      Done when: both apps use the system typeface and the iPhone app's light and dark colours, and follow the system's light or dark setting; one shared stylesheet holds the colours; `theme.base = "light"` is gone from `.streamlit/config.toml` and `desktop.py`
      Verify: `python3 -m pytest -q`; then run both apps in light and in dark and compare with the mockup
- [x] 14.2 Phone app sidebar, status bar and "I need help" bar
      Swift: `AlertMesh/AlertMesh/Views/EmergencyRootView.swift` (tabs, badges, `EmergencyHelpBarModifier`)
      Done when: Now, Report and Chat are in a sidebar with red count badges; nickname and town are at its foot and open Settings; a status bar shows Bluetooth and the local network on every tab; the red "I need help" bar is pinned to the bottom of Now; the window opens at 1200 × 760 and cannot be made smaller than 960 × 600; below 1100 wide the sidebar shows icons only
      Verify: `python3 -m pytest tests/test_phone_app.py tests/test_desktop.py`; then check by eye at 1280 and 960 wide
- [x] 14.3 Now like the iPhone
      Swift: `AlertMesh/AlertMesh/Views/NowView.swift` (status block, "What to do", other warnings, "How you're connected"), `NowReportsSections.swift` (calls for help)
      Done when: a solid colour block appears only when a warning covers your town; otherwise a grey "No current warnings" or "No warnings where you are" card; then "What to do", calls for help, other warnings with a colour bar and symbol, and "How you're connected"; on a wide window calls for help and the connection card sit in a side column
      Verify: `python3 -m pytest tests/test_phone_app.py`
- [x] 14.4 Report, Chat and the call-for-help sheet like the iPhone
      Swift: `AlertMesh/AlertMesh/Views/CommunityReportsView.swift`, `CommunityReportStyle.swift`, `SOSView.swift`, `ChatBubbleRow.swift`
      Done when: hazard reports are grey and calls for help red; chat shows bubbles (yours blue on the right, others grey on the left, name above the first of a run, time under the last); "I need help" opens a sheet with the iPhone's wording, its main button last on a Mac and first on Windows
      Verify: `python3 -m pytest tests/test_phone_app.py`
- [x] 14.5 Warning app in the same style
      Swift: `AlertMesh/AlertMesh/Views/IssueWarningView.swift`, `HubBoardView.swift`
      Done when: Console, Map and Hub board are in a sidebar with the simulated clock at its foot; the console has the form on the left and the phone preview and live warnings on the right; the Hub board stays black in light mode
      Verify: `python3 -m pytest tests/test_warning_app.py`; then check by eye
- [x] 14.6 Keyboard shortcuts
      Done when: ⌘1–3 or Ctrl+1–3 switch tabs, ⌘, or Ctrl+, opens Settings, ⌘⇧H or Ctrl+Shift+H opens the call-for-help sheet without sending; hints show ⌘ on a Mac and Ctrl on Windows
      Verify: `python3 -m pytest -q`; then press each shortcut in both packaged apps
- [!] 14.7 Check on Windows — blocked: needs a Windows PC (as 12.4)
      Done when: both apps built on a Windows PC look like the mockup at 100%, 125% and 150% display scaling
      Verify (on Windows): `powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1`, then open both apps

---

## Phase 15 — Internet link: warnings and calls for help reach iPhones

Added after Phase 14, at the user's request, so the Python apps and the iPhone app share
warnings and calls for help. The iPhone app already carries both over the internet on
Nostr, a public network of relay servers: official warnings as kind 1403 events, calls
for help and "I'm safe" as kind 1402. Each event holds the warning or report in its own
signed format, which the Python port already reads and writes byte for byte. This
phase adds the same Nostr link to the Python apps. The warning app then reaches every
iPhone with Alert Mesh (a Debug build, which trusts the development key) and internet,
anywhere; phone apps and iPhones see each other's calls for help.

Anything sent this way goes to public servers that anyone can read, so the link is a
switch in each app, **off** until turned on. The tests never use the real relays.

- [x] 15.1 Nostr events: BIP-340 signatures and event IDs (`alertmesh/nostr.py`)
      Swift: `AlertMesh/Nostr/NostrProtocol.swift` (`NostrEvent.sign`, `calculateEventId`, `isValidSignature`), `AlertMesh/Nostr/NostrIdentity.swift`
      Done when: an event is made, given its ID and signed with a fresh key each time, and checked, the way the Swift app does; BIP-340 signing matches the published test vector; no new library is needed for it
      Verify: `python3 -m pytest tests/test_nostr.py`
- [x] 15.2 Warning and report events
      Swift: `AlertMesh/AlertMesh/Services/OfficialAlertBridge.swift`, `CommunityReportBridge.swift` (`tagCells`, `makeEvent`, `payload`, `versionKey`); `AlertMesh/Nostr/NostrRelayManager.swift` (`NostrFilter.officialAlerts`, `communityReports`, built-in relays)
      Done when: a warning or cancellation becomes a kind 1403 event tagged with every 2- to 4-character prefix of its area and its expiry; an SOS or "I'm safe" becomes a kind 1402 event tagged with its 4-character cell; hazard reports are never sent; the Swift bridge tests are ported
      Verify: `python3 -m pytest tests/test_nostr.py`
- [x] 15.3 Geo relays: the relays nearest a place (`alertmesh/georelays.py`)
      Swift: `AlertMesh/Nostr/GeoRelayDirectory.swift` (`validatedEntries`, `validatedDirectoryAddress`, `closestRelays`), `AlertMesh/AlertMesh/Utils/AustralianAreas.swift`, `relays/online_relays_gps.csv`
      Done when: the relay list is read from the Swift app's copy (or the one packed into the app) and, with the internet on, from the same address the iPhone app downloads it from, with the same all-or-nothing checks; the 5 relays nearest a cell come out as the iPhone app picks them, because calls for help go to those relays, not to the built-in ones
      Verify: `python3 -m pytest tests/test_georelays.py`
- [x] 15.4 Relay link (`alertmesh/relays.py`)
      Swift: `AlertMesh/Nostr/NostrRelayManager.swift` (connect, publish, subscribe, reconnect)
      Done when: the link connects to each relay, publishes, subscribes, hands every event to a handler, reconnects after a drop, and reports how many relays are connected; tested against a relay run inside the tests
      Verify: `python3 -m pytest tests/test_relays.py`
- [x] 15.5 Warning app sends warnings over the internet
      Swift: `AlertMesh/AlertMesh/Services/OfficialAlertBridge.swift` (`publish`), `AlertMesh/App/AppRuntime.swift`
      Done when: with "Send over the internet" on, every warning, update and cancellation from the console is published to the built-in relays and the geo relays of its area, as the Mac console does; a cancellation carries its warning's area and expiry; the status bar says how many relays took it; off by default
      Verify: `python3 -m pytest tests/test_relays.py tests/test_warning_app.py`
- [x] 15.6 Phone app: warnings and calls for help from the internet
      Swift: `OfficialAlertBridge.swift` (`refreshSubscription`, `receive`), `CommunityReportBridge.swift` (`publishIfNew`, `refreshSubscription`, `receive`)
      Done when: with "Use the internet" on in Settings, the phone app takes every warning from the relays (checked against the development key), takes calls for help and "I'm safe" around its town from the geo relays there and passes them on over Bluetooth, and puts its own and heard calls for help online once each, on the geo relays of their cell; "How you're connected" shows the internet
      Verify: `python3 -m pytest tests/test_node.py tests/test_phone_app.py`
- [x] 15.7 Live check with the real relays
      Done when: the real relays accept an event signed here (a short-lived test kind that relays do not keep); a test warning published the warning app's way reaches a phone app's link over the real relays and is cancelled; a test call for help goes from one phone app's link to another and is answered with "I'm safe"
      Verify: `python3 tools/nostr_live_check.py --warning --sos` (from a Python with websockets)
- [ ] 15.8 Check with an iPhone
      Done when: a warning from the warning app shows on an iPhone running the Debug build; a call for help from the phone app shows on the iPhone, and one from the iPhone on the phone app
      Verify: by hand, with the user's iPhone
- [x] 15.9 README and wrap-up
      Done when: the README explains the switches, what goes to public servers, and the iPhone check; packaged apps rebuilt
      Verify: `python3 -m pytest -q`; `python3 desktop.py --check` and `--app warning --check`

---

## Phase 16 — One Bluetooth mesh with iPhones

Added after Phase 15, at the user's request. The phone app's Bluetooth used its own
format, so iPhones running Alert Mesh ignored laptops and laptops ignored iPhones. This
phase makes the phone app speak the iPhone app's (bitchat's) Bluetooth format, so
laptops and iPhones share one mesh with no internet: they see each other nearby, chat
in public, and pass warnings, calls for help, "I'm safe" and hazard reports along.

Only the unencrypted parts are matched. iPhones encrypt private messages with Noise,
which the laptops do not speak: private chat stays **between laptops only** (the user's
choice), under a packet type iPhones do not know and relay unread. Laptops with this
phase and laptops without it do not see each other over Bluetooth (different service
IDs); Wi-Fi and the internet are unaffected.

The iPhone's rules are in `../alert-mesh/localPackages/BitFoundation/` (the packet) and
`../alert-mesh/AlertMesh/Services/BLE/` (the link). Step 15.8, the check with an
iPhone, is done with step 16.10.

- [x] 16.1 Packet codec (`alertmesh/bitchat.py`)
      Swift: `localPackages/BitFoundation/Sources/BitFoundation/BinaryProtocol.swift`, `BitchatPacket.swift`, `MessagePadding.swift`, `CompressionUtil.swift`, `PeerID.swift`
      Done when: packets are encoded and decoded as the iPhone app does (header, flags, sender and recipient, compression, padding); the signed bytes are built as the iPhone builds them (TTL 0, no signature, padded, compressed when due), and a received packet's signature is checked from its own bytes; peer ID = the first 8 bytes of SHA-256 of the X25519 key; the Swift test cases are ported
      Verify: `python3 -m pytest tests/test_bitchat.py`
- [x] 16.2 Cross-check with Swift
      Done when: a small Swift package built on the app's BitFoundation decodes and verifies packets made in Python, and Python decodes and verifies packets made in Swift; Python's compression is compared with Apple's, and the answer is kept as test data that the apps check when they start (if they differ, messages stay under 100 bytes, where nothing is compressed)
      Verify: `python3 tools/cross_check_bitchat.py` (Mac with Swift)
- [x] 16.3 Announce, leave, catch-up request, fragments
      Swift: `AlertMesh/Protocols/Packets.swift` (announce), `AlertMesh/Models/RequestSyncPacket.swift`, `AlertMesh/Services/BLE/BLEOutboundFragmentPlanner.swift`, `BLEFragmentAssemblyBuffer.swift`, `AlertMesh/Services/NotificationStreamAssembler.swift`
      Done when: announces (nickname, X25519 key, Ed25519 key, and our "laptop" marker the iPhone skips), leave and catch-up requests are made and read; long packets are cut into fragments and put back together; a stream of notifications is cut back into packets
      Verify: `python3 -m pytest tests/test_bitchat.py`
- [ ] 16.4 Early check with an iPhone (`tools/ble_probe.py`)
      Done when: the probe connects to an iPhone running Alert Mesh (Debug build), prints the iPhone's announce and messages, and the laptop's name and a long message show on the iPhone
      Verify: by hand, with the user's iPhone
- [ ] 16.5 The mesh node on the iPhone's packets
      Swift: `AlertMesh/Services/BLE/BLEService.swift` (receive and relay), `BLEIngressPacketGuard.swift`, `BLEAnnounceHandlingPolicy.swift`, `BLEPublicMessagePolicy.swift`, `BLEReceivePipeline.swift`, `AlertMesh/Services/RelayController.swift`
      Done when: `alertmesh/node.py` sends and takes the iPhone's packets: announces every 15 seconds or so and at once on a new link; public chat as plain text checked against the sender's announced key; warnings and reports as before; laptop-only private messages under their own type; leave; the iPhone's checks (clock within 2 minutes, duplicates, announce rules); relaying as the iPhone does
      Verify: `python3 -m pytest tests/test_node.py tests/test_internet.py tests/test_phone_app.py`
- [ ] 16.6 Phone app: iPhones and laptops in one list
      Done when: Chat lists iPhones and laptops nearby by name; "Message" is offered only for laptops; the message limit follows step 16.2
      Verify: `python3 -m pytest tests/test_phone_app.py`
- [ ] 16.7 Bluetooth link in both roles (`alertmesh/ble.py`)
      Swift: `AlertMesh/Services/BLE/BLEService+LinkLayerPeripheralRole.swift`, `BLEService+LinkLayerCentralRole.swift`
      Done when: the laptop uses the iPhone app's service and characteristic, sends to connected devices by writing and to subscribed devices by notifying, keeps its connections open and subscribes to them, and sends one whole packet per write or notification
      Verify: `python3 -m pytest tests/test_ble.py`
- [ ] 16.8 Fragments per link, and new links
      Swift: `AlertMesh/Services/BLE/BLEOutboundLinkPlanner.swift`, `BLEOutboundPacketPolicy.swift`
      Done when: the Bluetooth process cuts a packet into fragments when a link cannot carry it whole; the laptop count is the live links; a new link makes the node announce at once
      Verify: `python3 -m pytest tests/test_ble.py tests/test_node.py`
- [ ] 16.9 Catching up from iPhones
      Swift: `AlertMesh/Sync/GossipSyncManager.swift`, `AlertMesh/Sync/RequestSyncManager.swift`
      Done when: soon after a new link the laptop asks for the warnings and reports the other device holds, and takes the answers (which carry old times) only within 30 seconds of asking
      Verify: `python3 -m pytest tests/test_node.py`
- [ ] 16.10 Check with an iPhone, README, rebuild
      Done when: with an iPhone running the Debug build: each lists the other; public chat both ways; a warning from the warning app reaches the iPhone through a laptop; a call for help goes both ways; a laptop that arrives late gets a warning the iPhone holds; private chat still works between laptops; the README explains it all; the packaged apps are rebuilt
      Verify: by hand; `python3 desktop.py --check` and `--app warning --check`

---

## Rules for every step

1. Mark the step `[~]`. Read the Swift file it names, and its Swift tests.
2. Write the Python code. Port the matching Swift test cases.
3. Run the step's **Verify** command. It must pass. Also run `python3 -m pytest -q` so
   nothing else broke.
4. Tick the box `[x]`, then run `python3 tools/update_status.py` to recount the Status
   table and **Next step**. Add a [`CHANGELOG.md`](CHANGELOG.md) entry.
5. Commit only that step's files, with a message that explains why.
