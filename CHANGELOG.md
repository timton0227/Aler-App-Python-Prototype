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
