"""What one laptop keeps on disk: warnings, reports (SOS, "safe" and hazards) and chats.

Plays the part of the iPhone app's JSON files in Application Support (official.json,
community.json, public-messages.json), but in one SQLite file next to the profile.
SQLite comes with Python, so nothing new needs installing.

Warnings and reports are kept as their signed bytes, exactly as they arrived. On start
each store checks every signature again, so a file someone edited by hand cannot slip
in a forged warning. Chat messages are kept field by field: Nearby messages from
iPhones are signed as whole Bluetooth packets, which are not kept.

The stores keep working in memory as before. They tell the database after each change,
and read it back once when they are made.

This is free and unencumbered software released into the public domain.
"""
import sqlite3
import sys
import threading
from pathlib import Path

DATABASE_FILE = "alertmesh.db"
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    alert_id BLOB PRIMARY KEY,
    payload BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS cancellations (
    alert_id BLOB PRIMARY KEY,
    payload BLOB NOT NULL,
    retain_until INTEGER NOT NULL,
    is_orphan INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    report_key BLOB PRIMARY KEY,
    payload BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
    message_id BLOB PRIMARY KEY,
    conversation TEXT NOT NULL,
    sender_key BLOB NOT NULL,
    sender_nickname TEXT NOT NULL,
    recipient_key BLOB NOT NULL,
    text TEXT NOT NULL,
    sent_at INTEGER NOT NULL,
    signature BLOB NOT NULL,
    outgoing INTEGER NOT NULL,
    received_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    conversation TEXT PRIMARY KEY,
    unread INTEGER NOT NULL
);
"""


class Database:
    """One SQLite file. Safe to call from the radio's thread and the page's at once.

    Rows come back in the order they were written, which is the order the stores
    keep (and evict) them in."""

    def __init__(self, path: Path | str):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        if sys.platform != "win32":
            path.chmod(0o600)  # what people said in private chats
        with self._lock:
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(f"{path} was made by a newer Alert Mesh (version {version})")
            self._db.executescript(_SCHEMA)
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # --- Warnings ---

    def alerts(self) -> list[tuple[bytes, bytes]]:
        """(alert_id, payload) for every warning kept."""
        return self._rows("SELECT alert_id, payload FROM alerts ORDER BY rowid")

    def cancellations(self) -> list[tuple[bytes, bytes, int, bool]]:
        """(alert_id, payload, retain_until, is_orphan) for every cancellation kept."""
        rows = self._rows("SELECT alert_id, payload, retain_until, is_orphan FROM cancellations ORDER BY rowid")
        return [(a, p, r, bool(o)) for a, p, r, o in rows]

    def save_alerts(self, alerts: list[tuple[bytes, bytes]],
                    cancellations: list[tuple[bytes, bytes, int, bool]]) -> None:
        """Replace what is kept with the store's whole contents (at most a few hundred rows)."""
        self._replace([
            ("alerts", "INSERT INTO alerts VALUES (?, ?)", alerts),
            ("cancellations", "INSERT INTO cancellations VALUES (?, ?, ?, ?)",
             [(a, p, r, int(o)) for a, p, r, o in cancellations]),
        ])

    # --- Reports ---

    def reports(self) -> list[tuple[bytes, bytes]]:
        """(author key + report ID, payload) for every report kept."""
        return self._rows("SELECT report_key, payload FROM reports ORDER BY rowid")

    def save_reports(self, rows: list[tuple[bytes, bytes]]) -> None:
        self._replace([("reports", "INSERT INTO reports VALUES (?, ?)", rows)])

    # --- Chats ---

    def chat_messages(self) -> list[tuple]:
        """(conversation, message_id, sender_key, sender_nickname, recipient_key, text,
        sent_at, signature, outgoing, received_at), oldest received first."""
        rows = self._rows("SELECT conversation, message_id, sender_key, sender_nickname, recipient_key, text, "
                          "sent_at, signature, outgoing, received_at FROM chat_messages ORDER BY rowid")
        return [(*row[:8], bool(row[8]), row[9]) for row in rows]

    def unread(self) -> dict[str, int]:
        return dict(self._rows("SELECT conversation, unread FROM conversations"))

    def add_chat_message(self, conversation: str, message, outgoing: bool, received_at: int,
                         unread: int, dropped_id: bytes | None = None) -> None:
        """Keep one new message, its conversation's unread count, and drop the message the
        conversation pushed out (if any), all at once."""
        with self._lock, self._db:
            self._db.execute("BEGIN")
            self._db.execute(
                "INSERT OR IGNORE INTO chat_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (message.message_id, conversation, message.sender_key, message.sender_nickname,
                 message.recipient_key, message.text, message.sent_at, message.signature, int(outgoing),
                 received_at))
            if dropped_id is not None:
                self._db.execute("DELETE FROM chat_messages WHERE message_id = ?", (dropped_id,))
            self._set_unread(conversation, unread)

    def set_unread(self, conversation: str, unread: int) -> None:
        with self._lock:
            self._set_unread(conversation, unread)

    # --- Internals ---

    def _set_unread(self, conversation: str, unread: int) -> None:
        self._db.execute("INSERT INTO conversations VALUES (?, ?) "
                         "ON CONFLICT (conversation) DO UPDATE SET unread = excluded.unread", (conversation, unread))

    def _rows(self, sql: str) -> list[tuple]:
        with self._lock:
            return self._db.execute(sql).fetchall()

    def _replace(self, tables: list[tuple[str, str, list]]) -> None:
        with self._lock, self._db:
            self._db.execute("BEGIN")
            for table, insert, rows in tables:
                self._db.execute(f"DELETE FROM {table}")
                self._db.executemany(insert, rows)
