"""The files copied from the Swift app are still the same (alertmesh/swift_app.py).

Skipped where the Swift app is not next to this folder.
"""
import pytest

from alertmesh import swift_app


def test_every_copy_is_in_this_repository():
    missing = [copy for copy in swift_app.COPIES if not (swift_app.ROOT / copy).exists()]
    assert missing == []


@pytest.mark.skipif(not swift_app.available(), reason="needs the Swift app (ALERTMESH_SWIFT_APP)")
def test_the_copies_match_the_swift_app():
    assert swift_app.differences() == [], "run python3 tools/copy_from_swift.py"
