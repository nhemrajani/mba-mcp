"""SQLite state: connection handling and versioned migrations.

The whole campaign lives in one file under the configured data dir. Migrations
are a plain ordered list applied against ``PRAGMA user_version`` — adding a
migration means appending to :data:`MIGRATIONS`, never editing an old entry.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

MIGRATIONS: list[str] = [
    # 1 — targets, applications, contacts, interactions, outreach drafts.
    """
    CREATE TABLE targets (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT    NOT NULL,
        ats_kind    TEXT,
        ats_slug    TEXT,
        ats_url     TEXT,
        priority    INTEGER NOT NULL DEFAULT 2,
        created_at  TEXT    NOT NULL
    );
    CREATE UNIQUE INDEX idx_targets_name ON targets (name COLLATE NOCASE);

    CREATE TABLE applications (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        company     TEXT    NOT NULL,
        role        TEXT    NOT NULL,
        url         TEXT,
        status      TEXT    NOT NULL DEFAULT 'interested',
        deadline    TEXT,
        notes       TEXT,
        created_at  TEXT    NOT NULL,
        updated_at  TEXT    NOT NULL
    );
    CREATE INDEX idx_applications_status ON applications (status);

    CREATE TABLE contacts (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name     TEXT NOT NULL,
        company       TEXT,
        title         TEXT,
        email         TEXT,
        linkedin_url  TEXT,
        school        TEXT,
        connected_on  TEXT,
        source        TEXT NOT NULL DEFAULT 'linkedin_csv',
        created_at    TEXT NOT NULL
    );
    CREATE UNIQUE INDEX idx_contacts_identity
        ON contacts (full_name COLLATE NOCASE, IFNULL(company, '') COLLATE NOCASE);
    CREATE INDEX idx_contacts_company ON contacts (company COLLATE NOCASE);

    CREATE TABLE interactions (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        contact_id     INTEGER NOT NULL REFERENCES contacts (id) ON DELETE CASCADE,
        kind           TEXT    NOT NULL,
        notes          TEXT,
        occurred_at    TEXT    NOT NULL,
        next_followup  TEXT,
        created_at     TEXT    NOT NULL
    );
    CREATE INDEX idx_interactions_contact ON interactions (contact_id);
    CREATE INDEX idx_interactions_followup ON interactions (next_followup);

    CREATE TABLE outreach_drafts (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        contact_id        INTEGER NOT NULL REFERENCES contacts (id) ON DELETE CASCADE,
        to_email          TEXT,
        subject           TEXT    NOT NULL,
        body              TEXT    NOT NULL,
        status            TEXT    NOT NULL DEFAULT 'draft',
        created_at        TEXT    NOT NULL,
        sent_at           TEXT,
        gmail_message_id  TEXT
    );
    CREATE INDEX idx_drafts_contact ON outreach_drafts (contact_id);
    """,
    # 2 — the user's own profile, and alumni fields on contacts.
    """
    CREATE TABLE profile (
        id                INTEGER PRIMARY KEY CHECK (id = 1),
        full_name         TEXT,
        school            TEXT,
        school_linkedin   TEXT,
        graduation_year   INTEGER,
        track             TEXT,
        target_locations  TEXT,
        email             TEXT,
        updated_at        TEXT NOT NULL
    );

    ALTER TABLE contacts ADD COLUMN grad_year INTEGER;
    ALTER TABLE contacts ADD COLUMN notes TEXT;
    """,
]

SCHEMA_VERSION = len(MIGRATIONS)


def now_iso() -> str:
    """UTC timestamp, second precision, for stored record metadata."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today_iso() -> str:
    """Local calendar date — deadlines and follow-ups are day-granular."""
    return date.today().isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the campaign database, migrated to current."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Apply any migrations the database has not seen. Returns the new version."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema v{version} is newer than this build (v{SCHEMA_VERSION}). "
            "Upgrade mba-mcp."
        )
    for index in range(version, SCHEMA_VERSION):
        with conn:
            conn.executescript(MIGRATIONS[index])
            conn.execute(f"PRAGMA user_version = {index + 1}")
    return SCHEMA_VERSION


@contextmanager
def session(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None
