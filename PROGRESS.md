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
| 7 Mesh simulation | 2 | 7 |
| 8 Metrics | 0 | 3 |
| 9 Notebook | 0 | 8 |
| 10 Streamlit | 0 | 4 |
| 11 Final check | 0 | 3 |
| **All** | **34** | **57** |

**Next step:** 7.3

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
- [ ] 7.3 Only verified packets relay
      Done when: a forged warning never spreads
      Verify: `python3 -m pytest tests/test_mesh_sim.py -k forged`
- [ ] 7.4 Moving phones carry warnings
      Done when: a warning reaches a group out of range only after a phone drives there
      Verify: `python3 -m pytest tests/test_mesh_sim.py -k carry`
- [ ] 7.5 Phones with internet receive directly
      Verify: `python3 -m pytest tests/test_mesh_sim.py -k internet`
- [ ] 7.6 Each phone's loud/quiet decision
      Verify: `python3 -m pytest tests/test_mesh_sim.py -k urgency`
- [ ] 7.7 SOS and reports travel through the same mesh
      Verify: `python3 -m pytest tests/test_mesh_sim.py`

## Phase 8 — Metrics (new)

- [ ] 8.1 Share of phones in the area warned over time
      Verify: `python3 -m pytest tests/test_metrics.py -k coverage`
- [ ] 8.2 With mesh vs without mesh
      Verify: `python3 -m pytest tests/test_metrics.py -k compare`
- [ ] 8.3 Sweeps over phone density, Bluetooth range, share offline (fixed random seed)
      Verify: `python3 -m pytest tests/test_metrics.py`

## Phase 9 — Notebook (`demo.ipynb`)

Verify each step: `jupyter nbconvert --to notebook --execute demo.ipynb --output /tmp/demo-run.ipynb` runs with no errors.

- [ ] 9.1 Issue a signed bushfire warning
- [ ] 9.2 A forged or edited warning is rejected
- [ ] 9.3 Watch the warning spread on a map
- [ ] 9.4 Who gets a loud alert, who gets a quiet one, and why
- [ ] 9.5 Update, then cancel, the warning
- [ ] 9.6 SOS, then "I'm safe"; a stranger cannot fake "safe"
- [ ] 9.7 Community hazard report
- [ ] 9.8 Charts: with vs without mesh

## Phase 10 — Streamlit (`app.py`)

Verify each step: `streamlit run app.py`, then check the tab in a browser.

- [ ] 10.1 Warning console tab (write, sign, send)
- [ ] 10.2 Map tab (phones light up as the warning spreads)
- [ ] 10.3 Phone view tab (one phone's alerts and the loud/quiet reason)
- [ ] 10.4 Hub board tab (large-type board with the SOS list)

## Phase 11 — Final check

- [ ] 11.1 Cross-check with Swift: Python decodes a packet made by `scripts/sign-test-alert.swift`
- [ ] 11.2 README walk-through in a fresh clone
- [ ] 11.3 `git status` shows no change under `alert-mesh/`

---

## Rules for every step

1. Mark the step `[~]`. Read the Swift file it names, and its Swift tests.
2. Write the Python code. Port the matching Swift test cases.
3. Run the step's **Verify** command. It must pass. Also run `python3 -m pytest -q` so
   nothing else broke.
4. Tick the box `[x]`, then run `python3 tools/update_status.py` to recount the Status
   table and **Next step**. Add a [`CHANGELOG.md`](CHANGELOG.md) entry.
5. Commit only that step's files, with a message that explains why.
