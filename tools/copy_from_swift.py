"""Refresh the files this repository copies from the Swift app (see alertmesh/swift_app.py).

    python3 tools/copy_from_swift.py            (copies what changed)
    python3 tools/copy_from_swift.py --check    (only says what changed; exit 1 if anything)

Needs the Swift app at ../App_prototype/alert-mesh, or ALERTMESH_SWIFT_APP set.

This is free and unencumbered software released into the public domain.
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from alertmesh.swift_app import COPIES, ROOT, SWIFT_APP, available, differences  # noqa: E402


def main(check_only: bool) -> int:
    if not available():
        print(f"The Swift app is not at {SWIFT_APP}; set ALERTMESH_SWIFT_APP.")
        return 1
    changed = differences()
    for copy in changed:
        print(f"{'differs' if check_only else 'copied'}: {copy}")
        if not check_only:
            (ROOT / copy).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SWIFT_APP / COPIES[copy], ROOT / copy)
    if not changed:
        print(f"All {len(COPIES)} copies match the Swift app.")
    return 1 if check_only and changed else 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
