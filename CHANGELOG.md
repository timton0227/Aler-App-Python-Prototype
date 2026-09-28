# Changelog — Swift to Python port

One entry per step in [`PROGRESS.md`](PROGRESS.md), newest first.

Every commit subject starts with its step number, for example `[py 2.5] ...`. To find
the commit for a step, run:

```bash
git log --oneline --grep '^\[py 2.5\]'
```

Entry format:

```
## <step> <title> — <date>
- What: what was added or changed.
- Ported from: the Swift file and function (paths relative to ../alert-mesh/), or "new".
- Differences from Swift: "none", or each difference and why.
- Verified by: the command that was run, and its result.
```

**Differences from Swift** is how the port stays honest. Write down anything that is
simplified, left out, or behaves differently from the app.

---

## 15.2 Warning and report events — 2026-09-28
- What: in `alertmesh/nostr.py`, how warnings and calls for help travel as Nostr events.
  - `alert_event`: a warning or cancellation, its signed bytes in base64, as a kind 1403 event. It is tagged with every 2- to 4-character prefix of its area cells and with its expiry (a cancellation carries its warning's area and expiry).
  - `report_event`: a call for help or "I'm safe" as a kind 1402 event, tagged with its 4-character cell and expiry. `is_bridged` keeps hazard reports off the internet.
  - `payload_of` takes the signed bytes back out, refusing other kinds, content over 1024 bytes and broken base64. The signature inside is checked by the stores, as before.
  - `alert_version_key` and `report_version_key`, so each version is handed on once.
  - `official_alerts_filter` (every warning, anywhere) and `community_reports_filter` with `report_cells` (the 4-character cells around a place, with their neighbours).
  - `BUILT_IN_RELAYS`, the iPhone app's four relays; `ALERTMESH_NOSTR_RELAYS` names others (the tests use it).
- Also: `PROGRESS.md` gains step 15.3, geo relays. Reading the Swift code for this step showed that the iPhone app sends calls for help to the 5 relays nearest the caller's area, not to the built-in ones, so the Python apps must pick relays the same way. The later steps are renumbered.
- Ported from: `AlertMesh/AlertMesh/Services/OfficialAlertBridge.swift` and `CommunityReportBridge.swift` (`tagCells`, `makeEvent`, `payload`, `versionKey`, `isBridged`, the cells in `refreshSubscription`); `AlertMesh/Nostr/NostrRelayManager.swift` (`builtInRelays`, `NostrFilter.officialAlerts`, `communityReports`). Tests from `OfficialAlertBridgeTests.swift` and `CommunityReportBridgeTests.swift`, the parts about the events themselves.
- Differences from Swift: none in the events. The bridges' state (what was already sent, the subscriptions) comes in steps 15.5 and 15.6.
- Verified by: `python3 -m pytest tests/test_nostr.py` — 35 passed; `python3 -m pytest -q` — 508 passed.

## 15.1 Nostr events: BIP-340 signatures and event IDs — 2026-09-28
- What: `alertmesh/nostr.py`, the envelope the internet link sends and receives.
  - `schnorr_sign`, `schnorr_verify` and `public_key`: BIP-340 signatures on the secp256k1 curve, written out in plain Python after the BIP's reference code, so no new library is needed.
  - `Event`, `sign_event` and `event_hash`: a Nostr event, its ID (the SHA-256 of the fields written the NIP-01 way) and its signature, made with a fresh key for every event.
  - `Event.from_dict` reads an event from a relay and refuses one with too many or too long tags, or fields of the wrong type.
- Ported from: `AlertMesh/Nostr/NostrProtocol.swift` (`NostrEvent.sign`, `calculateEventId`, `isValidSignature`, `isWithinInboundTagLimits`), `AlertMesh/Nostr/NostrIdentity.swift` (`generate`); tests from `AlertMeshTests/NostrProtocolTests.swift`.
- Differences from Swift:
  - The Swift app uses the secp256k1 C library (through P256K). Plain Python is slower (about 30 ms to sign) and not constant-time. Neither matters here: the app signs a few events, and each key signs one event and is thrown away.
  - `from_dict` also refuses fields of the wrong type; Swift's decoder does that on its own.
- Verified by:
  - `python3 -m pytest tests/test_nostr.py` — 21 passed. They include BIP-340's test vector 0 (the exact signature) and two events signed by other apps, frozen in the Swift tests: one by the Android app and one by an older iPhone release. Both verify here.
  - `python3 -m pytest -q` — 494 passed.

## 14.7 Check on Windows — blocked — 2026-09-27
- What: not done; it needs a Windows PC, as step 12.4 does. Marked `[!]` in `PROGRESS.md`.
- Also in this commit, to close the rest of Phase 14:
  - the README describes the new look: the Settings sheet, the status bar, the "I need help" bar, dark mode, the shortcuts and the window sizes;
  - `docs/desktop-design.md` says what is built;
  - `requirements.txt` caps Streamlit at the newest version tested (`<1.65`), because the stylesheet styles some of Streamlit's own parts, which can change in a new version (the design's Risks section).
- Ported from: not applicable.
- Differences from Swift: not applicable.
- Verified by: `python3 -m pytest -q` — 470 passed, 2 skipped; `python3 desktop.py --check` and `--app warning --check` report ok.

## 14.6 Keyboard shortcuts — 2026-09-27
- What:
  - Both apps: ⌘1, ⌘2, ⌘3 switch tabs (Ctrl+1 to 3 on Windows).
  - Phone app:
    - ⌘, opens Settings;
    - ⌘⇧H opens the call-for-help sheet, going to Now first if needed (Ctrl+, and Ctrl+Shift+H on Windows).
    - Like the iPhone, the shortcut only opens the sheet: nothing is sent until "Send call for help" is pressed.
  - `alertmesh/style.py`:
    - `shortcuts()` puts a small script on the page that presses the page's own buttons, found by their keys;
    - `shortcut_label()` writes a shortcut the system's way (⌘ and ⇧ on a Mac, Ctrl+ and Shift+ on Windows);
    - a line under the tabs gives their shortcuts ("⌘1 to ⌘3 switch tabs"), and the Settings and "I need help" tooltips give theirs. The tabs have no tooltip: a tab's tooltip covered the tab above it while the pointer moved there (found in the browser check).
  - Newer Streamlit runs the script in the page itself. Streamlit 1.51 has no way to do that, so it runs in a hidden frame that reaches up to the page.
