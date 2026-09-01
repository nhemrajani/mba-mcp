"""CRUD over the SQLite campaign state.

Deliberately dumb: read, write, return dicts. Ranking lives in
:mod:`connections`, date maths in :mod:`timeline`, and all language work
belongs to the calling assistant.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any, Iterable, Sequence

from .db import now_iso, today_iso
from .models import APPLICATION_STATUSES


class NotFound(LookupError):
    """A record the caller referenced by id does not exist."""


def _dicts(rows: Iterable[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


# --------------------------------------------------------------------------
# Targets
# --------------------------------------------------------------------------


def upsert_target(
    conn: sqlite3.Connection,
    name: str,
    ats_kind: str | None = None,
    ats_slug: str | None = None,
    ats_url: str | None = None,
    priority: int = 2,
) -> dict:
    """Add a target company, or refresh the one already stored under that name."""
    existing = get_target_by_name(conn, name)
    with conn:
        if existing:
            conn.execute(
                """
                UPDATE targets
                   SET ats_kind = COALESCE(?, ats_kind),
                       ats_slug = COALESCE(?, ats_slug),
                       ats_url  = COALESCE(?, ats_url),
                       priority = ?
                 WHERE id = ?
                """,
                (ats_kind, ats_slug, ats_url, priority, existing["id"]),
            )
            target_id = existing["id"]
        else:
            cursor = conn.execute(
                """
                INSERT INTO targets (name, ats_kind, ats_slug, ats_url, priority, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name.strip(), ats_kind, ats_slug, ats_url, priority, now_iso()),
            )
            target_id = int(cursor.lastrowid)
    return get_target(conn, target_id)


def get_target(conn: sqlite3.Connection, target_id: int) -> dict:
    row = conn.execute("SELECT * FROM targets WHERE id = ?", (target_id,)).fetchone()
    if row is None:
        raise NotFound(f"No target with id {target_id}")
    return dict(row)


def get_target_by_name(conn: sqlite3.Connection, name: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM targets WHERE name = ? COLLATE NOCASE", (name.strip(),)
    ).fetchone()
    return dict(row) if row else None


def list_targets(conn: sqlite3.Connection) -> list[dict]:
    return _dicts(
        conn.execute(
            "SELECT * FROM targets ORDER BY priority ASC, name COLLATE NOCASE ASC"
        )
    )


# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------


def add_application(
    conn: sqlite3.Connection,
    company: str,
    role: str,
    url: str | None = None,
    status: str = "interested",
    deadline: str | None = None,
    notes: str | None = None,
) -> dict:
    status = _check_status(status)
    stamp = now_iso()
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO applications
                (company, role, url, status, deadline, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (company.strip(), role.strip(), url, status, deadline, notes, stamp, stamp),
        )
    return get_application(conn, int(cursor.lastrowid))


def update_application(
    conn: sqlite3.Connection,
    application_id: int,
    status: str | None = None,
    deadline: str | None = None,
    notes: str | None = None,
    role: str | None = None,
    url: str | None = None,
) -> dict:
    current = get_application(conn, application_id)
    if status is not None:
        status = _check_status(status)
    with conn:
        conn.execute(
            """
            UPDATE applications
               SET status = ?, deadline = ?, notes = ?, role = ?, url = ?, updated_at = ?
             WHERE id = ?
            """,
            (
                status or current["status"],
                deadline if deadline is not None else current["deadline"],
                notes if notes is not None else current["notes"],
                role or current["role"],
                url if url is not None else current["url"],
                now_iso(),
                application_id,
            ),
        )
    return get_application(conn, application_id)


def get_application(conn: sqlite3.Connection, application_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM applications WHERE id = ?", (application_id,)
    ).fetchone()
    if row is None:
        raise NotFound(f"No application with id {application_id}")
    return _with_deadline_countdown(dict(row))


