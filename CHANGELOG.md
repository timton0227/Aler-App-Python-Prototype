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