- Ported from: new. The iPhone has no keyboard shortcuts. The list is from `docs/desktop-design.md`, "Keyboard".
- Differences from Swift: not applicable.
  - Not built:
    - Hub board full screen (⌃⌘F, F11): the window belongs to pywebview, not to the page.
    - The Mac menu bar entries for these shortcuts.
  - Built in already: Esc closes a sheet and Return sends a message (Streamlit's own).
- Verified by:
  - `python3 -m pytest tests/test_style.py` — 13 passed (2 new: labels on a Mac and on Windows, and the script carries each binding).
  - `python3 -m pytest -q` — 470 passed, 2 skipped.
  - Pressed in headless Chromium with Streamlit 1.64 and 1.51 (Linux, so Ctrl):
    - phone app: Ctrl+2 goes to Report, Ctrl+3 to Chat, Ctrl+Shift+H from Chat goes to Now and opens the call-for-help sheet, Ctrl+, opens Settings with the nickname filled in;
    - warning app: Ctrl+3 goes to Hub board, Ctrl+2 to Map.
  - ⌘ on a Mac and the packaged apps' windows have not been pressed yet.

## 14.5 Warning app in the same style — 2026-09-27
- What:
  - Warning console, Map and Hub board are tabs in the sidebar, like the phone app's.
  - The simulated clock and its +1, +5 and +15 minute buttons sit at the sidebar's foot. "Build a new town" is folded into a "Simulated town" section under the tabs.
  - A status bar says whether the local network is on and that warnings are signed with the development key.
  - Console:
    - the result of the last send at the top, in its usual wording;
    - the form on the left;
    - on the right: the warning as phones in the area show it (the solid block and "What to do", as on Now), the area map, and the live warnings as grey cards with a colour bar, with Update…, Send again and a red Cancel warning.
    The confirm and cancel prompts put their buttons in the system's order.
  - Hub board (`alertmesh/hub.py`): black whatever the system's light or dark setting, with the iPhone app's dark colours: the fills on the hero and row bars, the text colours for level names. Rows are dark grey cards; calls for help are in a red-bordered card.
- Ported from: `IssueWarningView.swift` (console layout and preview), `HubBoardView.swift` (the board), as written down in `docs/desktop-design.md`.
- Differences from Swift:
  - The console's preview shows the block a phone *in* the area shows. The Mac console's preview is its own card.
  - The Hub board used to be black text on white, chosen for projectors. The design moves it to black, with colours made for a dark background.
- Verified by:
  - `python3 -m pytest tests/test_warning_app.py tests/test_hub.py` — 23 passed (2 new: the preview block, the black board with dark colours). The tab tests now switch pages with the sidebar buttons, since only the open page is drawn. The clock test also checks the sidebar's minute.
  - `python3 -m pytest -q` — 468 passed, 2 skipped. The page tests also pass with Streamlit 1.51.0.
  - Checked by eye in headless Chromium, in light and dark:
    - wrote and sent an Emergency Warning;
    - saw the preview, the live warning with its red Cancel, and the black Hub board.

## 14.4 Report, Chat and the call-for-help sheet like the iPhone — 2026-09-27
- What:
  - **Call for help**: "I need help" opens a sheet with the iPhone's wording:
    - how a call for help travels;
    - "This is not 000…" in red;
    - that it says you are in the town picked in Settings, because a laptop has no GPS;
    - an optional note.
    The main button is red and sits last on a Mac and first on Windows (`style.button_order`). While your call for help is out, the sheet offers "Send it again" and "I'm safe now", each with what it does. Your own call for help also stays on Now, in the red call-for-help style.
  - **Report**: the form is on the left:
    - Type;
    - How bad, as three buttons with symbols, the chosen one blue;
    - the note;
    - "Send report" with where it is sent from.

    "From people nearby" is on the right. Calls for help are red; hazard reports and "I'm safe" are grey cards with their own symbol. The line underneath says these are not official warnings and nobody has checked them.
  - **Chat**:
    - The list has "Chats", Nearby first with unread counts in blue, and "People nearby".
    - The conversation says who can read it.
    - Messages are bubbles as in Messages, from `style.bubbles()`: yours blue on the right, theirs grey on the left, the name above the first of a run, the time under the last.
    - The message box is rounded.
- Ported from: `SOSView.swift` (English strings: `sos.body`, `sos.not_emergency_services`, `sos.active.*`, `sos.resend*`, `sos.safe*`), `CommunityReportsView.swift` and `CommunityReportStyle.swift`, `ChatBubbleRow.swift` (`ChatBubbleStyle`), as written down in `docs/desktop-design.md`.
- Differences from Swift:
  - "Phone" is "laptop" in the wording. `sos.location_note` (150 metres) is replaced by the town line, because a laptop has no GPS.
  - A run of bubbles ends when the sender changes or after 5 minutes' silence. The Swift grouping was not checked for this step.
  - "How bad" is three buttons, not a segmented control: Streamlit's segmented control cannot be driven by the 1.51 test runner.
  - There is no live byte count while typing a message; `st.chat_input` does not report typing. The "at most 280 bytes" message after sending stays.
  - The chat list shows names only, with no last-message preview.
- Verified by:
  - `python3 -m pytest tests/test_phone_app.py tests/test_style.py` — 43 passed (6 new). They cover:
    - the sheet opens without sending, sends, closes, and Cancel sends nothing;
    - button order on Mac and Windows;
    - "I'm safe now" from the sheet;
    - calls for help red and hazard reports grey;
    - bubble runs and escaping.
    - Report and Chat checks now read the drawn cards and bubbles.
  - `python3 -m pytest -q` — 466 passed, 2 skipped. The page tests also pass with Streamlit 1.51.0.
  - Checked by eye in headless Chromium: the sheet, Report and Chat in light and dark, against the mockup.

## 14.3 Now like the iPhone — 2026-09-27
- What:
  - `alertmesh/phone.py`: `now_status()` decides what the top of Now shows:
    - `CLEAR`, no live warnings;
    - `ELSEWHERE`, warnings but none covering you;
    - `AFFECTED`, the most severe warning whose area you are in, with every other warning listed after it.
    "Covers you" means "You are in this area"; next to the area stays in the list.
  - `phone_app.py`, Now from top to bottom:
    1. A solid block in the level's colour, only when a warning covers you: symbol, level, "You are in this area", headline, hazard, end time, and "Open full warning". Otherwise a grey card: "No current warnings" in the all-clear green, or "No warnings where you are" with how many are listed below.
    2. "What to do", in large type in a card with a border in the level's colour.
    3. Other warnings: grey cards with a 6-point colour bar and the level in its text colour, each able to open in full.
    4. In a side column: calls for help (red-bordered, "Message" when that person is in range), and "How you're connected" in plain counts.
  - Below 1100 wide the side column moves under the main one.
  - "Open full warning" opens a sheet with the whole warning, why the app was loud or quiet, when it was issued and its area.
  - Your own call for help, when out, stays at the top of Now.
- Ported from: `NowView.swift` (the status and `affectedBlock`, "What to do", other warnings, `connectionSection`), `NowReportsSections.swift` (calls for help), `AlertSeverity.symbolName`, as written down in `docs/desktop-design.md`.
- Differences from Swift:
  - "Open full warning" is a link-style button under the block, not the block itself: a Streamlit button cannot hold a drawn block.
  - The connection card counts laptops and says whether the local network is on; the iPhone counts phones and the internet.
  - Other warnings say "Another area" or "Near you" but no distance: `places.label` has no name for a whole 40 km warning cell.
- Verified by:
  - `python3 -m pytest tests/test_phone_app.py` — 30 passed (8 new). They cover:
    - clear, elsewhere and affected;
    - the worst covering warning wins over a worse one elsewhere, and the others stay most severe first;
    - next to the area is not covering you;
    - the page's grey card, the block, "What to do" and the full-warning sheet;
    - the connection card;
    - "Message" on a call for help from someone in range.
  - `python3 -m pytest -q` — 460 passed, 2 skipped. The page tests also pass with Streamlit 1.51.0.
  - Checked by eye in headless Chromium, in all three states, light and dark, at 1280 and 960 wide, against the mockup.

## 14.2 Phone app sidebar, status bar and "I need help" bar — 2026-09-27
- What:
  - The three tabs are buttons in the sidebar instead of a row of radio buttons, with the app's icon and name above them. Calls for help and loud warnings count on Now, unread messages on Chat, as red badges like the iPhone tab bar's; the open tab shows none.
  - Your nickname and town sit at the foot of the sidebar. Clicking them opens a Settings sheet (nickname, town, why a town, the place-name credit, Done). "Pick your town" on the page has an "Open Settings" button.
  - A status bar along the bottom, on every tab: Bluetooth and how many laptops are nearby, the local network, and when the page last changed. When one is off it says so, with the reason.
  - The red "I need help" bar is pinned to the bottom of Now. It opens the call for help; nothing is sent until "Send call for help". Without a town it is greyed out and says why.
  - Each tab has its own title. The page uses the whole window.
  - `alertmesh/style.py`: `nav()`, `page_title()`, `status_bar()` and the styles for them. The sidebar is 220 wide; below 1100 wide it is 76 wide, with icons over short labels and the badge on the icon.
  - `desktop.py`: the phone app opens at 1200 × 760; both apps cannot be made smaller than 960 × 600 (was 700 × 600).
- Ported from: `EmergencyRootView.swift` (the tabs and their badges, `EmergencyHelpBarModifier`), `NowView.connectionSection` (the connection in plain counts), as written down in `docs/desktop-design.md`.
- Differences from Swift:
  - The iPhone's bottom tab bar is a sidebar, which is how Mac and Windows apps show a few tabs.
  - The help bar is 56 points tall, not 60, and the call for help still opens inside the page; step 14.4 makes it a sheet.
  - Settings is a sheet here; on the iPhone it is a screen of its own.
- Verified by:
  - `python3 -m pytest tests/test_phone_app.py tests/test_desktop.py` — 36 passed (4 new: tabs in the sidebar and page titles, the status bar on every tab, the help bar on Now only, Settings from the foot of the sidebar; the town check now goes through Settings; the unread count is the Chat badge).
  - `python3 -m pytest -q` — 452 passed, 2 skipped. The page tests also pass with Streamlit 1.51.0.
  - Checked by eye in headless Chromium, at 1280 and 960 wide, light and dark, with Streamlit 1.51 and 1.64.
  - Found and fixed on the way: a starting value put in Session State does not reach a field inside a sheet in the browser (the test runner shows it anyway), so the Settings fields take theirs as parameters.

## 14.1 Colours, system typeface and dark mode — 2026-09-27
- What:
  - `alertmesh/style.py` (new) holds the shared look for both apps:
    - `THEME`, Streamlit's light and dark settings: system blue, the iPhone's backgrounds and card grey, the sidebar grey, and the system typeface (SF Pro on a Mac, Segoe UI Variable on Windows, no bundled font);
    - `TOKENS` and `CSS`, one stylesheet whose colours are variables with a dark partner each;
    - classes for a level as a fill, as text, as a bar and as a border;
    - the level symbols (circle-i, triangle, octagon).
  - `.streamlit/config.toml` no longer forces light. It holds `[theme.light]` and `[theme.dark]`, so the page follows the system's setting. `desktop.py` passes the same settings as flags, because the packaged apps start where that file is not found. It imports `style` only when starting the page, so the self-check can still report a missing `alertmesh`.
  - Both apps put the stylesheet on the page. The phone app's warning cards and the console's preview and live list draw their level colours from the classes, so they change in dark mode.
- Ported from: `ThemePalette.alertMesh` and the severity fill and text colours in `AlertMesh/Utils/Theme.swift`; `EmergencyLayout` and `EmergencyType` in `AlertMesh/AlertMesh/Views/EmergencyLayout.swift`; `ChatBubbleStyle` in `ChatBubbleRow.swift`; `AlertSeverity.symbolName`. The values are the ones written down in `docs/desktop-design.md`.
- Differences from Swift:
  - Sizes are fixed at about 88% of the iPhone's default text sizes, not Dynamic Type.
  - The symbols are small drawings in the spirit of the SF Symbols the app uses; SF Symbols cannot be used outside Apple's platforms.
  - The Hub board still has its white background; step 14.5 makes it black.
- Verified by:
  - `python3 -m pytest -q` — 448 passed, 2 skipped (7 new in `tests/test_style.py`: the config file and the desktop flags hold the same theme, no `theme.base`, the system typeface, the iPhone colours, a dark partner for every colour, no fixed colour in the stylesheet's rules).
  - The page tests also pass with Streamlit 1.51.0, the lowest supported version (50 passed).
  - Both apps opened headless in Chromium, with the system set to light and to dark: the page, the sidebar, the buttons and the warning cards switch between the iPhone's light and dark colours.

## 13.9 README: the two apps and the two-laptop check — 2026-09-27
- What: the README now covers:
  - the two apps, and what is and is not covered (no iPhone compatibility);
  - a "Phone app" section: picking a town, where the profile is kept, the three tabs, and a table of what travels over Bluetooth and what over the local network;
  - "Bluetooth and network permission (Mac)": run from VS Code or the packaged app, not Terminal, and allow Bluetooth and Local Network;
  - the Windows firewall;
  - a six-step "Two-laptop check";
  - desktop apps for both, with sizes and how to open each on another computer.
  - `tools/ble_probe.py` and `phone_app.py` now say to run from VS Code, not Terminal.
- Ported from: new.
- Differences from Swift: not applicable.
- Verified by: read against what was run in steps 13.1 to 13.8:
  - the Terminal and iTerm Info.plists have no Bluetooth usage description and VS Code's does;
  - the Bluetooth status wording is the page's own;
  - the app sizes are from the 13.8 build;
  - the 30 s repeat is what brought a warning to a phone app started late.
  - The two-laptop steps themselves have not been run (step 13.4).

## 13.8 Two desktop apps — 2026-09-27
- What:
  - `desktop.py` knows two pages (`PAGES`: phone and warning), takes `--app`, and can be the phone app's Bluetooth process (`--bluetooth`, used by the packaged app). Its self-check also imports the modules a page loads only later (Bluetooth and network libraries).
  - `packaging/start_phone.py` and `start_warning.py` are the two packaged apps' start files.
  - `packaging/alert_mesh.spec` builds both:
    - `Alert Mesh.app`, the phone app: it keeps the Phase 12 bundle ID, bundles `bleak` and `bless`, and leaves out the simulation and its maps;
    - `Alert Mesh Warnings.app` (`au.alertmesh.warnings`);
    - both Info.plists carry a Local Network usage description, and the phone app's also carries a Bluetooth one.
  - `packaging/build_mac.sh` builds, checks and zips both.
  - `packaging/build_windows.ps1` does the same for Windows, still not run.
  - VS Code has "Desktop window: phone app" and "Desktop window: warning app".
- Ported from: new (Phase 12 packaging, now for two apps).
- Differences from Swift: the iPhone app and the Mac console are one codebase built twice. Here too: one package, two start files.
- Verified by:
  - `python3 -m pytest tests/test_desktop.py` — 11 passed (commands for both apps, self-check of both).
  - `packaging/build_mac.sh` built both apps, and each finished app passed its own `--check`. Sizes: `Alert Mesh.app` is 246 MB (zip 97 MB); `Alert Mesh Warnings.app` is 287 MB (zip 112 MB).
  - Opened both packaged apps on this Mac:
    - the phone app's sidebar said "Bluetooth: on" (its Bluetooth process ran, and was not stopped by macOS) and "Local network: on";
    - I picked Katherine and sent a Watch and Act warning from the warning app. It appeared in the phone app as "You are in this area", loud. The warning app's line said "sent to phone apps on the local network".
    - "Cancel warning" cleared it from the phone app.
    - Quitting both left no process, including the Bluetooth process.
    - The phone app saved its profile in `~/Library/Application Support/Alert Mesh/phone.json`, readable by the owner only.
  - Not yet run: the Windows build.

## 13.7 Warning app — 2026-09-27
- What:
  - `app.py` is now `warning_app.py`, with three tabs (Warning console, Map, Hub board); the Phone view tab gave way to the phone app. `tests/test_app.py` is now `tests/test_warning_app.py`.
  - Each warning, update, cancellation and "send again" also goes to real phone apps on the local network, through `console.NetworkShare` (`Console` has a new optional `share`, and `world.build` passes it on). The line under the Send button says whether that worked.
  - Building a new town, opening a second browser tab or reloading the page withdraws the warnings sent earlier, since the new town could not cancel them.
  - `desktop.py`, the PyInstaller recipe, VS Code ("Warning app") and the README point at `warning_app.py`.
  - The tests use their own network port (`tests/conftest.py`, `ALERTMESH_LAN_PORT`), so a phone app running on the same computer never sees test warnings.
- Ported from: `AlertMesh/AlertMesh/Services/OfficialAlertIssuer.swift` and `AlertMesh/AlertMesh/Views/IssueWarningView.swift` (unchanged console); the network copy is new.
- Differences from Swift: the simulated town runs on its own clock, which starts in 2023 and only moves when the operator lets time pass. Real phone apps check the real clock. So the copy sent to phone apps is signed again with the real time: same event ID, words, area and length. The Mac issuer signs once, with the real time.
- Verified by:
  - `python3 -m pytest tests/test_warning_app.py tests/test_console.py` — 13 + 20 passed. They cover:
    - a sent warning reaches a listener with the pinned signature and today's time;
    - a phone store refuses the town's 2023 copy and takes the real one;
    - update, "send again" (same bytes) and cancel reach the phone store;
    - a new town withdraws what the old one sent.
  - End to end on this Mac, in a browser, with the warning app and the phone app running side by side:
    - a warning sent from the console appeared on the phone app as "You are in this area", loud, 30 s later (the phone app had started listening just after the first send, so it came with the repeat), and the page updated by itself;
    - "Cancel warning" cleared it from the phone app within 3 s.
  - Found on the way: reloading the warning page used to leave its warnings on phone apps with no way to cancel them; fixed as above.

## 13.6 Phone app — 2026-09-27
- What:
  - `alertmesh/phone.py`, the phone app's engine:
    - one person's saved profile (identity seed, nickname, town) in their own folder (`~/Library/Application Support/Alert Mesh/phone.json` on a Mac, `%APPDATA%\Alert Mesh` on Windows; `ALERTMESH_HOME` moves it); the file is readable by its owner only;
    - the mesh node, fed by the Bluetooth process and the Wi-Fi listener, ticking once a second;
    - warnings with how they concern this person (`proximity.decide`), calls for help, sending an SOS, "I'm safe" and hazard reports from the person's town.
  - `phone_app.py`, the page, with the iPhone app's three tabs:
    - Now: a "Call for help" button, or while one is out, "I'm safe now" and "Send it again"; people asking for help first, then warnings in their level colour with how close they are;
    - Report: the hazard report form and the community reports list;
    - Chat: Nearby plus one conversation per person, people in range with a "Message" button, and a message box.
  - A pop-up for each new warning and call for help, using the existing notification words. The page checks for news once a second and redraws only when something changed. The sidebar holds nickname, town, and Bluetooth and network status.
  - VS Code entry "Phone app".
- Ported from: `AlertMesh/AlertMesh/Views/EmergencyRootView.swift` (three tabs), `NowView.swift` (calls for help first, then warnings), `SOSView.swift` (call for help, "I'm safe", send again, the "not 000" line), `CommunityReportsView.swift`, `ChatInboxView.swift` (Nearby and private conversations, unread counts).
- Differences from Swift:
  - The person picks their town instead of GPS: a laptop has none. The iPhone app will not open without location; the phone app opens, and asks for a town before a call for help or report can be sent.
  - The tab bar is a row of choices, not real tabs, so the page knows when Chat is open and can mark messages read. Unread counts show on the line below, because a label that changes can reset the choice.
  - Pop-ups inside the page instead of system notifications.
  - Messages are not saved between runs.
  - No read receipts, no map pin on a call for help.
- Verified by:
  - `python3 -m pytest tests/test_phone_app.py` — 19 passed, with a fake radio. They cover:
    - the profile is kept and survives a broken file; the same person after a restart;
    - a warning for my town is loud and elsewhere quiet;
    - SOS and "I'm safe" from the page;
    - someone else's call for help shows first;
    - a hazard report sent from the page;
    - typing a message sends a signed Nearby frame;
    - an incoming message is counted, then marked read when Chat opens;
    - a private message to Bob can only be opened by Bob;
    - a too-long message is refused with a reason.
  - By eye in a browser: picked Katherine, sent a call for help ("Your call for help is out … It says you are near Katherine", fixed from a first "Near Near Katherine"), and typed a Nearby message, which showed as a bubble. The sidebar showed "Bluetooth: off", with the reason, because that server ran from a program without Bluetooth permission.

## 13.5 Wi-Fi link — 2026-09-27
- What: `alertmesh/lan.py`:
  - `Broadcaster` (warning app): sends each signed warning or cancellation as a UDP multicast packet (group 239.255.77.7, port 47147, TTL 1, so routers never pass it on). It repeats every 30 s until the warning ends; a cancellation replaces its warning.
  - `Listener` (phone app): hands every warning packet heard to the node, which checks the signature before keeping it. Several listeners can share one computer.
  - Every packet is sent twice, on the network and inside the computer, so both apps on one computer always work.
- Ported from: stands in for `AlertMesh/AlertMesh/Services/OfficialAlertBridge.swift` (warnings over Nostr internet relays). The local network plays the internet.
- Differences from Swift:
  - Local network only, not the internet.
  - No relay list, no Nostr event wrapping (kind 1403), no area-based subscription: every phone app on the network hears every warning and decides by its own location, as for Bluetooth.
- Verified by:
  - `python3 -m pytest tests/test_lan.py` — 8 passed, 5 runs in a row: a warning arrives; two listeners on one computer both hear it; junk and oversize packets are ignored; TTL is 1; repeats keep coming; a cancellation replaces its warning; ended ones stop.
  - Found on the way, on this Mac (macOS 15): multicast on the Wi-Fi interface is silently dropped until the program has "Local Network" permission. From a program without it, nothing arrived, with no error. Inside a small app with a Local Network usage description, the first sends were dropped and then arrived once allowed. That is why every packet also goes through the loopback interface, and why the packaged apps will need that description (step 13.8).
  - Not yet run: two computers on one Wi-Fi.

## 13.4 Bluetooth link — 2026-09-27 (blocked: two-laptop check not yet run)
- What: `alertmesh/ble.py`:
  - `split` / `Reassembler`: each frame is cut into pieces that fit one Bluetooth write (at least 20 bytes), each piece carrying a 6-byte label; pieces are put back together on arrival, even out of order or mixed with another frame's; unfinished frames are dropped after 10 s.
  - `BleLink`: advertises the Alert Mesh service with a writable "inbox" (`bless`), scans for other laptops advertising it (`bleak`), keeps connections open, and writes each frame to every laptop seen in the last 30 s. A laptop that fails is left alone for 15 s.
  - `BluetoothProcess`: runs all of that in a separate small process and talks to it over standard input and output.
  - `tools/ble_probe.py` now takes its IDs from here.
- Ported from: modelled on `AlertMesh/Services/BLE/BLEService+LinkLayerCentralRole.swift` (scan, connect, write) and `BLEService+LinkLayerPeripheralRole.swift` (advertise, receive), and the iPhone app's `fragment` message type.
- Differences from Swift:
  - The inbox only takes writes: no notifications back from the peripheral side. Each laptop connects to the others itself instead.
  - No link-quality tracking, no connection limits, no duty cycling for battery.
  - Pieces are our own format, not the iPhone's fragments.
  - Bluetooth runs in its own process. On a Mac, a program without permission to use Bluetooth is stopped outright; this way only the Bluetooth process stops, and the app explains why.
- Verified by:
  - `python3 -m pytest tests/test_ble.py` — 19 passed, with the radio replaced by fakes:
    - the largest frame survives write sizes of 20, 23, 180 and 512;
    - pieces arrive shuffled across two frames and are still put back together;
    - a frame reaches every laptop in range, and connections are reused;
    - a failed laptop is not retried for 15 s;
    - the Bluetooth process passes frames both ways;
    - a Bluetooth process stopped by macOS gives a plain explanation.
  - On this Mac with real Bluetooth, inside a small app allowed to use it: status went from "starting" to "on" within a second, and sending with nobody in range did no harm.
  - Run from a program without Bluetooth permission, macOS stopped only the Bluetooth process, and the app reported "off: macOS stopped Bluetooth because this program is not allowed to use it…".
  - Not yet run: two laptops exchanging frames. That needs a second computer.

## 13.3 Mesh node — 2026-09-27
- What: `alertmesh/node.py`, one laptop in a real mesh, with no radio code in it:
  - frames (version, kind, TTL, packet ID, body), with the iPhone app's kind numbers;
  - each packet handled once, remembering the last 1000 IDs;
  - relaying with `mesh_sim.relay_ttl`, the same rule as the simulation;
  - announces every 30 s, and a "people nearby" list that drops anyone silent for 95 s;
  - a gossip every 60 s: neighbours are sent every warning and report held, one hop;
  - `ChatStore`: Nearby plus one conversation per person, each message kept once, unread counts.
  - Warnings go through the existing `AlertStore` and reports through `ReportStore`, so a forged warning is refused exactly as in the simulation. `take_official` takes warnings from outside the mesh (the Wi-Fi link, step 13.5).
  - A lock around every public method, because the radio and the page run on different threads.
- Ported from: modelled on `AlertMesh/Services/BLE/BLEService.swift` (relay with TTL, per-type handling), `AlertMesh/Services/MessageDeduplicationService.swift` (each packet once, LRU of 1000), and GossipSyncManager (neighbours swap what they hold).
- Differences from Swift:
  - Gossip sends everything held each minute, instead of first swapping a compact filter of what each side has. That is fine for tens of items; the app's filter scales to thousands.
  - No store-and-forward courier for private messages to someone out of range: a private message can only go to a person heard from recently.
  - A warning repeated from Wi-Fi is not relayed again (only new ones are), so the Wi-Fi repeat every 30 s does not flood the Bluetooth.
- Verified by: `python3 -m pytest tests/test_node.py` — 19 passed, with a fake radio:
  - A's message reaches C through B, and in a ring it is sent exactly 3 times;
  - a 12-laptop row: N1 to N7 hear it and N8 does not;
  - forged messages and forged warnings go no further than the first laptop;
  - a private message is read only by its recipient and never appears in clear on the air;
  - a call for help crosses two hops and "I'm safe" replaces it;
  - a laptop that arrives late gets warnings and reports at the next gossip.

## 13.2 Chat messages — 2026-09-27
- What: `alertmesh/chat.py`:
  - `Identity` holds one person's two keys (signing and chat) and nickname; its 64-byte seed is what gets saved. Its signing half also signs that person's reports, so chat and calls for help share one identity.
  - `Announce` ("I'm here": nickname plus both keys, signed);
  - `ChatMessage`, signed, either Nearby (everyone in range can read it) or private (names its recipient);
  - `seal` / `open_sealed` / `Identity.open`, which lock a private message so only the recipient can read it.
  - Text limit 280 bytes; the largest sealed message is 545 bytes.
- Ported from: modelled on `localPackages/BitFoundation/Sources/BitFoundation/MessageType.swift` (`announce`, `message`, `noiseEncrypted`) and `AlertMesh/Services/PrivateChatManager.swift`. The byte layout follows the Python ports of the warning and report formats (same field style, same signing style).
- Differences from Swift:
  - Not wire-compatible with the iPhone app.
  - Private messages use a one-off X25519 key + HKDF-SHA256 + ChaCha20-Poly1305 per message instead of Noise XX sessions: no handshake, but no forward secrecy (someone who later steals Bob's chat key can read old messages to Bob).
  - No read receipts, no delivery receipts, no mentions, no voice or files.
  - The recipient is signed inside the message, so a private message cannot be shown as Nearby or re-sealed to a third person.
- Verified by: `python3 -m pytest tests/test_chat.py` — 16 passed (round trips; changed nickname, text or recipient fails the signature; empty and oversize text refused, counting bytes not letters; only the recipient can open a private message; a changed sealed message does not open; a message written to Carol and re-sealed to Bob is refused).

## 13.1 Bluetooth trial — 2026-09-27
- What: Phase 13 added to `PROGRESS.md` (a phone app and a separate warning app, like the iPhone app). `bleak` and `bless` added to `requirements.txt`. New `tools/ble_probe.py`: advertises the Alert Mesh service with one writable characteristic, scans for nearby devices, and writes a hello to any other laptop running it.
- Ported from: the idea of `AlertMesh/Services/BLE/BLEService.swift`, which is both a Bluetooth central (scans, connects, writes) and a peripheral (advertises, receives). No code ported.
- Differences from Swift: our own service ID (`aa857bb9-…`), not the iPhone app's (`F47B5E2D-…`), so laptops and iPhones ignore each other. The iPhone app's Bluetooth protocol (Noise encryption, announces, fragments, gossip sync) is not reproduced.
- Verified by: on this Mac (macOS 15, Python 3.13), the probe run inside a small app that declares Bluetooth use printed `advertising: True` and `78 Bluetooth devices nearby`, exit 0. Found on the way: macOS stops any program that uses Bluetooth without a written reason in its app's Info.plist (crash report: "attempted to access privacy-sensitive data without a usage description"). Terminal and iTerm have no such reason, VS Code does, so run the Bluetooth parts from VS Code; the packaged app will carry its own. Not yet checked: two laptops finding each other (needs a second computer).

## 12.5 README: the desktop app — 2026-09-27
- What: a new README section, "Desktop app (no browser)":
  - how to build on a Mac (`packaging/build_mac.sh`) and on Windows (`packaging\build_windows.ps1`, marked not yet run), what each makes and how big it is, and how to pick the build Python;
  - how to try the window without building (`python3 desktop.py`, or the VS Code "Desktop window" entry);
  - how to open the app on another computer: unzip and open; Apple Silicon Macs only; the macOS first-open block for downloaded copies and **Open Anyway** in Privacy & Security; Windows SmartScreen's **More info → Run anyway**; that the map background needs internet; that the page is reachable only from that computer; and where the server log is.
- Ported from: not applicable.
- Differences from Swift: not applicable.
- Verified by: read against what was run.
  - **Matches what was measured:** the build commands and output paths are those used in 12.3; sizes 287 MB and 112 MB; build time about 45 s; python.org Python 3.14; macOS 15.7.5.
  - **Not checked here:**
    - **The macOS first-open block.** This Mac has Gatekeeper switched off (`spctl --assess` reports `override=security disabled`), so the block could not be shown. The README describes macOS 15's documented behaviour for apps not signed by a registered Apple developer.
    - **"A copy from a USB stick usually opens straight away."** Only downloads, AirDrop and e-mail mark a file as coming from the internet.
    - **Everything about Windows.** It is untested (step 12.4).

## 12.4 Windows build script (written, not yet run) — 2026-09-27
- What: `packaging/build_windows.ps1`, the Windows counterpart of `build_mac.sh`, using the same recipe (`packaging/alert_mesh.spec`). It:
  - makes or reuses `packaging\.venv-windows` with `py -3` (or `$env:PYTHON`);
  - installs the build tools;
  - runs PyInstaller;
  - checks the finished `dist\Alert Mesh\Alert Mesh.exe` with `--check`;
  - zips the folder to `dist\Alert-Mesh-windows.zip`.

  The icon is the Swift app's 256 px image, which PyInstaller turns into `.ico` with Pillow. `desktop.py --check` now also writes its result to `alert-mesh-check.txt` in the temp folder, because a Windows window app has no text output (`sys.stdout` is `None`), so `print` alone would crash.
- Ported from: new (packaging).
- Differences from Swift: not applicable.
- Verified by: **not run.** There is no Windows PC and no PowerShell on this Mac, so the step is marked `[!] blocked` in PROGRESS.md.
  - **What was checked here:** the script is plain ASCII (safe for Windows PowerShell 5.1), and it uses the same recipe and launcher that built and ran on the Mac. The Mac app was rebuilt after the `--check` change and still passes its check. New test `test_the_self_check_works_without_text_output` runs the check with `sys.stdout = None` and reads the result from the file. `tests/test_desktop.py`: 9 passed; full suite 357 passed.
  - **Not checked, and to watch for on Windows:**
    - the script's own syntax;
    - pywebview's Windows part (`pythonnet`), which may not yet support the newest Python (the script's header says to fall back to Python 3.13);
    - the WebView2 runtime (normally part of Windows 10 and 11);
    - SmartScreen's warning on first open;
    - the parent-process check in `desktop.py`, which uses the Windows API on Windows.
  - **To finish this step on Windows**, from `python-prototype\`:
    1. Run `powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1`. It must end with "ok: 30 imports of app.py load; 996 towns …".
    2. Open `dist\Alert Mesh\Alert Mesh.exe`, send a warning, and check the four tabs.
    3. Close the window. Task Manager must show no "Alert Mesh" left.
    4. Tick the box.

## 12.3 Mac app — 2026-09-27
- What: `packaging/build_mac.sh` builds `dist/Alert Mesh.app` and `dist/Alert-Mesh-mac.zip`, in about 45 s once the build tools are installed. The app runs with no Python on the computer. The script:
  - makes or reuses the build environment `packaging/.venv-mac`, choosing the Python with `PYTHON=` (3.10 or newer; tested with python.org 3.14.3);
  - installs the build tools;
  - makes the icon (`.icns`, with `iconutil`) from the Swift app's own icon images;
  - runs PyInstaller with the new recipe `packaging/alert_mesh.spec`;
  - checks the finished app with `--check`;
  - zips the app with `ditto` for sharing.

  The recipe is shared with Windows. It bundles `desktop.py`, `app.py`, every `alertmesh` module, Streamlit and Plotly with their files, and a copy of the Swift app's town list at `alertmesh/data/` (step 12.1). It leaves out the test and notebook tools. New `desktop.py --check` imports everything `app.py` imports and reads the town list, without opening a window.
- Ported from: new (packaging). Bundle id `au.alertmesh.prototype`, version 1.0.0.
- Differences from Swift: not applicable. (The Swift app has its own Mac build; this app is the Python prototype.)
- Verified by:
  - **Build.** `packaging/build_mac.sh` from empty `build/` and `dist/` finished in 46 s. Results: app 287 MB, zip 113 MB, Apple Silicon only (`arm64`). It is ad-hoc signed only, which is PyInstaller's default; not signed by a registered Apple developer.
  - **The first build did not work, and the fix is now part of the build.**
    - Symptom: the window opened, but the page showed `ImportError: cannot import name 'hub' from 'alertmesh' (unknown location)`.
    - Cause: `collect_submodules("alertmesh")` ran where `alertmesh` could not be imported, so it found no modules and no alertmesh code was bundled. Only the town-list folder `alertmesh/data/` was, and Python took that folder for the package.
    - Fix: the recipe now lists the modules straight from the folder.
    - Guard: the build runs `--check` on the finished app. In a folder set up like that broken build, `--check` printed `missing: alertmesh.console` and exited 1; on the fixed app it prints `ok: 30 imports of app.py load; 996 towns from …/Alert Mesh.app/Contents/Resources/alertmesh/data/AustralianPlacesData.swift`.
  - **The fixed app, unzipped outside the repo (scratchpad) and opened there:**
    - its page was up 2 s after opening, on `127.0.0.1` only;
    - a native "Alert Mesh" window in the light theme with the map background, and no Deploy button;
    - by hand in that window: wrote and sent an Emergency Warning covering the town ("Sent: … — 1 device connected over Bluetooth, handed to internet relays"), pressed +5, and checked the Map (spread shown), the Phone view (card, "Loud now: You are inside the warning area.", notification) and the Hub board (large type, "2 devices nearby");
    - closing the window, or quitting the app, left no process within 1–2 s.
  - **Nothing outside the app is needed:**
    - no linked library outside the app or macOS (`otool -L`);
    - no file inside it mentions this user's home folder;
    - `env -i … --check` run from `/` passes.
  - **Tests:** `python3 -m pytest tests/test_desktop.py` — 8 passed, 2 new (`--check` passes here; `--check` fails when the alertmesh code is missing). Full suite: 356 passed.

## 12.2 Desktop launcher — 2026-09-27
- What: `desktop.py` shows the live demo page in its own window, with no browser. Streamlit's server and the window both need the program's main thread, so the program starts a second copy of itself with `--serve PORT --parent PID` to run the page, and shows the page with `pywebview` (Safari's engine on a Mac, Edge's on Windows).
  - Before the page is up, the window shows "Starting the simulated town…". If the page is not up within 60 s, or the server stops, the window says so and names the log file (`alert-mesh-server.log` in the system temp folder).
  - Closing the window stops the server. If the window's process is killed instead, the server notices its parent is gone within about a second and exits, so no server is left running.
  - Streamlit settings are passed on the command line, because the packaged app starts in `/`, where `.streamlit/config.toml` is not found. The page is served on `127.0.0.1` only, so no other computer can reach it; `streamlit run` offers it to the network. Also: light theme, no Deploy button, `global.developmentMode=false` (a bundled Streamlit otherwise believes it is in development).
  - Other additions:
    - `packaging/requirements-build.txt`: the build tools PyInstaller 6.22, pywebview 6.2 and Pillow 12, on top of the prototype's libraries.
    - A separate build environment, `packaging/.venv-mac` (Python 3.14.3), which git ignores, as it does `build/` and `dist/`.
    - A VS Code Run entry, "Desktop window".
    - A plain message when pywebview is missing.
- Ported from: new (packaging).
- Differences from Swift: not applicable.
- Verified by:
  - `python3 -m pytest tests/test_desktop.py` — 6 passed:
    - the port;
    - the command in development and packaged form;
    - the Streamlit flags (127.0.0.1, development mode off);
    - a real server that starts, answers `/`, and stops;
    - no waiting on a server that has already stopped;
    - the server exits when its parent is killed. This test failed as it should with the parent watch switched off on purpose, and passes with it on.

    Full suite: 354 passed.
  - By eye: `packaging/.venv-mac/bin/python desktop.py` opened a native macOS window titled "Alert Mesh" showing the page, and its tabs worked. `lsof` showed the server listening on `127.0.0.1` only. Closing the window stopped both processes within 1 s, and the server log ended with "Stopping...".
  - Not tested: the Windows branch of the parent check (it asks Windows whether the parent still runs), because there is no Windows PC here.

## 12.1 Town list found inside the desktop app — 2026-09-27
- What: Phase 12 (a desktop app with no browser) is added to PROGRESS.md at the user's request, with 5 steps. This first step makes `alertmesh/places.py` look for the town list in two places, in order:
  1. the Swift app's own file (development, unchanged);
  2. `alertmesh/data/AustralianPlacesData.swift`, a copy the desktop build will put inside the app, where the Swift folder does not exist.

  No copy is committed: the Swift file stays the only source. If neither exists, the error names every place it looked. New: `DATA_FILE_NAME`, `DATA_FILE_CANDIDATES`, `data_file()`. `DATA_FILE` is now the file actually in use.
- Ported from: not applicable (packaging).
- Differences from Swift: none. The data and parsing are unchanged.
- Verified by: `python3 -m pytest tests/test_places.py` — 30 passed, 3 of them new:
  - development reads the Swift app's file;
  - with the Swift folder missing, a bundled copy is read and gives exactly the same places;
  - the error names both places.

  Full suite: 348 passed.

## 11.3 The Swift app folder is unchanged — 2026-09-27
- What: confirmed that the port never changed the Swift app, the rule set at step 0.1. The check's commands are now in PROGRESS.md, so anyone can re-run it.
- Ported from: not applicable.
- Differences from Swift: not applicable.
- Verified by, from the repository root, against `6ca96ca` (the commit just before step 0.1; 59 `[py …]` commits since):
  - `git diff --name-only 6ca96ca..HEAD -- alert-mesh`: nothing.
  - `git log --oneline 6ca96ca..HEAD -- alert-mesh`: nothing. No commit of any kind touched it.
  - `git status --porcelain -- alert-mesh`: nothing. No change, tracked or untracked.
  - Files on disk: nothing that git tracks changed. One thing did change, outside git's view: at 16:06 today, 47 files in `alert-mesh/.build/index-build/` were rewritten. That is Swift's code-index cache, which git ignores (`.build/`) and which rebuilds itself. The time matches the first manual run of `swift scripts/sign-test-alert.swift` from inside `alert-mesh/` during step 11.1, so this session most likely caused it. No source file was involved.
  - The committed tool, `tools/cross_check_swift.py` (and its pytest test), runs the script from `python-prototype/`. After running both, no file under `alert-mesh/` had changed.
  - A first attempt at the on-disk check used `find -newermt` with a date that included a time zone. It silently matched nothing, which would have wrongly reported no changes. Comparing against a reference file gave the real answer above.

## 11.2 README walk-through in a fresh clone — 2026-09-27
- What: cloned the branch into an empty folder, made a new Python environment, and followed the README step by step. Fixed what that turned up:
  - **The page tests broke on the newest Streamlit.** A fresh install gets Streamlit 1.64 (this machine has 1.51). 1.64 resolves `AppTest.from_file("app.py")` relative to the test file, not the current folder, so all 15 page tests failed to start. `tests/test_app.py` now gives an absolute path, which works on both versions.
  - **The prototype crashed on a Mac's built-in Python.** `/usr/bin/python3` on this Mac is 3.9.6. There, the first import fails with `TypeError: unsupported operand type(s) for |`, because the modules use `X | None` hints that need Python 3.10 or newer. `alertmesh/__init__.py` now stops with a plain message instead: which Python is running, that 3.10 or newer is needed, and where to get it. The README now says so first.
  - **`requirements.txt` claimed versions that were never tested.** It said `streamlit>=1.30`, but the page uses features 1.30 does not have. Every minimum is now the lowest version actually tested (this machine's), and the comment lists the newest versions also tested.
  - **README "Set up" now matches the steps that were run.** Check `python3 --version`, make a `.venv`, activate it, install, and pick that interpreter in VS Code. Some systems (such as Homebrew's Python) refuse a plain `pip install`, which the environment avoids. Windows lines are given, and the README says honestly that only macOS was tested.
- Ported from: not applicable.
- Differences from Swift: not applicable.
- Verified by: three clean runs, each in a new clone with a new environment from `requirements.txt`:
  - **Python 3.13, before the fixes.** Library versions: cryptography 50.0.1, plotly 7.1.0, pandas 3.0.6, streamlit 1.64.0, pytest 9.1.1, ipykernel 7.3.0, nbconvert 7.17.1.
    - Tests: 330 passed and 15 page tests failed to start. After the test fix: 345 passed, with no warnings.
    - Notebook: runs with no errors. 14 of 17 code cells give exactly the same text as on this machine. The other 3 differ only in random warning IDs, random author keys and a memory address. The summary table is identical (98% / 11% after 10 minutes).
    - `streamlit run app.py` from the clone, checked in the browser pane: light theme and map tiles, a warning sent, and the Map and Hub board tabs showing it.
    - `tools/cross_check_swift.py`: all passed.
  - **Python 3.14.3** (python.org), with the same libraries: 345 passed, and the notebook ran with the same results.
  - **Python 3.13 again, after the fixes**, applied to a second clone and following the new README "Set up" word for word:
    - 345 passed;
    - the notebook ran with no errors;
    - the cross-check all passed;
    - the page started and loaded.

  Separately: the Mac's `/usr/bin/python3` (3.9.6) now stops with the new message; the old `TypeError` was seen first. This machine's own environment (the lowest versions) still passes 345.

## 11.1 Cross-check with Swift, both ways — 2026-09-27
- What: `tools/cross_check_swift.py`, a repeatable two-way check against Swift, plus `tools/verify_signature.swift` (about 40 lines, CryptoKit) and `tests/test_cross_check.py`. The test is skipped where Swift is not installed.
  - **Swift signs, Python checks.** The app's own script `scripts/sign-test-alert.swift` signs 6 warnings. They cover every hazard and every level: the frozen vector's inputs, a Katherine flood, no "what to do" text, 4 cells lasting 7 days, French and Japanese text, and the largest warning that fits. It also signs 1 cancellation. For each, Python must decode it, verify it with the pinned key, read back every field, and produce the very same bytes up to the signature. A phone's store must accept it, and the cancellation must withdraw its warning.
  - **Python signs, Swift checks.** Apple's CryptoKit, the library the app verifies with, checks the Python signatures on the same 6 warnings and the cancellation. It must also reject each one with one signature bit flipped.
- Ported from: nothing ported; this checks the port against `scripts/sign-test-alert.swift`, which is itself an independent implementation of `docs/ALERT-WIRE-FORMAT.md`.
- Differences from Swift: none found. One rule worth knowing, the same in both languages: the console refuses a warning with no "what to do" (`WarningDraft.problems`), but the wire format and the script allow one, and Python decodes it. For that case the tool builds the warning straight from the wire format rather than through the console.
- Verified by:
  - `python3 tools/cross_check_swift.py`: 8 of 8 passed in about 3 s. The largest warning is 370 bytes, inside the 383-byte frame.
  - The checks were broken on purpose to show they can fail. Each one then failed:
    - phones pinning a different key: "signature does not verify with the pinned key";
    - Python changing one byte: "Python's bytes differ from Swift's before the signature";
    - CryptoKit given a different real key: rejected;
    - CryptoKit given one bit of the signed message flipped: rejected.

    A first try at the message check changed a byte that was already 0x00, so it changed nothing and CryptoKit rightly accepted. It was redone by flipping a bit.
  - `python3 -m pytest tests/test_cross_check.py`: 2 passed. Full suite: 345 passed.
  - `git status` shows no change under `alert-mesh/` after running the script.

## 10.4 Streamlit: hub board tab — 2026-09-27
- What: the page's fourth tab, the evacuation centre's wall display. It has:
  - a header with the title and a clock;
  - the most serious live warning in large type: a strip in its level colour, then the headline, what to do, until when, and its area cells;
  - up to 3 more warnings as rows;
  - a footer with "N devices nearby" (or "No devices nearby yet") and "N more warnings not shown" when some did not fit;
  - when nothing is live, "No current warnings" with the board's "this board is live" line.

  Under the warnings is a list of calls for help the centre has heard, with who sent each, roughly where, how long ago, and the note. New module `alertmesh/hub.py` holds the board's rules and its HTML. New `World.board()`. The README now describes the four tabs.
- Ported from: `AlertMesh/AlertMesh/Views/HubBoardView.swift` (`maxRows`, `hiddenCount`, `peersText`, `clockText`, the hero, rows, empty state and footer, the English strings and the board's own large type sizes).
- Differences from Swift:
  - The calls-for-help list is new. The Swift board shows official warnings only, and the Mac notifies for calls for help instead. It is added because this step's checklist line asked for it, and it is labelled as unchecked reports, not official warnings.
  - The board does not refresh every second. It changes when simulated time passes or something is sent. The Swift board ticks its clock every second so a quiet board visibly stays alive.
  - No full-screen mode and no Escape key. The caption suggests collapsing the sidebar and using the browser's full screen.
  - No hub-mode switch. The Swift `HubModeController` also turns on the mesh bridge and keeps the display awake. Here the centre is always the online hub.
- Verified by: `python3 -m pytest tests/test_hub.py tests/test_world.py tests/test_app.py` — 38 passed. These include:
  - 5 ported board tests (footer says none rather than zero, warnings past the third row are counted, clock is a time only, the worst warning is the hero, empty and populated boards draw) and a row with no action and an unknown hazard;
  - a calls-for-help test (only SOS reports are listed);
  - a world test (the board shows the centre's warning and a call for help that reached it);
  - a headless page test.

  The full suite passed 343. By eye in the browser pane:
  - Sent an Emergency Warning, sent a call for help from phone p0, and let 15 minutes pass. The board showed the warning in large type, "Until 13:43 #qvqj9", "Calls for help nearby: p0, Near Katherine (qvqj9wy), 15 min ago — Car stuck at the causeway", and "4 devices nearby".
  - The empty board showed "No current warnings" with the live-board line.
- Found by reading the board's HTML: a warning with no "what to do" left a blank line followed by an indented line. In Markdown that ends the HTML block and prints the rest of the card as code. Every HTML block on the page is now one line (`hub.one_line`), with a test that fails on the old output.

## 10.3 Streamlit: phone view tab — 2026-09-27
- What: the page's third tab: one phone in the town. Pick a phone (it starts on one with no internet). It shows roughly where the phone is ("Near Katherine"), a nickname anyone can change, and switches for Bluetooth, location, internet, and a watched place.
  - Warnings: each live warning as the phone lists it (level colour, headline, "You are in this area" / "Near you" / "Another area", until when, what to do). Under each: why it is loud or quiet now, in plain words, and the notification the phone showed, worded as the app words it.
  - Community reports: the phone's report list (calls for help, hazards, "safe"), with who sent each and roughly where. Calls for help it was told about show as their notifications ("p0 needs help nearby").
  - Actions: send a call for help with a note, then "I'm safe now" or "Send it again", and send a hazard report (type, how bad, note). Without location, both are replaced by the app's "turn on location" lines.
  - New module `alertmesh/notifications.py`: what a notification says.
  - `labels.REASON_TEXT`: the reasons in plain words, now shared with the notebook's section 4, which used its own copy.
  - New in `world.py`: `phones`, `set_phone` (the phone re-checks its warnings at once) and `warnings_on`.
- Ported from: `AlertMesh/AlertMesh/Services/AlertNotificationContent.swift` (`make`, `Whereabouts`, the level emoji) and `SOSNotificationContent.swift` (`make`); strings and layout from `AlertsView.swift`, `CommunityReportsView.swift` and `SOSView.swift`.
- Differences from Swift:
  - Previews are always shown on the page. `alert_content` and `sos_content` still take `hide_previews`, and its tests are ported.
  - No notification identifiers: the prototype does not replace banners.
  - A watched place is one town's suburb-sized cell (6 characters). The app bookmarks location channels of any size.
  - "Send it again" re-sends from where the phone is now, like the app. There is no "Show on map" or "Call 000" sheet.
  - The plain-words reason line is new. The app shows only the "how close" line.
- Verified by: `python3 -m pytest tests/test_notifications.py tests/test_world.py tests/test_app.py` — 44 passed. These cover 16 ported notification-wording tests, 3 world tests (list and notification, Bluetooth off, watched place with location off), and 5 headless page tests: an empty phone, a warning with its reason and notification, location off, call for help then safe (including the notification on a phone that heard it), and a hazard report that is not a warning. The full suite passed 333, and the notebook still runs with the same section 4 table.
- By eye in the browser pane: sent an Emergency Warning and let 5 minutes pass. Phone p0 (no internet, walking) then showed the red card, "You are in this area · Until 13:43", "Loud now: You are inside the warning area." and the notification "🔴 Emergency Warning · Flood". Sent a call for help from p0: the page showed "Your call for help is out" with "I'm safe now" and "Send it again", and the report list showed "Needs help — You, Near Katherine".
- Found while building it: a phone cannot be a picker option, because Streamlit copies its options and a phone holds a private key that cannot be copied. The picker lists phone IDs instead.

## 10.2 Streamlit: map tab — 2026-09-27
- What: the page's second tab. Pick any warning the console has sent (newest first, marked "(ended or cancelled)" when no longer live). The map shows every phone in the simulated town: blue = warned by internet, red = got it over Bluetooth, grey = not warned yet. It also shows the warning area in the level's colour and the evacuation centre as a black dot. Four counts sit under the map:
  - warned, out of all phones;
  - warned inside the area, out of the phones in it;
  - told loudly;
  - got it over Bluetooth.

  "Let N minutes pass and record them" (1–30) moves the town's time on and records every minute. ▶ then plays those minutes, or drag the slider. New in `world.py`: `phones_now`, `play` (frames labelled with the town's own minutes) and `spread` (the counts). New in `viz.py`: `area_traces`, `centre_trace` and `fit_zoom`. `spread_map` shows a single moment with no play controls.
- Ported from: new (no Swift screen shows the simulation). Builds on step 9.3's `spread_frames` and the 9.3 fix to `spread_map`.
- Differences from Swift: not applicable.
- Verified by: `python3 -m pytest tests/test_world.py tests/test_app.py -k "map or spread or play"` passed. These include a headless page test (send, then "Let 10 minutes pass": time moves 10 minutes, frames cover minutes 0 to 10, and the count rises) and tests that the counts add up and the frames use the town's own minutes. The full suite passed 309, and the notebook still runs (`nbconvert --execute`, no errors).

  By eye in the browser pane: sent an Emergency Warning covering the town, then played 10 minutes. At minute 10: 272 of 300 warned (91%, the same as the notebook's town), 272 told loudly, 242 over Bluetooth. ▶ played minutes 0 to 10 with the colours correct. The same check found and fixed five things:
  - The mouse wheel zoomed the maps instead of scrolling the page, so the page's maps no longer zoom on scroll; their + and − buttons still work.
  - The counts were cut off in a narrow window, so their labels are now shorter, with the full wording on hover.
  - The play controls overlapped the map's credit line, so they now sit below it.
  - The slider's "minute" label sat under the buttons, so it moved to the right.
  - Rows of buttons were squeezed letter by letter in a narrow window, so they now wrap to the next line, and the place and area-size pickers are stacked.

## 9.3 (fix) The spread map keeps its colours while it plays — 2026-09-27
- What: `viz.spread_map` now builds the animated map itself, with one trace per status ("warned by internet", "warned by Bluetooth", "not warned yet") in every frame, even an empty one. Before, it used Plotly Express, which leaves a status out of any minute where no phone has it. Plotly animates traces by position, so from that minute on the phones would take the wrong colour, or not show at all. The notebook's town happened to have all three statuses in every minute, so its map was right. The page's map starts before anyone is warned, so it would have been wrong. It also takes `extra_traces` (such as the warning area), which stay the same in every frame, and puts the play button and slider below the map instead of over the map's credit line.
- Ported from: not applicable (drawing fix).
- Differences from the app: none added.
- Verified by: new test `tests/test_viz.py::test_every_frame_of_the_spread_map_has_the_same_traces` **fails** with the old code (base figure had 1 trace instead of 3) and passes with the fix. The notebook's town map, saved as HTML and played in the browser pane, shows the three colours and the legend correctly from minute 0 to 30. Share warned is unchanged: 54, 66, 76, 86, 91, 98, 98 and 99% at minutes 0, 1, 2, 5, 10, 15, 20 and 30. `jupyter nbconvert --execute demo.ipynb` ran with no errors (about 26 s). Full suite: 305 passed.

## 10.1 Streamlit: warning console tab — 2026-09-27
- What: `app.py`, the live demo page, with its first tab. The operator writes a warning (hazard, level, headline and what to do with byte counters, how long it lasts, area), sees a preview in the level's colour and a map of the area, and sends it after a confirmation. Live warnings are listed with Update…, Send again and Cancel warning. The sidebar holds the simulated town: a clock, "+1 / +5 / +15 minutes" buttons (time only moves when asked), and a form to build a new town. New modules:
  - `alertmesh/console.py`: the console (issue, update, resend, cancel, and the outcome line) and the area picker.
  - `alertmesh/world.py`: one simulated town, the notebook's section 3 town by default, plus an evacuation centre (a Mac, phone "hub") in the middle. The console sends from it.
  - `alertmesh/labels.py`: the app's words and colours for levels, hazards, report kinds and "how close" lines.
  - `viz.area_map`: the area picked, as outlined cells around the evacuation centre.
  - `.streamlit/config.toml`: always the light theme.
- Ported from: `AlertMesh/AlertMesh/Services/OfficialAlertIssuer.swift`, `AlertMesh/AlertMesh/Views/IssueWarningView.swift` (layout and English strings), `WarningAreaPicker` in `AlertMesh/AlertMesh/Views/WarningAreaMapView.swift`, `AlertNotificationContent.Strings`, `AlertsView.Strings.proximity` and `untilText`, `AlertSeverityStyle.swift` with `Utils/Theme.swift` (light-theme colours), `CommunityReportStyle.swift` (report words).
- Differences from Swift:
  - No key card. The prototype always signs with the development key, so the Swift `noKey` and `signingFailed` errors cannot happen.
  - The area is picked from a list of towns (nearest first) plus a size, or "Cover the simulated town", instead of by clicking the map. The same rule applies: picking inside a picked cell removes it, a larger cell swallows smaller ones, and a fifth cell is refused. For the same reason the no-area problem reads "Pick an area." instead of "Pick an area on the map."
  - The outcome line says "1 device" rather than the Swift "1 devices".
  - Offline, the warning goes out over Bluetooth only and is not queued. In the app, a warning posted with no relay connected may still go out once one connects; here the operator presses Send again.
  - The confirmation is a box under the Send button, not a macOS dialog.
  - Times show in this computer's time zone.
- Verified by: `python3 -m pytest tests/test_console.py tests/test_world.py tests/test_app.py` — 31 passed. These cover 8 ported issuer tests and 6 ported area-picker tests, plus page tests run headless with Streamlit's `AppTest`: send, Back, update, cancel with "Keep it", offline, and time passing. The full suite passed 304. By eye in the browser pane (`streamlit run app.py`): wrote an Emergency Warning, covered the simulated town (`qvqj9`, drawn on the map), confirmed, and saw it in Live warnings with "Until 13:43 · qvqj9". The outcome line read "Sent: … — 1 devices connected over Bluetooth, handed to internet relays", which led to the plural fix above. Two more fixes came from the same check:
  - The map's "Evacuation centre" label did not show, because the OpenStreetMap style has no font for map text. It is now hover-only, with a caption.
  - The browser's dark mode made the light-theme level colours hard to read, so the page is now always light.

## 9.8 Notebook: charts, with the mesh vs internet only — 2026-09-27
- What: section 8 of `demo.ipynb`. A curve of the share warned over 30 minutes, with the mesh and with internet only, plus a summary table. Three sweep charts, averaging 3 layouts per value: number of phones, share walking about, and Bluetooth reach. It closes with "what this shows, and what it does not", including the simulation caveats.
- Ported from: new. Uses `metrics.compare`, `metrics.sweep`, `metrics.means` and the `viz` charts.
- Differences from the app: not applicable.
- Verified by: `jupyter nbconvert --to notebook --execute demo.ipynb` ran with no errors; the whole notebook takes about 26 s. Base scenario (250 phones, 1 km², 10% online, 20% walking, 30 min): with the mesh 98% after 10 min, 98.8% at the end, 80% by minute 1; internet only 11.2% throughout. Sweeps, with mesh vs internet only:

  | Changed | Values | With mesh | Internet only |
  |---|---|---|---|
  | Phones | 50 / 100 / 200 / 400 | 89% / 93% / 99% / 100% | 15% / 12% / 12% / 12% |
  | Share walking about | 0 / 0.1 / 0.25 / 0.5 | 57% / 98% / 100% / 100% | 10% / 9% / 10% / 10% |
  | Bluetooth reach | 20 / 40 / 60 / 100 m | 90% / 97% / 99% / 100% | 11% |

  The first draft of the closing text said Bluetooth reach "matters a lot" and that a still, sparse camp gains much less. These charts, which include walkers, do not show either, so the text was rewritten to what they do show. It notes that without walkers both factors matter far more, as step 8.3 measured.

## 9.7 Notebook: community hazard reports — 2026-09-27
- What: section 7 of `demo.ipynb`. Jo reports a flooded causeway (high). After 10 minutes: how many phones hold it, that it is in no official warning store, and that it caused no notifications. Then one phone's report list (hazard first, then check-ins) with who sent each, which key signed it, severity, the place in words, and the note. A note explains that a nickname proves nothing and the key does.
- Ported from: new. Uses `Mesh.send_hazard`, the report store and `places.label`.
- Differences from the app: the "signed by key" column (first 4 bytes of the key) is a notebook teaching aid; whether the app's screens show the key was not checked, so the text claims only what the store guarantees (one record per key).
- Verified by: `jupyter nbconvert --to notebook --execute demo.ipynb` ran with no errors. Jo's report reached 243 phones in 10 minutes, is in no official store, and caused 0 notifications. The list shows the stranger's fake "I'm safe" from section 6 under the nickname "Sam" but a different key from Sam's real one. A first draft said "the real app shows this difference"; that was not checked, so it was reworded before commit.

## 9.6 Notebook: SOS, then "I'm safe"; a stranger cannot fake it — 2026-09-27
- What: section 6 of `demo.ipynb`. Sam (a phone with no internet) sends an SOS near Katherine, cut to 7 characters (about 150 m). A table shows how far it had spread at 0, 2, 5 and 10 minutes, and how loudly phones were told. A stranger tries two fake "I'm safe" messages: one claims Sam's key, one uses their own key with Sam's SOS ID; neither calls off the SOS. Then Sam's own "I'm safe" replaces it.
- Ported from: new. Uses `ReportAuthor`, the report store and `Mesh.send_sos` / `send_safe`.
- Differences from the app: none.
- Verified by: `jupyter nbconvert --to notebook --execute demo.ipynb` ran with no errors. The SOS reached 24 phones at once, 52 at 2 min, 102 at 5 min and 211 at 10 min; 210 were told loudly (all nearby in this 1.2 km town). After both fakes and 5 minutes, 271 phones still hold Sam's SOS. Ten minutes after Sam's "I'm safe", 205 phones hold it, 92 still show the SOS (not reached yet), and 203 were told Sam is safe. A first draft counted SOS and "safe" together, because they share one record ID, and wrongly showed 297 for both; the helper now counts by kind.

## 9.5 Notebook: update, then cancel — 2026-09-27
- What: section 5 of `demo.ipynb`. In the section 3 town: a flood Watch and Act is published, updated to an Emergency Warning (same event, later version), then withdrawn, with 10 minutes between each. A table shows the phones showing the event, how many show the current version, and the notifications so far. Late copies of both old versions are refused.
- Ported from: new. Uses `signer` (`WarningDraft.updating`, `cancel`), the stores and the mesh.
- Differences from the app: none.
- Verified by: `jupyter nbconvert --to notebook --execute demo.ipynb` ran with no errors. Watch and Act after 10 min: 289 phones, all 289 on that version, 289 notifications. After the update: 295 showing, 287 on the Emergency Warning (8 not reached by the update yet), 580 notifications. After the withdrawal: 4 still showing (not reached yet). Both old copies rejected. The first draft had two faults, both fixed before this commit. (1) The helper counted the wrong warning's level, giving 0; the phones also hold the section 3 bushfire warning, which sorts first. (2) The text claimed the withdrawal cleared every phone; it now says almost every phone, and explains the rest.

## 9.4 Notebook: loud or quiet, and why — 2026-09-27
- What: section 4 of `demo.ipynb`. A table of six people and their notification with a plain-English reason. Anna at home: loud. Ben 60 km away: quiet. Fin just outside the area: quiet. Cara with location off but a remembered area: loud. Dev with location off watching Katherine: loud. Eve with location off and nothing known: quiet, never silent. Then the count for the whole town from section 3.
- Ported from: new. Uses `proximity` through each simulated phone.
- Differences from the app: the reason sentences are written for the notebook; the app's own wording is in `AlertNotificationContent.swift`.
- Verified by: `jupyter nbconvert --to notebook --execute demo.ipynb` ran twice in separate Python runs with identical output, after the 7.4 fix. Six-person table as described. Whole town: 297 loud, 3 not warned yet. A first version labelled those 3 "silent"; they are phones not reached by minute 30, so they are now labelled "not warned yet". With the fix, section 3 reads 54%, 66%, 76%, 86%, 91%, 98%, 98%, 99%. The 9.3 entry's minute-2 figure of 77% came from a run before the fix.

## 7.4 (fix) Same results in every Python run — 2026-09-27
- What: `Mesh._sync()` now syncs phone pairs in sorted order. Before, it walked a Python set, whose order changes between runs (Python shuffles string hashes per run). Within one tick, that order decides whether a warning crosses one pair or two, so the same scenario gave slightly different curves each run (for example 64%, 65% or 66% at minute 1). Found while writing the notebook, which promises the same numbers on every run.
- Ported from: not applicable (simulation fix).
- Differences from the app: none added. The app has no such order; each phone syncs on its own timer.
- Verified by: new test `tests/test_metrics.py::test_results_are_the_same_in_every_python_run` runs one scenario under three hash seeds and requires identical results. It **fails** with the old code (checked by temporarily undoing the fix) and passes with the fix. The step 8.3 sweep numbers were re-run: unchanged to the nearest percent. Full suite: 271 passed.

## 9.3 Notebook: watch the warning spread on a map — 2026-09-27
- What: section 3 of `demo.ipynb`: 300 phones over about 1.2 km × 1.2 km around Katherine, 10% online, a quarter walking about. An animated map shows each minute for 30 minutes, followed by a table of the share warned. New shared module `alertmesh/viz.py` (`phone_status`, `spread_frames`, `spread_map`, `share_by_minute`, `curves_chart`, `sweep_chart`) and `tests/test_viz.py`.
- Ported from: new.
- Differences from the plan: `viz.py` was not in `PROGRESS.md`. It is added in this step so the notebook and the Streamlit page (Phase 10) draw the same pictures from one place. Maps use OpenStreetMap tiles; offline, the background stays blank but the phones still show.
- Verified by: `python3 -m pytest tests/test_viz.py` — 3 passed. A first run failed because Plotly ignores a colour column with an empty name; it was renamed "network". `jupyter nbconvert --to notebook --execute demo.ipynb` ran with no errors. Share warned: minute 0 54%, 1 66%, 2 77%, 5 86%, 10 91%, 15 98%, 20 98%, 30 99%. Not yet checked by eye: the browser pane cannot screenshot a local file. It will be checked in step 10.2, where Streamlit shows the same map. Full suite: 270 passed.

## 9.2 Notebook: forged and edited warnings go nowhere — 2026-09-27
- What: section 2 of `demo.ipynb`. A table of four warnings (genuine, forged with another key, downgraded to Advice, area moved to Darwin) with "signature valid" and what a phone's store says. Then a 5-phone line where a modified phone floods the forgery: it reaches 1 phone and no phone keeps it; the genuine warning reaches all 5.
- Ported from: new. Uses `signer`, `wire`, `AlertStore` and `Mesh` from earlier steps.
- Differences from the app: none.
- Verified by: `jupyter nbconvert --to notebook --execute demo.ipynb` ran with no errors. Table: genuine True/accepted; forged, downgraded and moved False/rejected. "Forgery reached 1 phone(s); phones now holding it: 0". "Genuine warning: phones holding it: 5 of 5".

## 9.1 Notebook: issue a signed warning — 2026-09-27
- What: new `demo.ipynb` with the introduction (what the app does, how to run, the simulation caveat), a setup cell, and section 1: sign an Emergency Warning for a bushfire near Katherine with the dev key, print its area code and place name, its size (217 of 383 bytes), its first bytes, and that it verifies against the pinned key. `pandas` added to `requirements.txt` for the notebook's tables.
- Ported from: new. Uses `signer`, `wire`, `geohash` and `places` from earlier steps.
- Differences from the app: none. The notebook is saved without outputs, to keep the file small and the history readable; **Run All** in VS Code recreates them.
- Verified by: `jupyter nbconvert --to notebook --execute demo.ipynb` (output written to the scratchpad) ran with no errors. Printed: "Area code: qvqj9 (Near Katherine)", "Signed warning: 217 bytes (must fit one Bluetooth frame: 383 bytes)", "Signed by the key phones trust? True".

## 8.3 Sweeps with fixed seeds — 2026-09-27
- What: `metrics.sweep(base, parameter, values, repeats)` runs any `Scenario` field over a list of values, each value with several seeds (`base.seed`, `+1`, …), with and without the mesh. It gives one row per run. `metrics.means()` averages the repeats. Also tidied the test imports (removed an unused `geohash` import).
- Ported from: new.
- Differences from the app: not applicable.
- Verified by: `python3 -m pytest tests/test_metrics.py` — 15 passed (6 new). One row per run, and identical rows on a second run (fixed seeds). The test scenario is 800 m square, 10% online, 30 minutes, 2 seeds each; the averages it printed:

  | Changed | Value | With mesh | Internet only |
  |---|---|---|---|
  | Phones | 40 | 22% | 15% |
  | Phones | 300 | 88% | 9% |
  | Bluetooth range | 20 m | 9% | 7% |
  | Bluetooth range | 100 m | 97% | 7% |
  | Moving at 5 m/s (80 phones) | none | 31% | 11% |
  | Moving at 5 m/s (80 phones) | half | 100% | 10% |

  Everyone online gives 100% either way. An unknown field is refused. Full suite: 267 passed. These are simulation results under the simplifications in steps 7.2–7.5, not field measurements.

## 8.2 With the mesh vs internet only — 2026-09-27
- What: `metrics.compare()` and `Comparison` (with `summary()`: warned after 10 minutes, warned at the end, minutes to 80%, told loudly, for both). "Internet only" is the same scenario with Bluetooth off on every phone, so only phones with internet are warned: what a warning app without the mesh would reach.
- Ported from: new.
- Differences from the app: not applicable.
- Verified by: `python3 -m pytest tests/test_metrics.py -k compare` — 4 passed. Both runs have the same phones in the same places, with Bluetooth on or off. Internet only reaches exactly the online phones, at every sample. The mesh never does worse and, in the test scenario, does better. The summary has both rows. Default scenario (300 still phones in 1 km², 10% online): internet only 9.7%, with mesh 64.3%, both flat from the first minute. Full suite: 261 passed.

## 8.1 Share of phones in the area warned over time — 2026-09-27
- What: new module `alertmesh/metrics.py` with `Scenario` (town, number of phones, square size, share online, Bluetooth range, share moving, speed, mesh on/off, level, duration, sample interval, seed), `Result` (`times_s`, `warned_share`, `loud_share`, `in_area`, `first_heard_s`, `final_share`, `time_to_share()`), `area_cells()`, `build()` and `run()`. The warning is signed with the dev key, published to the internet at time 0, and covers the whole square. The measure counts phones where they really are, whatever their location setting.
- Ported from: new.
- Differences from the app: not applicable. The simulation's own limits are listed in steps 7.2–7.5.
- Verified by: `python3 -m pytest tests/test_metrics.py -k coverage` — 5 passed. Warning cells cover squares of 0.5, 1, 4 and 10 km with at most 4 cells. The same seed gives the same layout and the same signed warning. The curve starts at least at the online share and never falls. Everyone warned inside the area was told loudly. `time_to_share` behaves at the edges. A first look at the default scenario (300 still phones in 1 km², 10% online): 64% warned at once and still 64% after an hour. Still phones never meet anyone new, so moving phones matter (step 8.3). Full suite: 257 passed.

## 7.8 Sync sends only what the other phone lacks — 2026-09-27
- What: `Mesh.sync_pair()` now checks what the other phone already holds and sends only what is missing. A newer version of a warning counts as missing.
- Ported from: `AlertMesh/Sync/GossipSyncManager.swift` (each side sends a compact filter of the packet IDs it holds; the reply carries only what the filter lacks).
- Differences from the app: the app's filter is a probabilistic summary (a Golomb-coded set) that now and then wrongly says "already held"; the simulation knows exactly what each phone holds, so it never misses an item that way.
- Checklist change: step 7.8 was added to `PROGRESS.md` at the end of Phase 7, after a timing run showed the old sync was too slow for Phase 8. The total is now 58 steps.
- Verified by: `python3 -m pytest tests/test_mesh_sim.py -k sync` — 6 passed (3 new, plus 3 carry tests whose names contain "sync"). Nothing is offered when the other phone already holds it. A missing newer version is still delivered. 500 phones in a 1 km square for 1 simulated hour: 461 phones warned, the same as before this change, in 1.9 s instead of 12 s (the test allows up to 6 s). Full suite: 252 passed.

## 7.7 SOS and reports through the same mesh — 2026-09-27
- What: `Mesh.send_sos()`, `Mesh.send_safe()`, `Mesh.send_hazard()`; `ReportNotification` and `Phone.report_notifications`; `proximity.sos_urgency()` and `SOS_NEAR_PRECISION` (5). Reports flood, sync and are carried exactly like warnings, and an SOS gets the extra relay hop. Another person's SOS is loud when it is in the same or a neighbouring 5-character cell as this phone or a watched place, and quiet otherwise; it notifies once per level. "I'm safe" is told, quietly, only to phones that were told about that SOS. Hazard reports never notify. A phone is never told about its own reports.
- Ported from: `AlertMesh/AlertMesh/Services/SOSNotificationsModel.swift` (`SOSProximity.urgency`, `handleArrival`, `evaluate`, `reevaluate`) and the send side of `CommunityReportManager` (via `ReportAuthor`, step 3.4).
- Differences from the app: (1) Sending an SOS needs a live location in the simulation. (2) The notification wording (`SOSNotificationContent`) is not modelled; the record keeps the kind, nickname, place, level and note. (3) Reports do not travel over the internet (see step 7.5).
- Verified by: `python3 -m pytest tests/test_mesh_sim.py` — 35 passed (6 new). Also `tests/test_proximity.py` gained 1 test for `sos_urgency` (near, neighbouring cell, far, watched place, no location). An SOS reaches a 5-phone chain and nearby phones are told loudly; the sender is not told. A phone 6 hops away with no location is told quietly, then told about the "I'm safe". A phone that never heard the SOS is not told about the "safe". No SOS without a location. Hazards do not notify. A driving car carries an SOS to a camp 5 km away. Full suite: 249 passed.

## 7.6 Loud or quiet on each phone — 2026-09-27
- What: `Notification`, and on `Phone`: `decide()`, `evaluate()`, `reevaluate()`, `loudest()` and the `notifications` list. A phone decides on arrival and again every tick. It notifies only when a warning version deserves a louder level than it already got, so each version notifies at most once per level. With location off, the remembered area is used.
- Ported from: `AlertMesh/AlertMesh/Services/AlertNotificationsModel.swift` (`evaluate`, `reevaluate`, `versionKey` = event + version) and `NotificationLedger` (loudest level per version); the decision itself is `proximity.decide` from step 4.
- Differences from the app: (1) The app re-checks when it comes to the screen; the simulation re-checks every tick, as if every app were open. (2) The unseen-badge count and the notification wording (`AlertNotificationContent`) are not modelled.
- Verified by: `python3 -m pytest tests/test_mesh_sim.py -k urgency` — 5 passed. In the area at Watch and Act: loud, reason "inside area"; 50 km away: quiet, reason "outside area". Advice in the area: quiet. One notification per version, and an escalation notifies again. A car driving 20 km into the area gets quiet, then loud. With location off: the remembered area and a watched suburb both make it loud; a phone with nothing to go on gets quiet with reason "location unknown", never silent. Full suite: 242 passed.

## 7.5 Phones with internet — 2026-09-27
- What: `Mesh.publish()` and `Mesh.internet_feed`. Every phone with `has_internet` reads new items at once and on each tick. What its store accepts, it floods to its Bluetooth neighbours, so one connected phone warns its camp. A phone that comes online later catches up on everything it missed.
- Ported from: `AlertMesh/AlertMesh/Services/OfficialAlertBridge.swift` (every phone subscribes to all kind-1403 warnings, verifies them, and hands them to its mesh) and `OfficialAlertIssuer` (the console sends over both routes).
- Differences from the app: (1) The internet is one shared list, not Nostr relays: no relay choice, delay, 200-event backfill limit or outages. (2) Only official warnings travel over the internet. In the app, SOS calls also go online but reach only the region; the simulation carries reports by Bluetooth only. (3) The closed-app background check (`BackgroundWarningCheck`, only when Tor is off) is not modelled; a phone with `has_internet` behaves like an open app.
- Verified by: `python3 -m pytest tests/test_mesh_sim.py -k internet` — 5 passed. An online phone gets a published warning at once, and its whole camp holds it in the same tick. A phone coming online later catches up. A forged post is dropped by every phone. A cancellation reaches the camp the same way. Full suite: 237 passed.

## 7.4 Carrying: sync between neighbours and moving phones — 2026-09-27
- What: `Mesh.links()`, `Mesh.sync_pair()` and sync inside `Mesh.step()`. Two phones swap every warning and report they hold (both ways) when they first come into range, and every 60 s after that (`SYNC_INTERVAL_S`). Sync copies are not flooded onward; they spread one hop per sync, like the app's TTL-0 sync replies. Phones on a route drive each tick.
- Ported from: `AlertMesh/Sync/GossipSyncManager.swift` (`officialAlertSyncIntervalSeconds` and `communityReportSyncIntervalSeconds` of 60 s, `scheduleInitialSyncToPeer` about 5 s after meeting, and `ttl = 0` on replies).
- Differences from the app: (1) The app sends a compact filter of what it holds, and the other phone replies with only what is missing. The simulation offers everything, and the store drops what it already has; the result is the same, only the radio cost differs. (2) All phones share one 60 s timer instead of one each. (3) The "5 s after meeting" sync happens in the same 10 s tick.
- Verified by: `python3 -m pytest tests/test_mesh_sim.py -k carry` — 5 passed. Two camps 5 km apart: with no carrier, camp B hears nothing in an hour. With a car driving across at 15 m/s, camp B holds the warning between 5 and 7 minutes after it was sent. A phone whose Bluetooth was off during the flood gets the warning in the first tick after it comes back. Sync makes no new broadcast. Periodic sync lands at 60 s. Full suite: 232 passed.

## 7.3 Only verified packets relay — 2026-09-27
- What: tests only, no code change. The rule "relay only what the store accepted" was built in step 7.2; this step proves it holds in the mesh.
- Ported from: new. The rule comes from `BLEService.handleOfficialAlert` and `sendOfficialAlertPayload`.
- Differences from the app: none for this rule.
- Verified by: `python3 -m pytest tests/test_mesh_sim.py -k forged` — 5 passed. (1) A forged warning is refused by the sender's own store and never sent. (2) A modified phone that floods it anyway reaches 1 neighbour, which rejects it; no phone stores or offers it, and no phone counts as warned. (3) A real warning with its level downgraded goes nowhere. (4) A fake "I'm safe" claiming someone else's key goes nowhere. (5) A real warning still spreads to all 5 phones alongside a forgery.

## 7.2 Mesh, links and the 7-hop flood — 2026-09-27
- What: `Mesh` (clock, phones, Bluetooth range, links, `broadcast`, `send`, `step`, `run`, and a readable `log`), `relay_ttl()`, `is_urgent()`, `Phone.receive()`, `Phone.first_heard_ms`. Constants `MESSAGE_TTL_DEFAULT` (7), `HIGH_DEGREE_THRESHOLD` (6), `DEFAULT_BLUETOOTH_RANGE_M` (60 m), `DEFAULT_TICK_S` (10 s).
- Ported from: the broadcast branch of `AlertMesh/Services/RelayController.swift` (`relay_ttl`); `TransportConfig.messageTTLDefault` and `bleHighDegreeThreshold`; relay-only-if-accepted-or-duplicate from `BLEService.handleOfficialAlert`; "the store is the gate" from `sendOfficialAlertPayload`.
- Differences from the app: (1) Hops within a tick are instant; real relays wait 10–220 ms of random jitter, which is tiny next to a 10-second tick. (2) There is no random relay suppression or radio loss; every phone in range hears every packet. (3) Links are a plain distance cut-off (60 m by default); real Bluetooth range varies with walls, bodies and phones, from about 10 m to over 100 m. (4) Each phone handles each packet once, standing in for the app's message deduplicator.
- Verified by: `python3 -m pytest tests/test_mesh_sim.py -k ttl` — 5 passed. A 10-phone chain carries a warning to the sender plus exactly 7 hops. Links respect range and Bluetooth off. `relay_ttl` gives the `RelayController` numbers for thin, middle, urgent and dense cases. A crowd of 12 hands the packet to each of the other 11 once. First-heard time is kept from the first arrival. Full suite: 222 passed.

## 7.1 Simulated phone — 2026-09-27
- What: new module `alertmesh/mesh_sim.py` with `Phone` and the helpers `offset_m()` and `flat_distance_m()`. Each phone has its own `AlertStore`, `ReportStore` and `ReportAuthor`. It has internet, Bluetooth and location switches, watched places (`bookmarks`), and a route it drives along at a set speed. It gives its own 8-character area code (None with location off) and keeps its last 4-character area as the remembered area. Also defines `OFFICIAL_ALERT_TYPE` (0x2D) and `COMMUNITY_REPORT_TYPE` (0x2E).
- Ported from: new. The remembered area follows `AlertMesh/AlertMesh/Services/RememberedArea.swift` (last precision-4 cell, kept while location is off).
- Differences from the plan: the Bluetooth range is set once for the whole mesh (step 7.2), not per phone. All simulated phones have the same radio, and one range keeps the neighbour search simple.
- Verified by: `python3 -m pytest tests/test_mesh_sim.py -k phone` — 4 passed. A first draft asserted an 8-character Katherine code written from memory; it failed and now checks against `geohash.encode` and the `qvqj9w` prefix verified in step 6.2.

## 6.3 Rough place in words — 2026-09-27
- What: `places.describe()`, `places.label()`, `places.text()`, `places.rounded_km()`, `places.distance_km()`, `places.compass_point()`, the result types `Near` and `Away`, and the limits (15 km town, 5 km place, factor 2, 300 km, 5-character minimum).
- Ported from: `AlertMesh/AlertMesh/Utils/AustralianPlaces.swift` (`describe`, `label(forGeohash:)`, `roundedKm`, `distanceKm`, `compassPoint`, `Limits`, and the English defaults in `Strings.text`).
- Differences from Swift: (1) English only; Swift translates the words into 30 languages and formats "60 km" per locale. (2) The direction is a plain word ("south-west") instead of a Swift enum. (3) Rounding is written to round halves up, like Swift's `rounded()`, because Python's `round()` rounds halves to even. A test pins this.
- Verified by: `python3 -m pytest tests/test_places.py` — 27 passed (19 new in this step). Ports every rule and list test in `AustralianPlacesTests.swift`: `aNearbyTownBeatsACloserSmallPlace`, `aSmallPlaceNamesTheSpotWhenNoTownIsNear`, the 5 cases of `furtherOutItSaysHowFarAndWhichWay`, both landmark tests, `distancesAreRounded`, `nothingWithin300KilometresSaysNothing`, `aCoarseCellGetsNoName`, `wordsCarryTheNameAndTheDistance`, the 4 cases of `territoryTownsReadAsThemselves`, `theDesertGetsADistanceAndDirection`, `outsideAustraliaSaysNothing`. Full suite: 213 passed.

## 6.2 Town lookup, area code, GeoNames credit — 2026-09-27
- What: `places.find()`, `places.find_all()`, `places.geohash_of()` (default 7 characters, the SOS precision) and `places.CREDIT`. Lookup ignores case and spaces at the ends. When a name repeats (87 names do), the largest town comes first.
- Ported from: `AlertMesh/AlertMesh/Utils/AustralianPlaces.swift` (`Strings.credit`). Name lookup is new: the Swift app never looks places up by name.
- Differences from Swift: `find`/`find_all` have no Swift equivalent; they exist so the demo can place phones by town name.
- Finding (Swift side, not changed): the Swift test comments call the `r7hg…` cells "around Fitzroy Crossing, WA", and the reference warning names Mount Barker. In fact `r7hg` is near Brisbane, QLD (centre about −27.51, 153.11). Fitzroy Crossing is `quc2…` and Mount Barker SA is `r1f8…`. Only the comments are wrong; no code depends on the place.
- Verified by: `python3 -m pytest tests/test_places.py -k lookup` — 5 passed. Sydney encodes to `r3gx2f`, its widely published geohash. Five Northern Territory and WA towns decode to boxes that contain them. Mount Barker gives 2 matches, with SA first.

## 6.1 Read towns and places from the Swift data file — 2026-09-27
- What: new module `alertmesh/places.py` with `Place`, `DATA_FILE`, `all_places()` and `towns()`. Reads the `towns` and `places` lists out of the Swift file at run time. Coordinates are stored in thousandths of a degree and converted to degrees. Malformed lines are skipped. A clear error explains what to do if the Swift file is missing.
- Ported from: `AlertMesh/AlertMesh/Utils/AustralianPlaces.swift` (`AustralianPlace`, `all`, `parse`); data from `AustralianPlacesData.swift`.
- Differences from Swift: Swift compiles the list into the app; Python reads the Swift source file, so `python-prototype/` must stay next to `alert-mesh/`.
- Checklist change: step 6.3 (rough place in words, "Near Katherine") was added to `PROGRESS.md`. The Swift `AustralianPlaces` does more than the original plan listed, and the demo needs the wording. The total is now 57 steps.
- Verified by: `python3 -m pytest tests/test_places.py -k load` — 3 passed. 996 towns and 3,396 smaller places load (the counts in the data file's own header), all inside Australia. Ports `theListParsesAndStaysInAustralia`.

## 5.5 Report store — 2026-09-27
- What: new module `alertmesh/report_store.py` with `ReportStore` (`ingest`, `ingest_payload`, `live_reports`, `sync_candidates`, `wipe`) and the limits `MAX_REPORTS` (300), `MAX_HAZARD_REPORTS_PER_AUTHOR` (5), `MAX_CHECK_INS_PER_AUTHOR` (2). A record is one (author, report ID) pair; a later version from the same author replaces it. Quotas are counted per author and separately for hazards and check-ins. When a quota or the store is full, hazards go first, then "safe", then an SOS last; oldest first within each. Sort order: SOS, then hazards by severity, then "safe"; newest first within each. Same time rules as the warning store, with the lifetime per kind.
- Ported from: `AlertMesh/AlertMesh/Services/CommunityReportStore.swift` (`ingest`, `ingestLocked`, `evictLocked`, `ordered`, `Limits`, and the rank helpers).
- Differences from Swift: (1) Memory only, no saving to disk, like the warning store. (2) It reuses `IngestResult` and `CLOCK_SKEW_MS` from `alert_store.py` instead of its own copies; the values are the same.
- Verified by: `python3 -m pytest tests/test_report_store.py` — 16 passed. Ports `reportWhoseSignatureDoesNotMatchItsAuthorKeyIsRejected`, `strangerCannotMarkAuthorSafe`, both duplicate tests, the four time tests, `safeWithSameIDAndAuthorReplacesSOS`, `staleSOSArrivingAfterSafeIsRejected`, `updatedHazardReportReplacesOlderVersion`, `fiveHazardReportsDoNotEvictTheAuthorsSOS`, `hazardQuotaEvictsOldestHazardOnly`, `checkInQuotaIsSeparateAndEvictsSafeBeforeSOS`, `quotasAreCountedPerAuthor`, `globalCapEvictsHazardReportsBeforeSOSCalls`, `reportsAreOrderedSOSFirstThenHazardBySeverityThenSafe`, `expiredReportsAreSwept`, and the memory part of `wipeClearsMemoryAndDisk`. The three Swift persistence tests are not ported (no disk). One extra test: reports signed by `ReportAuthor` (step 3.4) flow through the store, and an SOS followed by "I'm safe" leaves one record. Full suite: 186 passed.

## 5.4 Warning store: 500 cap, order, wipe — 2026-09-27
- What: `MAX_ALERTS` (500): when full, the warnings issued earliest are dropped first. The new warning still counts as accepted even if it was the one dropped, so it keeps spreading. Adds `AlertStore.wipe()`.
- Ported from: `AlertMesh/AlertMesh/Services/OfficialAlertStore.swift` (`Limits.maxAlerts` and the eviction in `ingestAlertLocked`, `wipe`, `ordered`).
- Differences from Swift: `wipe()` clears memory only; there is no file to delete and no notification to send.
- Verified by: `python3 -m pytest tests/test_alert_store.py` — 25 passed. New in this step: `globalCapEvictsOldestIssued`, `alertsAreOrderedBySeverityThenRecency`, and the memory part of `wipeClearsMemoryAndDisk`. The Swift persistence tests (`persistsAcrossRestart`, `restoreDropsEntriesThatNoLongerVerify`, `unreadableFileIsNeverOverwrittenAndMergesOnceReadable`) are not ported, because the Python store does not save to disk. Full suite: 170 passed.

## 5.3 Warning store: cancellations — 2026-09-27
- What: `AlertStore` now takes cancellations. A cancellation removes the warning and is kept until the warning's own expiry, so it keeps spreading. A copy of the cancelled version is refused. A later version reinstates the warning. A cancellation older than the version held is rejected. A cancellation for a warning not seen yet ("orphan") is kept for at most 7 days and suppresses that warning if it arrives; at most 100 orphans are kept, oldest dropped first. `sync_candidates()` now includes live cancellations. Adds `ORPHAN_CANCELLATION_LIFETIME_MS` and `MAX_ORPHAN_CANCELLATIONS`.
- Ported from: `AlertMesh/AlertMesh/Services/OfficialAlertStore.swift` (`ingestCancellationLocked`, the cancellation check at the top of `ingestAlertLocked`, cancellation pruning).
- Differences from Swift: the `retainUntilOverride` path, used only when restoring from disk, is not ported, because the Python store is memory-only.
- Verified by: `python3 -m pytest tests/test_alert_store.py -k cancel` — 10 passed. Ports `cancellationSignedByAnotherKeyIsRejected`, `cancellationRemovesAlertAndPropagatesUntilOriginalExpiry`, `cancellationArrivingBeforeAlertSuppressesIt`, `reissueAfterCancellationIsAcceptedAndSupersedesIt`, `staleCancellationDoesNotRemoveNewerVersion`, `duplicateCancellationIsDuplicate`, `orphanCancellationRetentionIsBoundedByReceiveTime`, `orphanCancellationCapEvictsOldest`, `matchedCancellationsAreExemptFromOrphanCap`. One extra test: a cancellation issued more than 1 hour ahead is rejected. Full suite: 167 passed.

## 5.2 Warning store: time rules — 2026-09-27
- What: `CLOCK_SKEW_MS` (1 hour). `AlertStore` now rejects a warning that has already expired, one issued more than 1 hour ahead of this phone's clock, and one expiring more than 7 days + 1 hour from now. Expired warnings are swept on every ingest and read.
- Ported from: `AlertMesh/AlertMesh/Services/OfficialAlertStore.swift` (`Limits.clockSkewMs`, the time guards in `ingestAlertLocked`, `pruneExpiredLocked`).
- Differences from Swift: none.
- Verified by: `python3 -m pytest tests/test_alert_store.py -k time` — 6 passed. Ports `rejectsAlreadyExpiredAlert`, `rejectsAlertIssuedBeyondClockSkew`, `acceptsAlertIssuedWithinClockSkew`, `rejectsAlertExpiringTooFarInTheFuture`, `expiredAlertsAreSwept`. One extra test pins the skew at 1 hour. Full suite: 157 passed.

## 5.1 Warning store: versions — 2026-09-27
- What: new module `alertmesh/alert_store.py` with `IngestResult` and `AlertStore` (`ingest`, `ingest_payload`, `live_alerts`, `sync_candidates`). Keeps one version per event: newer replaces, equal is a duplicate, older is rejected. Checks the signature first; a store with no key accepts nothing. `live_alerts()` sorts most severe first, then newest.
- Ported from: `AlertMesh/AlertMesh/Services/OfficialAlertStore.swift` (`ingest`, `ingestAlertLocked` version rules, `liveAlerts`, `syncCandidates`, `ordered`).
- Differences from Swift: (1) Swift stores the whole mesh packet (`BitchatPacket`); Python stores the warning's wire payload, because the simulation has no packet header. (2) No saving to disk, no thread queue, no Combine publishers: the simulation runs in one process and memory only. (3) Time rules, cancellations and the 500 cap come in steps 5.2–5.4.
- Verified by: `python3 -m pytest tests/test_alert_store.py -k versions` — 6 passed. Ports `alertSignedByAnotherKeyIsRejectedAndNotStored`, `storeWithoutAPublisherKeyAcceptsNothing`, `ingestStoresAndDeduplicates`, `sameVersionFromDifferentPacketIsDuplicate`, `newerVersionOfSameEventReplacesStoredAlert`, `olderVersionArrivingLaterIsRejected`. One extra test: malformed bytes are rejected.

## 4.3 No location and the remembered area — 2026-09-27
- What: `proximity.decide()` gains `remembered_cell` and the unknown-location rule. With no location and no watched place, a warning is quiet with the reason "location unknown", never silent. With no live location, a warning inside or covering the remembered rough area counts as inside, so Watch and Act or higher is loud.
- Ported from: `AlertMesh/AlertMesh/Services/AlertProximity.swift` (the `rememberedCell` and `locationUnknown` branches of `decide`).
- Differences from Swift: none. Where the remembered area comes from (`RememberedArea.swift`, the last 4-character cell) is not ported yet; the simulation can pass it in.
- Verified by: `python3 -m pytest tests/test_proximity.py` — 35 passed. New in this step: `unknownLocationKeepsEmergencyWarningsQuietNotSilent`, both cases of `unknownLocationKeepsLowerSeveritiesQuietToo`, `aWarningInsideTheRememberedAreaIsLoud`, `aWarningCoveringTheRememberedAreaIsLoud`, `adviceInTheRememberedAreaStaysQuiet`, `aLiveFixWinsOverTheRememberedArea`, `aRememberedAreaThatDoesNotMatchIsStillLocationUnknown`. One extra test runs 135 combinations (3 levels × 3 areas × 5 location set-ups × 3 remembered areas) and checks that none is silent. Every test in `AlertProximityTests.swift` now has a Python match. Full suite: 145 passed.

## 4.2 Loud-or-quiet decision with location and watched places — 2026-09-27
- What: `proximity.Urgency`, `ReasonKind`, `Reason`, `Decision`, and `decide(severity, area_cells, device_geohash, bookmarks)`.
- Ported from: `AlertMesh/AlertMesh/Services/AlertProximity.swift` (`AlertUrgency`, `AlertProximityReason`, `AlertProximityDecision`, `AlertProximity.decide`).
- Differences from Swift: (1) Swift's reason is an enum with attached values; Python uses `Reason(kind, cell, bookmark)`, and `ReasonKind` values are the Swift case names. (2) This step leaves out the no-location rule and the remembered area; step 4.3 adds both. Until then, a phone with no location and no watched place gets "quiet, outside the area".
- Verified by: `python3 -m pytest tests/test_proximity.py -k decide` — 13 passed. Ports all cases of `insideMapsBySeverity`, `adjacentIsAlwaysQuiet`, `elsewhereIsQuietWhenLocationIsKnown`, plus `bookmarkInsideAreaIsLoudWithoutAnyDeviceLocation`, `bookmarkElsewhereWithNoDeviceLocationIsNotLocationUnknown`, `deviceLocationOutranksAWeakerBookmarkMatchAndViceVersa`. One extra test covers a watched place next to the area.

## 4.1 Proximity match for one place — 2026-09-27
- What: new module `alertmesh/proximity.py` with `Match` (ELSEWHERE, ADJACENT, INSIDE), `MINIMUM_PRECISION_FOR_ADJACENCY` (5) and `match(place, area_cells)`.
- Ported from: `AlertMesh/AlertMesh/Services/AlertProximity.swift` (`AlertProximityMatch`, `AlertProximity.match(place:areaCells:)` and its private single-cell `match`).
- Differences from Swift: none. Returns a `(match, cell)` tuple like the Swift tuple.
- Verified by: `python3 -m pytest tests/test_proximity.py -k match` — 13 passed. Ports all 7 cases of `containmentByPrefix`, `coarsePlaceContainingTheWarningIsAdjacentNotInside`, `neighbouringCellAtPrecisionFiveIsAdjacent`, `neighbouringCellAtPrecisionFourIsNotAdjacent`, `precisionFourAlertAgainstPrecisionEightDevice`, `placeCoarserThanCellCannotBeAdjacent`. One extra test covers an empty place or an empty cell list.

## 3.4 Report signing, verification and supersession — 2026-09-27
- What: `reports.verify()`, `reports.supersedes()`, and `reports.ReportAuthor`: one person's key, with `hazard()`, `sos()` and `safe()`.
- Ported from: `AlertMesh/AlertMesh/Protocols/CommunityReportPackets.swift` (`verifySignature`, `supersedes`) and the signing part of `AlertMesh/AlertMesh/Services/CommunityReportManager.swift` (`send`, `sendHazard`, `sendSOS`, `markSafe`).
- Differences from Swift: (1) `ReportAuthor` ports only the signing rules of the manager: trim the note, cut SOS/safe to precision 7, trim the nickname to 32 bytes, reuse the report ID of the last check-in, step `created_at` past the version it replaces, and fall back to the SOS's place for "safe" with no location. Send states, resending and the transport are left out; the mesh simulation (Phase 7) sends. (2) Swift's fallback uses the *active* SOS (live and not answered). Python uses the last check-in if it is an SOS, and does not check expiry. (3) The `ReportAuthor` tests come from the Swift manager code, not from `CommunityReportManagerTests.swift` line by line. (4) The Swift key is the device's Noise signing key; Python makes a fresh Ed25519 key per person.
- Verified by: `python3 -m pytest tests/test_reports.py` — 32 passed. Ports `forgedSignatureFailsVerification`, the six tamper tests (including `flippingAnSOSIntoSafeFailsVerification`), `toleratesUnknownHazardTypeAndStillVerifies`, the four supersession tests (including `strangerCannotSupersedeAnSOS`), `maximalReportFitsOneBLEFrame` (344 bytes), and `frozenSOSEncodesToTheFrozenBytes` (signed with the seed-0x01…0x20 key, decodes and verifies). Full suite: 110 passed.

## 3.3 Report encode, decode and receipt rules — 2026-09-27
- What: `reports.encode()`, `reports.decode()`, `reports.is_valid_geohash()`, `reports.kind_peek()`.
- Ported from: `AlertMesh/AlertMesh/Protocols/CommunityReportPackets.swift` (`CommunityReportWire.encode`, `decode(from:)`, `kind(in:)`, `isValidGeohash`).
- Differences from Swift: none in behaviour. `decode()` reuses `wire.read_tlvs()` with no repeatable fields, which gives the Swift rule "no field repeats". These tests use dummy keys and signatures, because decoding checks structure only; signing and verifying are step 3.4.
- Verified by: `python3 -m pytest tests/test_reports.py -k "encode or validation"` — 12 passed. The frozen SOS vector's 117-byte prefix (everything before the signature) matches (`frozenSOSEncodesToTheFrozenBytes`, structure part). Ports `encodedPrefixIsFrozen`, the four round-trip tests, the four precision tests, the three lifetime tests, the six bounds tests, `rejectsUnknownSeverity`, `rejectsUnknownKind`, both duplicate tests, `toleratesUnknownTLVs`, `rejectsTruncatedPayload`, `rejectsMissingSignature`, both kind-peek tests, and `aReportIsNotAnOfficialAlert`. Full suite: 99 passed.

## 3.2 Report data class and signing bytes — 2026-09-27
- What: `reports.CommunityReport` (frozen data class, with a `hazard` property), `reports.report_signing_bytes()`, `reports.signing_bytes_of()`.
- Ported from: `AlertMesh/AlertMesh/Protocols/CommunityReportPackets.swift` (`CommunityReportPacket`, `CommunityReportPacket.signingBytes`).
- Differences from Swift: none in behaviour. The Python module reuses the byte helpers `_context`, `_len16`, `_u64` from `wire.py`, as the Swift file reuses `BoardWireEncoding`.
- Verified by: `python3 -m pytest tests/test_reports.py -k signing` — 6 passed (5 new, plus the 3.1 signing-context test). Checks the frozen prefix `0x13 "alertmesh-report-v1"` then the kind byte (`signingContextIsFrozenAndDistinct`), every field's position against the spec, that SOS and "safe" sign different bytes, and that severity and hazard are signed.

## 3.1 Report constants, kinds and severities — 2026-09-27
- What: new module `alertmesh/reports.py` with the field limits, lifetimes, signing context, `MESSAGE_TYPE` (0x2E), and the `ReportKind`, `ReportSeverity`, `ReportTLVType` enums.
- Ported from: `AlertMesh/AlertMesh/Protocols/CommunityReportPackets.swift` (`CommunityReportWireConstants`, `CommunityReportKind`, `CommunityReportSeverity`, `CommunityReportTLVType`).
- Differences from Swift: `MESSAGE_TYPE` is a written-out number here; in Swift it comes from upstream's `MessageType` enum.
- Verified by: `python3 -m pytest tests/test_reports.py -k constants` — 4 passed. Ports `wireValuesAreFrozen` and the constant part of `signingContextIsFrozenAndDistinct`. An extra test checks that report severities share no names with official warning levels.

## 2.10 Warning draft checks and dev signer — 2026-09-27
- What: new module `alertmesh/signer.py`: `WarningDraft` (with `problems` and `WarningDraft.updating()`), `Problem`, `OfficialAlertSigner` (`sign`, `cancel`, `public_key`), `new_alert_id()`, `next_issued_at()`, and `DEV_PRIVATE_KEY` (marked dev-only).
- Ported from: `AlertMesh/AlertMesh/Services/OfficialAlertSigning.swift` (`WarningDraft`, `OfficialAlertSigner`) and `OfficialAlertIssuer.swift` (`nextIssuedAt`, random `makeAlertID`).
- Differences from Swift: (1) `PublisherKeyStore` (Keychain) is not ported; the Python signer takes the key directly and defaults to the public dev key. (2) Text trimming uses Python's `str.strip()`, which removes Unicode whitespace; Swift's `trimmingCharacters(in: .whitespacesAndNewlines)` is close but may differ on rare characters. (3) The issuer's sending (Bluetooth + internet) is not ported; the simulation does that in Phase 7.
- Verified by: `python3 -m pytest tests/test_signer.py` — 9 passed. Ports `matchesTheFrozenVectorFromTheSigningScript` (215 bytes, first 151 match, verifies against the pinned key), `anInvalidDraftIsNeverSigned`, `draftProblemsCoverEveryField`, `anUpdateKeepsTheEventAndMovesTheVersionOn`, `anUpdateDraftStartsFromTheWarning`, `eachIssueIsANewEvent`, and the signer part of `aCancellationVerifiesAndCarriesTheWarningsArea`. Full suite: 78 passed.

## 2.9 Size budget — 2026-09-27
- What: tests only, no code change.
- Ported from: `AlertMeshTests/AlertMesh/Protocols/AlertPacketsTests.swift` (`maximalAlertFitsOneBLEFrame`).
- Differences from Swift: the Swift test checks `<= 383`. Python also checks the exact figure of 370 from the spec, so any growth shows up at once. It also checks the two frozen example sizes (215 and 101).
- Verified by: `python3 -m pytest tests/test_wire.py -k budget` — 3 passed (2 new, plus the 2.1 budget-constant test, whose name also contains "budget").

## 2.8 Cancellations — 2026-09-27
- What: `wire.AlertCancellation`, `wire.cancellation_signing_bytes()`, `wire.encode_cancellation()`, and `wire.encode()`, which handles either kind. `decode()` and `verify()` now handle cancellations too.
- Ported from: `AlertMesh/AlertMesh/Protocols/AlertPackets.swift` (`AlertCancellationPacket`, the `.cancellation` cases of `AlertWire.encode` / `decode`).
- Differences from Swift: none.
- Verified by: `python3 -m pytest tests/test_wire.py -k cancellation` — 7 passed. The frozen 101-byte vector decodes and verifies against the pinned key. A Python-signed copy matches its first 37 bytes, and with the Swift signature all 101 bytes match. Ports `cancellationRoundTrip`, `cancellationSignedByAnotherKeyFailsVerification`, `cancellationRetargetedToAnotherAlertFailsVerification`, `flippingASignedAlertIntoACancellationFailsVerification`, `flippingACancellationIntoAnAlertFailsDecode`, `cancellationRejectsMissingFields`, `decodesTheFrozenCancellationVectorFromTheSigningScript`. Full suite: 67 passed.

## 2.7 Attack tests — 2026-09-27
- What: tests only, no code change. Each attack keeps a genuine signature and changes the content.
- Ported from: `AlertMeshTests/AlertMesh/Protocols/AlertPacketsTests.swift` (`tamperedHeadlineFailsVerification`, `tamperedSeverityFailsVerification`, `addingAnAreaCellFailsVerification`, `movingBytesBetweenHeadlineAndActionFailsVerification`).
- Differences from Swift: two extra tests. (1) Changed times or event ID fail. (2) An untouched warning still verifies, so the attack tests cannot pass by accident.
- Verified by: `python3 -m pytest tests/test_wire.py -k attack` — 6 passed.

## 2.6 Decode a warning and verify its signature — 2026-09-27
- What: `wire.decode()`, `wire.verify()`, `wire.verify_pinned()`, `wire.severity_peek()`. `decode()` returns an `OfficialAlert` or None. Cancellations come in step 2.8.
- Ported from: `AlertMesh/AlertMesh/Protocols/AlertPackets.swift` (`AlertWire.decode`, `verify(using:)`, `verifyAgainstPinnedPublisher`, `AlertWire.severity(in:)`) and `BoardWireEncoding.verify` / `uint64(from:)` in `AlertMesh/Protocols/BoardPackets.swift`.
- Differences from Swift: (1) Swift returns an `AlertWire` enum (`.alert` / `.cancellation`); Python returns the data object itself. (2) `severity_peek()` was not a separate step in `PROGRESS.md`; it is added here because it sits in the same Swift type and the mesh simulation needs it for relay priority. (3) A kind byte of `0x02` returns None until step 2.8.
- Verified by: `python3 -m pytest tests/test_wire.py -k decode` — 16 passed. Ports `decodesTheFrozenVectorFromTheSigningScript` (the Swift-made vector decodes and verifies against the pinned key), `frozenVectorFailsAgainstAnUnrelatedKey`, `alertRoundTrip`, `multipleAreaCellsRoundTripInOrder`, `emptyActionTextIsAllowed`, `forgedSignatureFailsVerification`, `alertFromAnotherKeyFailsAgainstPinnedPublisher`, the 9 bounds tests, `rejectsUnknownSeverity`, `toleratesUnknownHazardTypeAndStillVerifies`, `cycloneAndHeatwaveRoundTrip`, both duplicate tests, `areaCellsRemainRepeatable`, both unknown-TLV tests, `rejectsTruncatedPayload`, and both severity-peek tests. The Verify command in `PROGRESS.md` was widened from `-k decodes_frozen_vector` to `-k decode`, to cover all of these.

## 2.5 Encode a warning — 2026-09-27
- What: `wire.encode_alert()`.
- Ported from: `AlertMesh/AlertMesh/Protocols/AlertPackets.swift` (`AlertWire.encode`, `.alert` case).
- Differences from Swift: none. Same field order.
- Verified by: `python3 -m pytest tests/test_wire.py -k frozen_vector_prefix` — 3 passed. (1) Signed in Python with the dev key: 215 bytes, first 151 equal the frozen vector (the spec's rule). (2) With the Swift-made signature: all 215 bytes equal. (3) First 7 bytes frozen (`encodedPrefixIsFrozen`).

## 2.4 Warning signing bytes — 2026-09-27
- What: `wire.alert_signing_bytes()`, `wire.signing_bytes_of()`, and the private helpers `_context`, `_len16`, `_u64`. The tests now hold the frozen alert and cancellation vectors, copied from `AlertPacketsTests.swift`.
- Ported from: `AlertMesh/AlertMesh/Protocols/AlertPackets.swift` (`OfficialAlertPacket.signingBytes`) and `AlertMesh/Protocols/BoardPackets.swift` (`BoardWireEncoding.appendContext`, `appendLengthPrefixed`, `appendUInt64`).
- Differences from Swift: none.
- Verified by: `python3 -m pytest tests/test_wire.py -k signing_bytes` — 3 passed. The 22-byte frozen prefix matches (`signingContextIsFrozen`). The byte layout matches the spec table. The Swift-made signature in the frozen vector verifies over the bytes Python builds, against the pinned dev key.

## 2.3 Warning data class and receipt rules — 2026-09-27
- What: `wire.OfficialAlert` (frozen data class, with a `hazard` property that is None for an unknown code), `wire.is_valid_area_cell()`, `wire.alert_fields_are_valid()`.
- Ported from: `AlertMesh/AlertMesh/Protocols/AlertPackets.swift` (`OfficialAlertPacket`, `AlertWire.isValidAreaCell`, and the `guard` at the end of `AlertWire.decode` for `.alert`).
- Differences from Swift: the Swift rules sit inside `decode`. Python pulls them into `alert_fields_are_valid()` so each rule can be tested alone; `decode` (step 2.6) calls it. `area_cells` is a tuple, so the data class can be frozen.
- Verified by: `python3 -m pytest tests/test_wire.py -k validation` — 5 passed. Ports the rule parts of `emptyActionTextIsAllowed`, `rejectsMissingAreaCells`, `rejectsTooManyAreaCells`, `rejectsInvalidGeohashCharacters`, `rejectsAreaCellOutsidePrecisionBounds`, `rejectsOversizedHeadline`, `rejectsEmptyHeadline`, `rejectsExpiryBeforeIssue`, `rejectsExpiryBeyondSevenDays`. Step 2.6 runs the same cases again through a real encode and decode.

## 2.2 Field reader and writer (TLV) — 2026-09-27
- What: `wire.put_tlv()` and `wire.read_tlvs()`.
- Ported from: `AlertMesh/AlertMesh/Protocols/AlertPackets.swift` (`AlertWire.encode` → `putTLV`, and the loop at the top of `AlertWire.decode`).
- Differences from Swift: the Swift loop reads fields and checks values in one pass. Python splits this into `read_tlvs()` (structure and duplicates) and the decoder (values, step 2.6). The rules are the same: a truncated field rejects; 1–2 stray trailing bytes are ignored; a repeated known field rejects, except the ones marked repeatable; unknown types pass through for the caller to skip. `read_tlvs()` is reused for community reports (step 3.3).
- Verified by: `python3 -m pytest tests/test_wire.py -k tlv` — 8 passed (7 new tests, plus the 2.1 test about the retired 0x06 field, whose name also contains "tlv").

## 2.1 Warning constants, hazard and severity values — 2026-09-27
- What: `alertmesh/wire.py` with the field limits, `MAX_ENCODED_BYTES`, signing contexts, `PINNED_PUBLIC_KEY`, and the `HazardType`, `Severity`, `TLVType`, `WireKind` enums.
- Ported from: `AlertMesh/AlertMesh/Protocols/AlertPackets.swift` (`AlertWireConstants`, `AlertHazardType`, `AlertSeverity`, `AlertTLVType`, `AlertWireKind`) and `AlertPublisherKey.swift`.
- Differences from Swift: (1) `MAX_ENCODED_BYTES` is computed from written-out numbers (469 − 14 − 8 − 64), because Python has no `TransportConfig` or `BinaryProtocol` to read them from. (2) The pinned key is always the development key, like a Swift DEBUG build. A Swift Release build pins no key.
- Verified by: `python3 -m pytest tests/test_wire.py -k constants` — 6 passed. Ports `hazardWireValuesAreFrozen`, `severityIsOrdered`, `budgetIsDerivedFromUpstreamPacketOverhead`.

## 1.4 Geohash neighbors — 2026-09-27
- What: `geohash.neighbors()`, in N, NE, E, SE, S, SW, W, NW order.
- Ported from: `AlertMesh/Protocols/Geohash.swift` (`neighbors(of:)`).
- Differences from Swift: none. Same centre-offset method, same date-line wrap, same skipping of cells past a pole.
- Verified by: `python3 -m pytest tests/test_geohash.py -k neighbors` — 4 passed. Includes the Swift pole test (`geohashNeighborsNearPoleSkipOutOfBoundsCells`). A first draft of the test used neighbour cells written from memory, and they were wrong; the test now checks each neighbour's position geometrically instead.

## 1.3 Geohash decode_bounds and decode_center — 2026-09-27
- What: `geohash.decode_bounds()` and `geohash.decode_center()`.
- Ported from: `AlertMesh/Protocols/Geohash.swift` (`decodeBounds`, `decodeCenter`).
- Differences from Swift: `decode_center` reuses `decode_bounds` instead of repeating the loop. Same result.
- Verified by: `python3 -m pytest tests/test_geohash.py -k decode` — 3 passed (box contains the point at precisions 1–9; centre re-encodes to the same cell).

## 1.2 Geohash encode — 2026-09-27
- What: `geohash.encode(latitude, longitude, precision)`.
- Ported from: `AlertMesh/Protocols/Geohash.swift` (`encode`).
- Differences from Swift: none. Same clamping and same empty result for precision ≤ 0.
- Verified by: `python3 -m pytest tests/test_geohash.py -k encode` — 3 passed, including the standard example `u4pruydqqvj` and the Swift prefix test (`geohashEncoderPrecisionMapping`).

## 1.1 Geohash alphabet and is_valid — 2026-09-27
- What: `alertmesh/geohash.py` with `BASE32` and `is_valid()`.
- Ported from: `AlertMesh/Protocols/Geohash.swift` (`base32Chars`, `isValidGeohash`).
- Differences from Swift: none. Same 1–12 length rule, same case-insensitive check.
- Verified by: `python3 -m pytest tests/test_geohash.py -k valid` — 3 passed.

## 0.3 VS Code setup, package and smoke test — 2026-09-27
- What: `.vscode/settings.json` (pytest in the Testing panel), `.vscode/launch.json` ("Streamlit demo" and "Run all tests"), `pytest.ini`, empty `alertmesh` package, `tests/test_smoke.py`, and `tools/update_status.py`, which recounts the Status table in `PROGRESS.md` so it never drifts.
- Ported from: new.
- Differences from Swift: not applicable.
- Verified by: `python3 -m pytest -q` — 1 passed. `python3 tools/update_status.py` — "3/56 steps done. Next step: 1.1".

## 0.2 Progress checklist and changelog — 2026-09-27
- What: `PROGRESS.md` lists all 56 steps, each with its Swift source and verify command. This file records each step.
- Ported from: new.
- Differences from Swift: not applicable.
- Verified by: read through; the step counts in the Status table add up to 56.

## 0.1 Folder, README, requirements, ignore file — 2026-09-27
- What: created `python-prototype/` with `README.md`, `requirements.txt`, `.gitignore`.
- Ported from: new.
- Differences from Swift: not applicable.
- Verified by: `python3 -c "import cryptography, plotly, streamlit, pytest, ipykernel, nbconvert"` succeeds on the Anaconda Python 3.13 install.
