"""Schema, migration and store round-trip tests."""

import sqlite3

import pytest

from mba_mcp import db, store


def test_connect_creates_and_migrates(db_path):
    with db.session(db_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert db_path.exists()
    assert version == db.SCHEMA_VERSION == len(db.MIGRATIONS)
    assert {"targets", "applications", "contacts", "interactions", "outreach_drafts"} <= tables


def test_migrations_are_idempotent(db_path):
    with db.session(db_path) as conn:
        store.upsert_target(conn, "Bain")
    with db.session(db_path) as conn:  # reopening re-runs migrate()
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert len(store.list_targets(conn)) == 1


def test_future_schema_is_refused(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="newer than this build"):
        db.connect(db_path)


def test_target_upsert_is_keyed_on_name(db_path):
    with db.session(db_path) as conn:
        first = store.upsert_target(conn, "Bain & Company", priority=2)
        again = store.upsert_target(
            conn, "bain & company", ats_kind="greenhouse", ats_slug="bain", priority=1
        )
        assert again["id"] == first["id"]
        assert again["ats_slug"] == "bain"
        assert again["priority"] == 1
        assert len(store.list_targets(conn)) == 1
        assert store.get_target_by_name(conn, "BAIN & COMPANY") is not None


def test_targets_list_orders_by_priority(db_path):
    with db.session(db_path) as conn:
        store.upsert_target(conn, "Zeta", priority=3)
        store.upsert_target(conn, "Alpha", priority=1)
        store.upsert_target(conn, "Mid", priority=1)
        assert [t["name"] for t in store.list_targets(conn)] == ["Alpha", "Mid", "Zeta"]


def test_application_lifecycle(db_path):
    with db.session(db_path) as conn:
        app = store.add_application(
            conn, "Bain", "Summer Associate", url="https://x", deadline="2027-01-10"
        )
        assert app["status"] == "interested"
        assert app["days_until_deadline"] is not None

        moved = store.update_application(conn, app["id"], status="applied", notes="referred by Priya")
        assert moved["status"] == "applied"
        assert moved["notes"] == "referred by Priya"
        assert moved["role"] == "Summer Associate"  # untouched fields survive

        assert len(store.list_applications(conn, status="applied")) == 1
        assert store.list_applications(conn, status="offer") == []

        with pytest.raises(ValueError, match="Unknown status"):
            store.update_application(conn, app["id"], status="ghosted")
        with pytest.raises(store.NotFound):
            store.get_application(conn, 9999)


def test_applications_sort_soonest_deadline_first(db_path):
    with db.session(db_path) as conn:
        store.add_application(conn, "C", "role", deadline=None)
        store.add_application(conn, "B", "role", deadline="2027-03-01")
        store.add_application(conn, "A", "role", deadline="2027-01-01")
        assert [row["company"] for row in store.list_applications(conn)] == ["A", "B", "C"]


def test_contact_import_is_idempotent(db_path):
    rows = [
        {"full_name": "Priya Raman", "company": "Bain", "title": "Consultant"},
        {"full_name": "", "company": "Ghost"},
    ]
    with db.session(db_path) as conn:
        first = store.upsert_contacts(conn, rows)
        assert first == {"inserted": 1, "updated": 0, "skipped": 1}

        second = store.upsert_contacts(
            conn, [{"full_name": "Priya Raman", "company": "Bain", "email": "p@example.com"}]
        )
        assert second["updated"] == 1
        assert store.count_contacts(conn) == 1

        contact = store.list_contacts(conn)[0]
        assert contact["email"] == "p@example.com"
        assert contact["title"] == "Consultant"  # existing value not blanked


def test_followups_use_only_the_latest_interaction(db_path):
    with db.session(db_path) as conn:
        store.upsert_contacts(conn, [{"full_name": "Priya Raman", "company": "Bain"}])
        contact_id = store.list_contacts(conn)[0]["id"]

        store.add_interaction(
            conn, contact_id, "coffee_chat", notes="great chat",
            occurred_at="2026-09-01", next_followup="2026-09-15",
        )
        due = store.due_followups(conn, "2026-09-20")
        assert [row["due_on"] for row in due] == ["2026-09-15"]
        assert due[0]["last_kind"] == "coffee_chat"

        # A later conversation supersedes the earlier follow-up.
        store.add_interaction(
            conn, contact_id, "call", occurred_at="2026-09-16", next_followup="2026-10-30"
        )
        assert store.due_followups(conn, "2026-09-20") == []
        assert len(store.due_followups(conn, "2026-11-01")) == 1

        summary = store.interaction_summary(conn)
        assert summary[contact_id]["count"] == 2

        with pytest.raises(store.NotFound):
            store.add_interaction(conn, 4242, "call")


def test_draft_send_marks_state(db_path):
    with db.session(db_path) as conn:
        store.upsert_contacts(
            conn, [{"full_name": "Priya Raman", "company": "Bain", "email": "p@example.com"}]
        )
        contact_id = store.list_contacts(conn)[0]["id"]

        draft = store.save_draft(conn, contact_id, "Quick question", "Hi Priya,")
        assert draft["status"] == "draft"
        assert draft["to_email"] == "p@example.com"  # inherited from the contact

        sent = store.mark_draft_sent(conn, draft["id"], "gmail-123")
        assert sent["status"] == "sent"
        assert sent["gmail_message_id"] == "gmail-123"
        assert sent["sent_at"]
        assert len(store.list_drafts(conn, status="sent")) == 1

        with pytest.raises(store.NotFound):
            store.save_draft(conn, 4242, "s", "b")


def test_contacts_cascade_on_delete(db_path):
    with db.session(db_path) as conn:
        store.upsert_contacts(conn, [{"full_name": "Priya Raman", "company": "Bain"}])
        contact_id = store.list_contacts(conn)[0]["id"]
        store.add_interaction(conn, contact_id, "note")
        with conn:
            conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
        assert conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0] == 0
