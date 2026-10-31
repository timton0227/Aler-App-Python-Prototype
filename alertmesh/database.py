"""What one laptop keeps on disk: warnings, reports (SOS, "safe" and hazards) and chats.

Plays the part of the iPhone app's JSON files in Application Support (official.json,
community.json, public-messages.json), but in one SQLite file next to the profile.
SQLite comes with Python, so nothing new needs installing.

Warnings and reports are kept in their signed wire form (as the store encodes them). On
start each store checks every signature again, so a file someone edited by hand cannot
slip in a forged warning. Chat messages are kept field by field: Nearby messages from
iPhones are signed as whole Bluetooth packets, which are not kept.

The stores keep working in memory as before. They hand the database their whole
contents after each change; the database writes only the rows that changed. They read
it back once when they are made.

This is free and unencumbered software released into the public domain.
"""
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

DATABASE_FILE = "alertmesh.db"
SCHEMA_VERSION = 1

log = logging.getLogger(__name__)

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
CREATE TABLE IF NOT EXISTS meta (
    name TEXT PRIMARY KEY,
    value BLOB NOT NULL
);
"""

# Tables the stores hand over whole, with their key column.
_SYNCED = {"alerts": "alert_id", "cancellations": "alert_id", "reports": "report_key"}


class NewerDatabaseError(RuntimeError):
    """The file was made by a newer Alert Mesh, which may keep things this one cannot read."""


class Database:
    """One SQLite file. Safe to call from the radio's thread and the page's at once.

    Rows come back in the order they were written, which is the order the stores
    keep (and evict) them in. After `close()` every call does nothing, so a radio
    thread still finishing as the app stops cannot fail."""

    def __init__(self, path: Path | str):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        if not path.exists():
            # Made readable by its owner only before anything is written: it holds what
            # people said in private chats. (SQLite gives its journal the same mode.)
            os.close(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600))
        self._lock = threading.Lock()
        self._closed = False
        self._synced: dict[str, dict[bytes, tuple]] = {}  # table -> key -> row, as on disk
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        try:
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise NewerDatabaseError(f"{path} was made by a newer Alert Mesh (version {version})")
            self._db.executescript(_SCHEMA)
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except BaseException:
            self._db.close()
            raise

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._db.close()

    # --- Whose chats ---

    def claim(self, owner_key: bytes) -> None:
        """Chats belong to one identity. If the file was another identity's (the profile
        was lost and a new one made), its chats are dropped: they would show that
        person's messages as this one's. Warnings and reports belong to nobody, so stay."""
        with self._lock:
            if self._closed:
                return
            with self._db:
                self._db.execute("BEGIN")
                row = self._db.execute("SELECT value FROM meta WHERE name = 'owner'").fetchone()
                if row is not None and row[0] != owner_key:
                    log.warning("%s belonged to another identity: dropping its chats", self.path)
                    self._db.execute("DELETE FROM chat_messages")
                    self._db.execute("DELETE FROM conversations")
                self._db.execute("INSERT OR REPLACE INTO meta VALUES ('owner', ?)", (owner_key,))

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
        """Make what is kept match the store's whole contents."""
        self._sync({"alerts": alerts, "cancellations": [(a, p, r, int(o)) for a, p, r, o in cancellations]})

    # --- Reports ---

    def reports(self) -> list[tuple[bytes, bytes]]:
        """(author key + report ID, payload) for every report kept."""
        return self._rows("SELECT report_key, payload FROM reports ORDER BY rowid")

    def save_reports(self, rows: list[tuple[bytes, bytes]]) -> None:
        self._sync({"reports": rows})

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
        with self._lock:
            if self._closed:
                return
            with self._db:
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
            if not self._closed:
                self._set_unread(conversation, unread)

    # --- Internals ---

    def _set_unread(self, conversation: str, unread: int) -> None:
        self._db.execute("INSERT INTO conversations VALUES (?, ?) "
                         "ON CONFLICT (conversation) DO UPDATE SET unread = excluded.unread", (conversation, unread))

    def _rows(self, sql: str) -> list[tuple]:
        with self._lock:
            return [] if self._closed else self._db.execute(sql).fetchall()

    def _sync(self, tables: dict[str, list[tuple]]) -> None:
        """Write only what differs from the last time: rows that are new or changed go to
        the end (as the stores' dicts put them), rows that are gone are deleted."""
        with self._lock:
            if self._closed:
                return
            written = {}
            with self._db:
                self._db.execute("BEGIN")
                for table, rows in tables.items():
                    key = _SYNCED[table]
                    on_disk = self._synced.get(table)
                    if on_disk is None:
                        on_disk = {row[0]: row for row in self._db.execute(f"SELECT * FROM {table}")}
                    wanted = {row[0]: row for row in rows}
                    gone = [(k,) for k in on_disk if k not in wanted]
                    changed = [row for k, row in wanted.items() if on_disk.get(k) != row]
                    self._db.executemany(f"DELETE FROM {table} WHERE {key} = ?", gone)
                    marks = ", ".join("?" * len(rows[0])) if rows else ""
                    if changed:
                        self._db.executemany(f"INSERT OR REPLACE INTO {table} VALUES ({marks})", changed)
                    written[table] = wanted
            self._synced.update(written)  # only once committed: a failed write is tried again in full


def open_database(folder: Path) -> Database | None:
    """The phone app's database, opened so that a bad file never stops the app.

    A damaged file (power lost during a write) is moved aside and a new one made. A file
    from a newer Alert Mesh is left alone, and nothing is kept on disk this run."""
    path = Path(folder) / DATABASE_FILE
    try:
        return Database(path)
    except NewerDatabaseError as error:
        log.warning("%s; keeping nothing on disk this run", error)
        return None
    except sqlite3.DatabaseError as error:
        aside = path.with_name(f"{path.name}.broken-{int(time.time())}")
        log.warning("%s could not be read (%s); moved to %s and starting a new one", path, error, aside.name)
        path.replace(aside)
        return Database(path)