def list_applications(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    query = "SELECT * FROM applications"
    params: Sequence[Any] = ()
    if status:
        query += " WHERE status = ?"
        params = (_check_status(status),)
    # Live deadlines first, then everything undated, newest last touched first.
    query += " ORDER BY (deadline IS NULL) ASC, deadline ASC, updated_at DESC"
    return [_with_deadline_countdown(dict(row)) for row in conn.execute(query, params)]


def _check_status(status: str) -> str:
    normalised = status.strip().lower()
    if normalised not in APPLICATION_STATUSES:
        raise ValueError(
            f"Unknown status '{status}'. Use one of: {', '.join(APPLICATION_STATUSES)}"
        )
    return normalised


def _with_deadline_countdown(row: dict, today: date | None = None) -> dict:
    row["days_until_deadline"] = None
    if row.get("deadline"):
        try:
            row["days_until_deadline"] = (
                date.fromisoformat(row["deadline"]) - (today or date.today())
            ).days
        except ValueError:
            pass
    return row


# --------------------------------------------------------------------------
# Contacts
# --------------------------------------------------------------------------


def upsert_contacts(conn: sqlite3.Connection, contacts: Iterable[dict]) -> dict:
    """Import contacts idempotently, keyed on (name, company)."""
    inserted = updated = skipped = 0
    with conn:
        for contact in contacts:
            name = (contact.get("full_name") or "").strip()
            if not name:
                skipped += 1
                continue
            company = contact.get("company")
            existing = conn.execute(
                """
                SELECT id FROM contacts
                 WHERE full_name = ? COLLATE NOCASE
                   AND IFNULL(company, '') = IFNULL(?, '') COLLATE NOCASE
                """,
                (name, company),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE contacts
                       SET title        = COALESCE(?, title),
                           email        = COALESCE(?, email),
                           linkedin_url = COALESCE(?, linkedin_url),
                           school       = COALESCE(?, school),
                           grad_year    = COALESCE(?, grad_year),
                           connected_on = COALESCE(?, connected_on)
                     WHERE id = ?
                    """,
                    (
                        contact.get("title"),
                        contact.get("email"),
                        contact.get("linkedin_url"),
                        contact.get("school"),
                        contact.get("grad_year"),
                        contact.get("connected_on"),
                        existing["id"],
                    ),
                )
                updated += 1
            else:
                conn.execute(
                    """
                    INSERT INTO contacts
                        (full_name, company, title, email, linkedin_url, school,
                         grad_year, connected_on, source, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        company,
                        contact.get("title"),
                        contact.get("email"),
                        contact.get("linkedin_url"),
                        contact.get("school"),
                        contact.get("grad_year"),
                        contact.get("connected_on"),
                        contact.get("source", "linkedin_csv"),
                        now_iso(),
                    ),
                )
                inserted += 1
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


def set_contact_email(conn: sqlite3.Connection, contact_id: int, email: str) -> dict:
    """Record a confirmed address for a contact."""
    get_contact(conn, contact_id)
    with conn:
        conn.execute("UPDATE contacts SET email = ? WHERE id = ?", (email.strip(), contact_id))
    return get_contact(conn, contact_id)


def get_contact(conn: sqlite3.Connection, contact_id: int) -> dict:
    row = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    if row is None:
        raise NotFound(f"No contact with id {contact_id}")
    return dict(row)


def list_contacts(conn: sqlite3.Connection, limit: int | None = None) -> list[dict]:
    query = "SELECT * FROM contacts ORDER BY full_name COLLATE NOCASE"
    if limit:
        query += f" LIMIT {int(limit)}"
    return _dicts(conn.execute(query))


def count_contacts(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0])


def interaction_summary(conn: sqlite3.Connection) -> dict[int, dict]:
    rows = conn.execute(
        """
        SELECT contact_id, COUNT(*) AS count, MAX(occurred_at) AS last_occurred_at
          FROM interactions
         GROUP BY contact_id
        """
    )
    return {row["contact_id"]: dict(row) for row in rows}


# --------------------------------------------------------------------------
# Interactions & follow-ups
# --------------------------------------------------------------------------


