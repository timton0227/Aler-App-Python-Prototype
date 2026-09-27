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
