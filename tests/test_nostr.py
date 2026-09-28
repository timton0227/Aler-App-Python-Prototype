"""Tests for alertmesh.nostr.

Ported from: alert-mesh/AlertMeshTests/NostrProtocolTests.swift
             (nostrEventSignatureVerification_roundTrip, _detectsTamper,
             inboundNostrEventRejects*/Accepts*), plus BIP-340's own test vector and
             two events signed by other apps (the Swift tests' frozen fixtures);
         and alert-mesh/AlertMeshTests/AlertMesh/Services/OfficialAlertBridgeTests.swift
             and CommunityReportBridgeTests.swift (the parts about the events themselves).
"""
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from alertmesh import nostr, reports, wire
from alertmesh.reports import ReportAuthor, ReportSeverity
from alertmesh.signer import OfficialAlertSigner, WarningDraft
from alertmesh.wire import HazardType

FIXTURES = Path(__file__).resolve().parent / "data" / "nostr_fixtures"  # copied from the Swift app's tests


# --- BIP-340 --------------------------------------------------------------------


def test_bip340_test_vector_0():
    # BIP-340 test-vectors.csv, index 0: secret key 3, aux and message all zero.
    secret = (3).to_bytes(32, "big")
    assert nostr.public_key(secret).hex().upper() == \
        "F9308A019258C31049344F85F89D5229B531C845836F99B08601F113BCE036F9"
    signature = nostr.schnorr_sign(bytes(32), secret, aux=bytes(32))
    assert signature.hex().upper() == (
        "E907831F80848D1069A5371B402410364BDF1C5F8307B0084C55F1CE2DCA8215"
        "25F66A4A85EA8B71E482A74F382D2CE5EBEEE8FDB2172F477DF4900D310536C0")
    assert nostr.schnorr_verify(bytes(32), nostr.public_key(secret), signature)


def test_public_key_of_1_is_the_android_fixture_sender():
    # The Android fixture's metadata names ...79be... as the sender: the key of 1.
    assert nostr.public_key((1).to_bytes(32, "big")).hex() == \
        "79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"


def test_a_changed_message_or_signature_does_not_verify():
    secret = nostr.new_secret_key()
    message = bytes(range(32))
    signature = nostr.schnorr_sign(message, secret)
    key = nostr.public_key(secret)
    assert nostr.schnorr_verify(message, key, signature)
    assert not nostr.schnorr_verify(bytes(32), key, signature)
    assert not nostr.schnorr_verify(message, key, signature[:-1] + bytes([signature[-1] ^ 1]))
    assert not nostr.schnorr_verify(message, nostr.public_key(nostr.new_secret_key()), signature)
    assert not nostr.schnorr_verify(message, key, signature[:63])


def test_secret_keys_out_of_range_are_refused():
    with pytest.raises(ValueError):
        nostr.public_key(bytes(32))
    with pytest.raises(ValueError):
        nostr.schnorr_sign(bytes(32), b"\xff" * 32)


# --- Events -------------------------------------------------------------------


def test_signed_event_round_trip():
    event = nostr.sign_event(20000, [], "Signed event")
    assert event.is_valid()
    assert len(bytes.fromhex(event.pubkey)) == 32 and len(bytes.fromhex(event.sig)) == 64


def test_tampering_is_detected():
    event = nostr.sign_event(20000, [["g", "r7hg"]], "Original")
    assert not replace(event, id="deadbeef").is_valid()
    assert not replace(event, content="Changed").is_valid()
    assert not replace(event, tags=(("g", "r7hu"),)).is_valid()
    assert not replace(event, sig="zz").is_valid()


def test_each_event_gets_a_fresh_key():
    assert nostr.sign_event(1, [], "a").pubkey != nostr.sign_event(1, [], "a").pubkey


def test_event_id_is_the_nip01_serialization():
    event = nostr.sign_event(1403, [["g", "r7"], ["expiration", "1700000000"]], "QUJD/+=", created_at=1_700_000_000)
    serialized = ('[0,"' + event.pubkey + '",1700000000,1403,[["g","r7"],["expiration","1700000000"]],'
                  '"QUJD/+="]')
    assert event.id == hashlib.sha256(serialized.encode()).hexdigest()


