"""Tests for alertmesh.chat.

No Swift tests to port: the chat format is the Python prototype's own (laptops talk to
laptops). The rules mirror the iPhone app's: signed messages, private messages only the
recipient can read.
"""
import dataclasses

import pytest

from alertmesh import chat, reports, wire
from alertmesh.chat import Identity

NOW = 1_790_000_000_000


@pytest.fixture
def alice():
    return Identity("Alice")


@pytest.fixture
def bob():
    return Identity("Bob")


def test_contexts_are_distinct_from_every_other_signature():
    contexts = {chat.ANNOUNCE_CONTEXT, chat.CHAT_CONTEXT, reports.SIGNING_CONTEXT,
                wire.ALERT_SIGNING_CONTEXT, wire.CANCELLATION_SIGNING_CONTEXT}
    assert len(contexts) == 5


def test_identity_survives_a_restart_from_its_seed(alice):
    again = Identity("Alice", alice.seed)
    assert (again.signing_key, again.chat_key) == (alice.signing_key, alice.chat_key)
    with pytest.raises(ValueError):
        Identity("x", b"short")


def test_identity_signs_reports_with_the_same_key(alice):
    author = reports.ReportAuthor("Alice", alice.signing_seed)
    assert author.public_key == alice.signing_key


def test_announce_round_trips_and_verifies(alice):
    announce = alice.announce(NOW)
    decoded = chat.decode_announce(chat.encode_announce(announce))
    assert decoded == announce
    assert chat.verify_announce(decoded)
    assert (decoded.nickname, decoded.chat_key) == ("Alice", alice.chat_key)


def test_announce_with_a_changed_nickname_fails(alice):
    forged = dataclasses.replace(alice.announce(NOW), nickname="Police")
    assert not chat.verify_announce(forged)


def test_announce_missing_a_field_is_malformed(alice):
    data = chat.encode_announce(alice.announce(NOW))
    assert chat.decode_announce(data[:-67]) is None  # signature field removed
    assert chat.decode_announce(b"junk") is None


def test_nearby_message_round_trips_and_verifies(alice):
    message = alice.message("  Road to the bridge is flooded  ", NOW)
    assert message.text == "Road to the bridge is flooded"
    assert not message.is_private
    decoded = chat.decode_message(chat.encode_message(message))
    assert decoded == message
    assert chat.verify_message(decoded)


def test_changed_text_fails_the_signature(alice):
    message = alice.message("Meet at the school", NOW)
    assert not chat.verify_message(dataclasses.replace(message, text="Meet at the river"))


def test_private_message_cannot_be_shown_as_nearby(alice, bob):
    message = alice.message("hi Bob", NOW, to=bob.announce(NOW))
    assert message.is_private
    assert not chat.verify_message(dataclasses.replace(message, recipient_key=b""))


def test_empty_and_oversize_text_are_refused(alice):
    assert alice.message("   ", NOW) is None
    assert alice.message("x" * (chat.TEXT_MAX_BYTES + 1), NOW) is None
    assert alice.message("x" * chat.TEXT_MAX_BYTES, NOW) is not None
    # Multi-byte letters count as bytes, not characters.
    assert alice.message("é" * (chat.TEXT_MAX_BYTES // 2 + 1), NOW) is None


def test_oversize_text_on_the_wire_is_refused(alice):
    message = alice.message("hi", NOW)
    long = dataclasses.replace(message, text="x" * (chat.TEXT_MAX_BYTES + 1))
    assert chat.decode_message(chat.encode_message(long)) is None


def test_long_nickname_is_cut_to_fit(alice):
    alice.nickname = "Ä" * 40
    assert len(alice.announce(NOW).nickname.encode()) <= chat.NICKNAME_MAX_BYTES
    assert chat.decode_message(chat.encode_message(alice.message("hi", NOW))) is not None


def test_private_message_opens_only_for_its_recipient(alice, bob):
    carol = Identity("Carol")
    message = alice.message("the key is under the mat", NOW, to=bob.announce(NOW))
    sealed = chat.seal(chat.encode_message(message), bob.chat_key)
    assert b"under the mat" not in sealed
    assert bob.open(sealed) == message
    assert carol.open(sealed) is None
    assert alice.open(sealed) is None


def test_changed_sealed_message_does_not_open(alice, bob):
    sealed = bytearray(chat.seal(chat.encode_message(alice.message("hi", NOW, to=bob.announce(NOW))), bob.chat_key))
    sealed[-1] ^= 1
    assert bob.open(bytes(sealed)) is None
    assert bob.open(b"too short") is None


def test_message_to_someone_else_resealed_to_me_is_refused(alice, bob):
    """Carol cannot take a message Alice wrote to Carol and make Bob think it was to him."""
    carol = Identity("Carol")
    to_carol = alice.message("secret", NOW, to=carol.announce(NOW))
    assert bob.open(chat.seal(chat.encode_message(to_carol), bob.chat_key)) is None


def test_largest_messages_match_the_stated_limits(alice, bob):
    alice.nickname = "x" * 40
    message = alice.message("é" * (chat.TEXT_MAX_BYTES // 2), NOW, to=bob.announce(NOW))
    assert len(chat.encode_message(message)) == chat.MESSAGE_MAX_BYTES
    assert len(chat.seal(chat.encode_message(message), bob.chat_key)) == chat.SEALED_MAX_BYTES == 545