def add_interaction(
    conn: sqlite3.Connection,
    contact_id: int,
    kind: str,
    notes: str | None = None,
    next_followup: str | None = None,
    occurred_at: str | None = None,
) -> dict:
    get_contact(conn, contact_id)  # raises NotFound
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO interactions
                (contact_id, kind, notes, occurred_at, next_followup, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                contact_id,
                kind.strip().lower(),
                notes,
                occurred_at or today_iso(),
                next_followup,
                now_iso(),
            ),
        )
        interaction_id = int(cursor.lastrowid)
    row = conn.execute(
        "SELECT * FROM interactions WHERE id = ?", (interaction_id,)
    ).fetchone()
    return dict(row)


def due_followups(conn: sqlite3.Connection, due_on_or_before: str) -> list[dict]:
    """Contacts whose *latest* interaction set a follow-up date now reached.

    Only the latest interaction counts — a follow-up superseded by a more
    recent conversation is not still owed.
    """
    rows = conn.execute(
        """
        WITH latest AS (
            SELECT i.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY i.contact_id
                       ORDER BY i.occurred_at DESC, i.id DESC
                   ) AS rank
              FROM interactions i
        )
        SELECT latest.id           AS interaction_id,
               latest.kind         AS last_kind,
               latest.notes        AS last_notes,
               latest.occurred_at  AS last_occurred_at,
               latest.next_followup AS due_on,
               c.*
          FROM latest
          JOIN contacts c ON c.id = latest.contact_id
         WHERE latest.rank = 1
           AND latest.next_followup IS NOT NULL
           AND latest.next_followup <= ?
         ORDER BY latest.next_followup ASC
        """,
        (due_on_or_before,),
    )
    return _dicts(rows)


# --------------------------------------------------------------------------
# Outreach drafts
# --------------------------------------------------------------------------


def save_draft(
    conn: sqlite3.Connection,
    contact_id: int,
    subject: str,
    body: str,
    to_email: str | None = None,
) -> dict:
    contact = get_contact(conn, contact_id)
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO outreach_drafts
                (contact_id, to_email, subject, body, status, created_at)
            VALUES (?, ?, ?, ?, 'draft', ?)
            """,
            (contact_id, to_email or contact.get("email"), subject, body, now_iso()),
        )
    return get_draft(conn, int(cursor.lastrowid))


def get_draft(conn: sqlite3.Connection, draft_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM outreach_drafts WHERE id = ?", (draft_id,)
    ).fetchone()
    if row is None:
        raise NotFound(f"No outreach draft with id {draft_id}")
    return dict(row)


def list_drafts(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    query = "SELECT * FROM outreach_drafts"
    params: Sequence[Any] = ()
    if status:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY created_at DESC"
    return _dicts(conn.execute(query, params))


def mark_draft_sent(conn: sqlite3.Connection, draft_id: int, message_id: str) -> dict:
    with conn:
        conn.execute(
            """
            UPDATE outreach_drafts
               SET status = 'sent', sent_at = ?, gmail_message_id = ?
             WHERE id = ?
            """,
            (now_iso(), message_id, draft_id),
        )
    return get_draft(conn, draft_id)


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------

PROFILE_FIELDS = (
    "full_name",
    "school",
    "school_linkedin",
    "graduation_year",
    "track",
    "target_locations",
    "email",
)


def get_profile(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
    return dict(row) if row else {field: None for field in PROFILE_FIELDS}


def set_profile(conn: sqlite3.Connection, **fields: Any) -> dict:
    """Upsert the single profile row, leaving unspecified fields alone."""
    current = get_profile(conn)
    merged = {
        field: fields.get(field) if fields.get(field) is not None else current.get(field)
        for field in PROFILE_FIELDS
    }
    columns = ", ".join(PROFILE_FIELDS)
    placeholders = ", ".join("?" for _ in PROFILE_FIELDS)
    with conn:
        conn.execute(
            f"INSERT OR REPLACE INTO profile (id, {columns}, updated_at) "
            f"VALUES (1, {placeholders}, ?)",
            (*[merged[field] for field in PROFILE_FIELDS], now_iso()),
        )
    return get_profile(conn)