def test_dict_round_trip():
    event = nostr.sign_event(1402, [["g", "r7hg"]], "x")
    back = nostr.Event.from_dict(json.loads(json.dumps(event.to_dict())))
    assert back == event and back.is_valid()


@pytest.mark.parametrize("name", ["LegacyPrivateEnvelope733098bb", "AndroidLegacyPrivateEnvelopeB7f0b33d"])
def test_events_signed_by_other_apps_verify(name):
    path = FIXTURES / f"{name}.json"
    event = nostr.Event.from_dict(json.loads(path.read_text()))
    assert event is not None and event.is_valid()
    assert not replace(event, created_at=event.created_at + 1).is_valid()


def _raw(**changes):
    data = nostr.sign_event(1, [], "x").to_dict()
    data.update(changes)
    return data


def test_inbound_event_rejects_too_many_tags():
    assert nostr.Event.from_dict(_raw(tags=[["t", "x"]] * (nostr.MAX_TAGS + 1))) is None


def test_inbound_event_rejects_too_many_tag_values():
    assert nostr.Event.from_dict(_raw(tags=[["t"] * (nostr.MAX_TAG_VALUES + 1)])) is None


def test_inbound_event_rejects_oversized_tag_values():
    assert nostr.Event.from_dict(_raw(tags=[["t", "x" * (nostr.MAX_TAG_VALUE_BYTES + 1)]])) is None


def test_inbound_event_accepts_tags_within_limits():
    tags = [["t"] + ["x" * nostr.MAX_TAG_VALUE_BYTES] * (nostr.MAX_TAG_VALUES - 1)] * nostr.MAX_TAGS
    assert nostr.Event.from_dict(_raw(tags=tags)) is not None


@pytest.mark.parametrize("changes", [{"kind": "1"}, {"created_at": 1.5}, {"content": 5}, {"tags": "x"},
                                     {"kind": True}])
def test_inbound_event_rejects_wrong_types(changes):
    assert nostr.Event.from_dict(_raw(**changes)) is None


def test_inbound_event_rejects_missing_fields():
    data = _raw()
    del data["sig"]
    assert nostr.Event.from_dict(data) is None
    assert nostr.Event.from_dict("not an object") is None


# --- Warnings and reports as events ---------------------------------------------

NOW_MS = 1_700_000_000_000


def warning(cells=("r7hg2bc", "r7hu"), issued_at=NOW_MS):
    draft = WarningDraft(headline="Flood", action_text="Move to higher ground", duration_hours=6,
                         area_cells=list(cells))
    return OfficialAlertSigner().sign(draft, bytes(range(16)), issued_at)


def test_tags_are_every_short_prefix_of_each_cell():
    assert nostr.tag_cells(["r7hg2bc", "R1"]) == ["r1", "r7", "r7h", "r7hg"]
    assert nostr.tag_cells(["r7h"]) == ["r7", "r7h"]
    assert nostr.tag_cells(["r"]) == []


