"""Where the Swift app (the reference) is, and which of its files this repository copies.

The Swift app lives in its own repository (github.com/timton0227/Aler-App-Prototype,
folder `alert-mesh/`). It is looked for at `../App_prototype/alert-mesh`, next to this
folder; set ALERTMESH_SWIFT_APP to use another place.

Nothing the apps, the tests or the builds need comes from it at run time: the files in
COPIES are kept in this repository. Only the Swift cross-checks (tools/cross_check_*.py)
and the check that the copies are still the same (tests/test_swift_copies.py) read it,
and both are skipped when it is missing. `python3 tools/copy_from_swift.py` refreshes
the copies.

This is free and unencumbered software released into the public domain.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # this repository
SWIFT_APP = Path(os.environ.get("ALERTMESH_SWIFT_APP") or ROOT.parent / "App_prototype" / "alert-mesh")

_ICON_SIZES = ("16x16", "16x16@2x", "32x32", "32x32@2x", "128x128", "128x128@2x", "256x256", "256x256@2x",
               "512x512", "512x512@2x")

# Copy in this repository -> the Swift app's file it copies.
COPIES: dict[str, str] = {
    "alertmesh/data/AustralianPlacesData.swift": "AlertMesh/AlertMesh/Utils/AustralianPlacesData.swift",
    "alertmesh/data/online_relays_gps.csv": "relays/online_relays_gps.csv",
    "tests/data/nostr_fixtures/LegacyPrivateEnvelope733098bb.json":
        "AlertMeshTests/Nostr/Fixtures/LegacyPrivateEnvelope733098bb.json",
    "tests/data/nostr_fixtures/LegacyPrivateEnvelope733098bbRecipientKey.json":
        "AlertMeshTests/Nostr/Fixtures/LegacyPrivateEnvelope733098bbRecipientKey.json",
    "tests/data/nostr_fixtures/AndroidLegacyPrivateEnvelopeB7f0b33d.json":
        "AlertMeshTests/Nostr/Fixtures/AndroidLegacyPrivateEnvelopeB7f0b33d.json",
    "tests/data/nostr_fixtures/AndroidLegacyPrivateEnvelopeB7f0b33dMetadata.json":
        "AlertMeshTests/Nostr/Fixtures/AndroidLegacyPrivateEnvelopeB7f0b33dMetadata.json",
    **{f"packaging/AlertMesh.iconset/icon_{size}.png": f"AlertMesh/Assets.xcassets/AppIcon.appiconset/icon_{size}.png"
       for size in _ICON_SIZES},
}


def available() -> bool:
    return SWIFT_APP.is_dir()


def differences() -> list[str]:
    """The copies that are missing here or differ from the Swift app's file."""
    return [copy for copy, original in COPIES.items()
            if (SWIFT_APP / original).exists()
            and (not (ROOT / copy).exists() or (ROOT / copy).read_bytes() != (SWIFT_APP / original).read_bytes())]
