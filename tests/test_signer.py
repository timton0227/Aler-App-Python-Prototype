"""Tests for alertmesh.signer.

Swift reference: alert-mesh/AlertMeshTests/AlertMesh/Services/OfficialAlertIssuerTests.swift.
"""
from alertmesh import wire
from alertmesh.signer import (
    DEV_PRIVATE_KEY, OfficialAlertSigner, Problem, WarningDraft, new_alert_id, next_issued_at,
)
from alertmesh.wire import HazardType, Severity

NOW = 1_700_000_000_000


def draft() -> WarningDraft:
    return WarningDraft(
        hazard=HazardType.BUSHFIRE,
        severity=Severity.EMERGENCY_WARNING,
        headline="Bushfire at Mount Barker - leave now",
        action_text="Travel north on Highway 1. Do not wait.",
        duration_hours=6,
        area_cells=["r7hg", "r7hu"],
    )


def test_matches_the_frozen_vector_from_the_signing_script():
    """Swift: matchesTheFrozenVectorFromTheSigningScript."""
    alert = OfficialAlertSigner(DEV_PRIVATE_KEY).sign(draft(), bytes(range(16)), NOW)
    encoded = wire.encode(alert)
    assert len(encoded) == 215
    expected_prefix = (
        "01000101020010000102030405060708090a0b0c0d0e0f03000472376867030004723768"
        "750400244275736866697265206174204d6f756e74204261726b6572202d206c65617665"
        "206e6f7705002754726176656c206e6f727468206f6e204869676877617920312e20446f"
        "206e6f7420776169742e0700080000018bcfe568000800080000018bd12eff00090001020"
        "a0001030b0040"
    )
    assert encoded[:151].hex() == expected_prefix
    assert wire.verify_pinned(alert)


def test_an_invalid_draft_is_never_signed():
    """Swift: anInvalidDraftIsNeverSigned. The limit is bytes: 51 x "é" is 102 bytes."""
    too_long = draft()
    too_long.headline = "é" * 51
    no_area = draft()
    no_area.area_cells = []
    assert too_long.problems == [Problem.HEADLINE_TOO_LONG]
    assert no_area.problems == [Problem.NO_AREA]
    signer = OfficialAlertSigner()
    assert signer.sign(too_long, new_alert_id(), NOW) is None
    assert signer.sign(no_area, new_alert_id(), NOW) is None


def test_draft_problems_cover_every_field():
    """Swift: draftProblemsCoverEveryField."""
    d = WarningDraft(duration_hours=0, area_cells=["r7hg", "r7hu", "r7hv", "r7hy", "r7hz"])
    assert d.problems == [Problem.NO_HEADLINE, Problem.NO_ACTION, Problem.TOO_MANY_CELLS, Problem.DURATION_OUT_OF_RANGE]
    d.duration_hours = 169
    assert Problem.DURATION_OUT_OF_RANGE in d.problems
    d.duration_hours = 168
    assert Problem.DURATION_OUT_OF_RANGE not in d.problems


def test_signing_trims_text_and_lowercases_cells():
    d = draft()
    d.headline = "  Bushfire at Mount Barker - leave now \n"
    d.area_cells = ["R7HG"]
    alert = OfficialAlertSigner().sign(d, new_alert_id(), NOW)
    assert alert.headline == "Bushfire at Mount Barker - leave now"
    assert alert.area_cells == ("r7hg",)
    assert wire.decode(wire.encode(alert)) == alert


def test_an_update_keeps_the_event_and_moves_the_version_on():
    """Swift: anUpdateKeepsTheEventAndMovesTheVersionOn (signer part)."""
    signer = OfficialAlertSigner()
    first = signer.sign(draft(), new_alert_id(), NOW)
    changed = WarningDraft.updating(first, NOW)
    changed.headline = "Bushfire at Mount Barker - too late to leave"
    updated = signer.sign(changed, first.alert_id, next_issued_at(NOW, first.issued_at))
    assert updated.alert_id == first.alert_id
    assert updated.issued_at > first.issued_at  # same millisecond still moves on
    assert updated.hazard is HazardType.BUSHFIRE
    assert wire.verify_pinned(updated)


def test_an_update_draft_starts_from_the_warning():
    """Swift: anUpdateDraftStartsFromTheWarning. 6 h warning, 2 h 1 min later: 4 h left (rounded up)."""
    alert = OfficialAlertSigner().sign(draft(), new_alert_id(), NOW)
    edit = WarningDraft.updating(alert, NOW + 2 * 3_600_000 + 60_000)
    assert edit.headline == alert.headline
    assert edit.area_cells == list(alert.area_cells)
    assert edit.severity is Severity.EMERGENCY_WARNING
    assert edit.duration_hours == 4


def test_a_cancellation_verifies():
    """Swift: aCancellationVerifiesAndCarriesTheWarningsArea (signer part)."""
    signer = OfficialAlertSigner()
    alert = signer.sign(draft(), new_alert_id(), NOW)
    cancellation = signer.cancel(alert.alert_id, next_issued_at(NOW, alert.issued_at))
    assert cancellation.issued_at > alert.issued_at
    assert wire.verify_pinned(wire.decode(wire.encode(cancellation)))


def test_each_issue_is_a_new_event():
    """Swift: eachIssueIsANewEvent."""
    assert new_alert_id() != new_alert_id()
    assert len(new_alert_id()) == 16


def test_signer_public_key_is_the_pinned_dev_key():
    assert OfficialAlertSigner().public_key == wire.PINNED_PUBLIC_KEY
