"""Cross-check against Swift, both ways (tools/cross_check_swift.py).

Skipped where Swift is not installed (it needs a Mac with Xcode or the Swift
toolchain), so the rest of the suite still runs anywhere.
"""
import pytest

from tools import cross_check_swift as cc

pytestmark = pytest.mark.skipif(not cc.swift_available(), reason="needs Swift and the Swift app")


def test_swift_and_python_agree_both_ways():
    failures = {name: problems for name, problems in cc.run() if problems}
    assert failures == {}


def test_the_cases_cover_every_hazard_and_level_and_the_size_limit():
    assert {c.hazard for c in cc.CASES} == set(cc.HAZARDS)
    assert {c.severity for c in cc.CASES} == set(cc.SEVERITIES)
    longest = cc.sign_with_swift(cc.CASES[-1].args())
    assert len(longest) == 370  # the largest warning, still inside the 383-byte frame
