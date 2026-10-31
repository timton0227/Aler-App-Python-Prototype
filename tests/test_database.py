"""Tests for alertmesh.database: warnings, reports and chats kept over a restart."""
import os
import sqlite3

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from alertmesh import database, wire
from alertmesh.alert_store import AlertStore, IngestResult
from alertmesh.chat import Identity
from alertmesh.database import Database
from alertmesh.node import NEARBY, ChatStore
from alertmesh.phone import Phone
from alertmesh.report_store import ReportStore
from alertmesh.reports import ReportKind
from test_alert_store import BASE_MS, HOUR_MS, PUBLISHER, Clock, make_alert, make_cancellation
from test_report_store import make_report

KEY = PUBLISHER.public_key().public_bytes_raw()


def open_db(tmp_path) -> Database:
    return Database(tmp_path / database.DATABASE_FILE)


# --- Warnings


def test_warnings_and_cancellations_are_kept_over_a_restart(tmp_path):
    clock = Clock()
    store = AlertStore(KEY, clock, open_db(tmp_path))
    kept, withdrawn, orphan_id = make_alert(), make_alert(), os.urandom(16)
    assert store.ingest(kept) is IngestResult.ACCEPTED
    store.ingest(withdrawn)
    store.ingest(make_cancellation(withdrawn.alert_id, BASE_MS + 1000))
    store.ingest(make_cancellation(orphan_id, BASE_MS + 1000))

    again = AlertStore(KEY, clock, open_db(tmp_path))
    assert again.live_alerts() == [kept]
    assert sorted(again.sync_candidates()) == sorted(store.sync_candidates())
    # The cancellations still do their job: neither warning comes back.
    assert again.ingest(withdrawn) is IngestResult.REJECTED
    assert again.ingest(make_alert(alert_id=orphan_id)) is IngestResult.REJECTED


def test_expired_warnings_are_not_read_back(tmp_path):
    clock = Clock()
    AlertStore(KEY, clock, open_db(tmp_path)).ingest(make_alert(lifetime_ms=HOUR_MS))
    clock.now_ms += 2 * HOUR_MS
    assert AlertStore(KEY, clock, open_db(tmp_path)).live_alerts() == []


def test_warning_edited_on_disk_is_not_read_back(tmp_path):
    """Every signature is checked again, so the file cannot slip in a forged warning."""
    clock = Clock()
    AlertStore(KEY, clock, open_db(tmp_path)).ingest(make_alert())
    forged = make_alert(key=Ed25519PrivateKey.generate())
    with sqlite3.connect(tmp_path / database.DATABASE_FILE) as raw:
        raw.execute("INSERT INTO alerts VALUES (?, ?)", (forged.alert_id, wire.encode(forged)))
    assert len(AlertStore(KEY, clock, open_db(tmp_path)).live_alerts()) == 1


def test_wipe_empties_the_file_too(tmp_path):
    clock = Clock()
    store = AlertStore(KEY, clock, open_db(tmp_path))
    store.ingest(make_alert())
    store.wipe()
    assert AlertStore(KEY, clock, open_db(tmp_path)).live_alerts() == []


# --- Reports


def test_reports_and_calls_for_help_are_kept_over_a_restart(tmp_path):
    clock = Clock()
    store = ReportStore(clock, open_db(tmp_path))
    sos, hazard = make_report(ReportKind.SOS), make_report(ReportKind.HAZARD)
    assert store.ingest(sos) is IngestResult.ACCEPTED
    store.ingest(hazard)

    again = ReportStore(clock, open_db(tmp_path))
    assert again.live_reports() == [sos, hazard]
    assert again.ingest(sos) is IngestResult.DUPLICATE


def test_safe_answer_replaces_the_call_for_help_on_disk(tmp_path):
    clock = Clock()
    store = ReportStore(clock, open_db(tmp_path))
    sos = make_report(ReportKind.SOS)
    store.ingest(sos)
    safe = make_report(ReportKind.SAFE, report_id=sos.report_id, created_at=BASE_MS + 1000)
    assert store.ingest(safe) is IngestResult.ACCEPTED
    assert ReportStore(clock, open_db(tmp_path)).live_reports() == [safe]


# --- Chats


def test_chats_and_unread_counts_are_kept_over_a_restart(tmp_path):
    me, them = Identity("Me"), Identity("Them")
    store = ChatStore(open_db(tmp_path))
    nearby = them.message("Road's cut at the bridge", BASE_MS)
    private = them.message("Are you OK?", BASE_MS + 1, to=me.announce(BASE_MS))
    reply = me.message("Yes, at the school", BASE_MS + 2, to=them.announce(BASE_MS))
    store.add(NEARBY, nearby, False, BASE_MS)
    store.add(them.signing_key.hex(), private, False, BASE_MS + 1)
    store.add(them.signing_key.hex(), reply, True, BASE_MS + 2)
    store.mark_read(NEARBY)

    again = ChatStore(open_db(tmp_path))
    assert [e.message for e in again.conversations[NEARBY].entries] == [nearby]
    assert [(e.message, e.outgoing) for e in again.conversations[them.signing_key.hex()].entries] == [
        (private, False), (reply, True)]
    assert again.conversations[NEARBY].unread == 0 and again.unread == 1
    assert again.add(NEARBY, nearby, False, BASE_MS) is False  # still shown once


def test_message_pushed_out_of_a_full_conversation_is_dropped_on_disk(tmp_path, monkeypatch):
    from alertmesh import node

    monkeypatch.setattr(node, "MAX_MESSAGES_PER_CONVERSATION", 2)
    them = Identity("Them")
    store = ChatStore(open_db(tmp_path))
    messages = [them.message(f"update {i}", BASE_MS + i) for i in range(3)]
    for m in messages:
        store.add(NEARBY, m, False, BASE_MS)
    assert [e.message for e in ChatStore(open_db(tmp_path)).conversations[NEARBY].entries] == messages[1:]


# --- The phone app


def test_phone_app_keeps_its_chats_in_its_own_folder(tmp_path):
    first = Phone(tmp_path, Clock())
    message = Identity("Them").message("Water's rising", BASE_MS)
    first.node.chats.add(NEARBY, message, False, BASE_MS)
    assert [e.message for e in Phone(tmp_path, Clock()).node.chats.conversations[NEARBY].entries] == [message]
    assert (tmp_path / database.DATABASE_FILE).exists()


# --- The file


def test_only_the_owner_can_read_the_file(tmp_path):
    open_db(tmp_path)
    if os.name != "nt":
        assert (tmp_path / database.DATABASE_FILE).stat().st_mode & 0o077 == 0


def test_file_from_a_newer_version_is_refused(tmp_path):
    with sqlite3.connect(tmp_path / database.DATABASE_FILE) as raw:
        raw.execute(f"PRAGMA user_version = {database.SCHEMA_VERSION + 1}")
    try:
        open_db(tmp_path)
    except RuntimeError as error:
        assert "newer" in str(error)
    else:
        raise AssertionError("a newer file was opened")
