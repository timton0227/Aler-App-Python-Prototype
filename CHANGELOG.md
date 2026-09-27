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