def test_a_warning_is_tagged_with_its_area_and_expiry():
    alert = warning()
    event = nostr.alert_event(wire.encode(alert), alert.area_cells, alert.expires_at)
    assert event.kind == nostr.KIND_OFFICIAL_ALERT == 1403
    assert ("g", "r7") in event.tags and ("g", "r7hg") in event.tags and ("g", "r7hu") in event.tags
    assert ("g", "r7hg2") not in event.tags
    assert ("expiration", str(alert.expires_at // 1000)) in event.tags
    assert event.is_valid()


def test_the_event_carries_the_signed_warning():
    alert = warning()
    event = nostr.alert_event(wire.encode(alert), alert.area_cells, alert.expires_at)
    payload = nostr.payload_of(event, nostr.KIND_OFFICIAL_ALERT)
    assert payload == wire.encode(alert)
    assert wire.decode(payload) == alert and wire.verify_pinned(wire.decode(payload))


def test_a_cancellation_is_tagged_with_the_warnings_area():
    alert = warning()
    cancellation = OfficialAlertSigner().cancel(alert.alert_id, NOW_MS + 100)
    event = nostr.alert_event(wire.encode(cancellation), alert.area_cells, alert.expires_at)
    assert ("g", "r7hg") in event.tags
    assert ("expiration", str(alert.expires_at // 1000)) in event.tags
    assert wire.decode(nostr.payload_of(event, nostr.KIND_OFFICIAL_ALERT)) == cancellation


def test_updates_and_cancellations_are_new_versions():
    alert = warning()
    update = warning(issued_at=NOW_MS + 1)
    cancellation = OfficialAlertSigner().cancel(alert.alert_id, NOW_MS + 2)
    keys = {nostr.alert_version_key(item) for item in (alert, update, cancellation)}
    assert len(keys) == 3
    assert nostr.alert_version_key(alert) == nostr.alert_version_key(warning())


def test_other_kinds_and_oversize_or_broken_content_are_ignored():
    alert = warning()
    content = nostr.alert_event(wire.encode(alert), alert.area_cells, alert.expires_at).content
    assert nostr.payload_of(nostr.sign_event(1, [], content), nostr.KIND_OFFICIAL_ALERT) is None
    assert nostr.payload_of(nostr.sign_event(1403, [], "A" * 1028), nostr.KIND_OFFICIAL_ALERT) is None
    assert nostr.payload_of(nostr.sign_event(1403, [], "not base64!"), nostr.KIND_OFFICIAL_ALERT) is None


def sos(author=None, geohash="r7hg2bc"):
    return (author or ReportAuthor("Sam")).sos(geohash, "Trapped on roof", NOW_MS)


def test_an_sos_is_tagged_with_its_cell_and_expiry():
    report = sos()
    event = nostr.report_event(report)
    assert event.kind == nostr.KIND_COMMUNITY_REPORT == 1402
    assert list(event.tags) == [("g", "r7hg"), ("expiration", str(report.expires_at // 1000))]
    assert event.is_valid()


def test_the_event_carries_the_signed_report():
    report = sos()
    payload = nostr.payload_of(nostr.report_event(report), nostr.KIND_COMMUNITY_REPORT)
    assert reports.decode(payload) == report and reports.verify(reports.decode(payload))
    assert nostr.payload_of(nostr.report_event(report), nostr.KIND_OFFICIAL_ALERT) is None


def test_each_event_has_its_own_envelope_key():
    report = sos()
    assert nostr.report_event(report).pubkey != nostr.report_event(report).pubkey


def test_only_calls_for_help_and_safe_go_online():
    author = ReportAuthor("Sam")
    assert nostr.is_bridged(sos(author).kind)
    assert nostr.is_bridged(author.safe("r7hg2bc", "", NOW_MS + 1).kind)
    assert not nostr.is_bridged(author.hazard(HazardType.FLOOD, ReportSeverity.HIGH, "r7hg2bc", "", NOW_MS).kind)


def test_report_versions_differ_by_author_id_and_time():
    author = ReportAuthor("Sam")
    first = sos(author)
    safe = author.safe(None, "", NOW_MS + 1)  # answers the SOS: same ID, later time
    assert safe.report_id == first.report_id
    assert nostr.report_version_key(first) != nostr.report_version_key(safe)
    assert nostr.report_version_key(first) != nostr.report_version_key(sos())


def test_the_warning_subscription_asks_for_every_warning():
    subscription = nostr.official_alerts_filter(since_s=1_699_000_000)
    assert subscription == {"kinds": [1403], "since": 1_699_000_000, "limit": 200}
    assert "#g" not in subscription


def test_the_report_subscription_asks_for_nearby_cells():
    cells = nostr.report_cells(["r7hg2bc", None, "r7"])
    assert "r7hg" in cells and len(cells) == 9  # the cell and its 8 neighbours; too-short places are left out
    assert nostr.community_reports_filter(cells, since_s=5) == {"kinds": [1402], "#g": cells, "limit": 200,
                                                               "since": 5}
    assert nostr.report_cells([]) == []


def test_relays_are_the_built_in_ones_unless_named(monkeypatch):
    monkeypatch.delenv(nostr.RELAYS_VARIABLE, raising=False)
    assert nostr.relay_urls() == list(nostr.BUILT_IN_RELAYS)
    monkeypatch.setenv(nostr.RELAYS_VARIABLE, "ws://127.0.0.1:1, ws://127.0.0.1:2,")
    assert nostr.relay_urls() == ["ws://127.0.0.1:1", "ws://127.0.0.1:2"]
