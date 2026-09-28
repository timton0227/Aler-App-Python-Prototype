"""Tests for alertmesh.nostr.

Ported from: ../alert-mesh/AlertMeshTests/NostrProtocolTests.swift
             (nostrEventSignatureVerification_roundTrip, _detectsTamper,
             inboundNostrEventRejects*/Accepts*), plus BIP-340's own test vector and
             two events signed by other apps (the Swift tests' frozen fixtures).
"""
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from alertmesh import nostr

FIXTURES = Path(__file__).resolve().parent.parent.parent / "alert-mesh" / "AlertMeshTests" / "Nostr" / "Fixtures"


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
    if not path.exists():
        pytest.skip("the Swift app's test fixtures are not next to this folder")
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
