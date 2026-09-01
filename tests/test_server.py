"""Tool-level tests, with the guardrails as the headline cases."""

from datetime import date, timedelta

import pytest

from mba_mcp import ats, config as config_module, gmail, server


def call(tool, **kwargs):
    """Invoke an MCP tool's underlying function."""
    return getattr(tool, "fn", tool)(**kwargs)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """The suite must never reach the internet; discovery is opt-in per test."""
    def blocked(*args, **kwargs):
        raise AssertionError("test attempted a network call")

    monkeypatch.setattr(server.ats, "discover_ats", lambda *a, **k: None)
    monkeypatch.setattr(server.ats, "fetch_board", blocked)
    monkeypatch.setattr(server.ats, "fetch_adzuna", blocked)


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MBA_MCP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    monkeypatch.setenv("MBA_MCP_SCHOOL", "Wharton")
    config_module.get_config(refresh=True)
    yield
    config_module.get_config(refresh=True)


# --------------------------------------------------------------------------
# Targets & discovery
# --------------------------------------------------------------------------


def test_add_target_detects_the_board():
    target = call(
        server.add_target_company,
        name="Acme Co",
        ats_url="https://boards.greenhouse.io/acmeco",
        priority=1,
    )
    assert (target["ats_kind"], target["ats_slug"]) == ("greenhouse", "acmeco")
    assert call(server.list_targets)[0]["name"] == "Acme Co"


def test_add_target_explains_an_unrecognised_url():
    target = call(server.add_target_company, name="McKinsey", ats_url="https://mckinsey.com/careers")
    assert target["ats_kind"] is None
    assert "no job board found" in target["note"]


def test_add_target_discovers_a_board_on_a_careers_page(monkeypatch):
    monkeypatch.setattr(
        server.ats, "discover_ats", lambda url, **kw: ("workday", "citi|wd5|2")
    )
    target = call(server.add_target_company, name="Citi", ats_url="https://jobs.citi.com/")
    assert (target["ats_kind"], target["ats_slug"]) == ("workday", "citi|wd5|2")
    assert "powered by workday" in target["note"]


def test_find_jobs_without_targets_says_so():
    assert call(server.find_jobs)["note"].startswith("No target companies")


def test_find_jobs_sweeps_targets_and_filters(monkeypatch, fixture_json):
    call(server.add_target_company, name="Acme Co", ats_url="https://boards.greenhouse.io/acmeco")

    def fake_fetch(kind, slug, company, keywords=None, location=None, client=None):
        assert (kind, slug) == ("greenhouse", "acmeco")
        return ats.parse_greenhouse(fixture_json("greenhouse.json"), company)

    monkeypatch.setattr(server.ats, "fetch_board", fake_fetch)

    everything = call(server.find_jobs)
    assert len(everything["jobs"]) == 2
    assert everything["checked"][0]["open_roles"] == 2

    filtered = call(server.find_jobs, keywords="summer associate")
    assert [job["title"] for job in filtered["jobs"]] == ["Summer Associate (MBA) - Strategy"]


def test_find_jobs_reports_board_errors_without_failing(monkeypatch):
    call(server.add_target_company, name="Acme Co", ats_url="https://boards.greenhouse.io/acmeco")

    def boom(*args, **kwargs):
        raise ats.AtsError("HTTP 503")

    monkeypatch.setattr(server.ats, "fetch_board", boom)
    result = call(server.find_jobs)
    assert result["jobs"] == []
    assert result["errors"][0]["company"] == "Acme Co"


def test_find_jobs_without_ats_or_adzuna_explains_the_gap():
    call(server.add_target_company, name="Bain & Company")
    result = call(server.find_jobs)
    assert "No ATS URL" in result["errors"][0]["error"]


# --------------------------------------------------------------------------
# Pipeline & timeline
# --------------------------------------------------------------------------


def test_pipeline_tracks_and_advances():
    app = call(
        server.track_application,
        company="Bain",
        role="Summer Associate",
        deadline="2027-01-10",
    )
    assert app["status"] == "interested"

    call(server.update_application, id=app["id"], status="applied")
    pipeline = call(server.list_applications)
    assert pipeline["counts_by_status"] == {"applied": 1}
    assert pipeline["applications"][0]["status"] == "applied"
    assert call(server.list_applications, status="offer")["applications"] == []


def test_timeline_is_relative_to_today():
    rendered = call(server.get_recruiting_timeline, track="consulting")
    assert rendered["today"] == date.today().isoformat()
    assert rendered["milestones"]
    assert rendered["disclaimer"]


def test_timeline_unknown_track_lists_options():
    result = call(server.get_recruiting_timeline, track="quidditch")
    assert "consulting" in result["available_tracks"]


# --------------------------------------------------------------------------
# Networking
# --------------------------------------------------------------------------


def test_import_then_find_warm_paths(fixtures_dir):
    imported = call(server.import_connections, csv_path=str(fixtures_dir / "connections.csv"))
    assert imported["inserted"] == 4
    assert imported["parsed_rows"] == 4  # the nameless row never reaches the store

    again = call(server.import_connections, csv_path=str(fixtures_dir / "connections.csv"))
    assert again["inserted"] == 0 and again["total_contacts"] == 4

    paths = call(server.find_warm_paths, company="Bain & Company")
    assert paths["paths"][0]["contact"]["full_name"] == "Priya Raman"
    assert paths["paths"][0]["reasons"]
    assert paths["contacts_searched"] == 4


def test_find_warm_paths_with_no_contacts_points_at_import():
    assert "import_connections" in call(server.find_warm_paths, company="Bain")["note"]


def test_import_connections_reports_a_bad_path():
    assert "error" in call(server.import_connections, csv_path="/nope/missing.csv")


def test_log_interaction_drives_followups(fixtures_dir):
    call(server.import_connections, csv_path=str(fixtures_dir / "connections.csv"))
    contact_id = call(server.find_warm_paths, company="Bain & Company")["paths"][0]["contact"]["id"]

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    logged = call(
        server.log_interaction,
        contact_id=contact_id,
        kind="coffee_chat",
        notes="Wants a follow-up after the Sept presentation",
        next_followup=yesterday,
    )
    assert logged["contact"]["full_name"] == "Priya Raman"

    due = call(server.get_followups)
    assert due["count"] == 1
    assert due["due"][0]["days_overdue"] == 1
    assert due["due"][0]["last_kind"] == "coffee_chat"


def test_log_interaction_rejects_unknown_contact():
    assert "error" in call(server.log_interaction, contact_id=999, kind="call")


def test_interaction_without_followup_warns():
    call(server.import_connections, csv_path=str(__import__("pathlib").Path(__file__).parent / "fixtures" / "connections.csv"))
    contact_id = call(server.find_warm_paths, company="Bain & Company")["paths"][0]["contact"]["id"]
    logged = call(server.log_interaction, contact_id=contact_id, kind="note")
    assert "hint" in logged
    assert call(server.get_followups)["count"] == 0


# --------------------------------------------------------------------------
# Outreach — the guardrails
# --------------------------------------------------------------------------


@pytest.fixture
def draft(fixtures_dir):
    call(server.import_connections, csv_path=str(fixtures_dir / "connections.csv"))
    contact_id = call(server.find_warm_paths, company="Bain & Company")["paths"][0]["contact"]["id"]
    return call(
        server.save_outreach_draft,
        contact_id=contact_id,
        subject="Wharton MBA — quick question about Bain Boston",
        body="Hi Priya, ...",
    )


def test_saving_a_draft_sends_nothing(draft, monkeypatch):
    sent = []
    monkeypatch.setattr(gmail, "send_one", lambda *a, **k: sent.append(a) or "id")
    assert draft["status"] == "draft"
    assert draft["to_email"] == "priya.raman@example.com"
    assert "confirm=True" in draft["next_step"]
    assert sent == []


def test_send_email_refuses_without_confirmation(draft, monkeypatch):
    sent = []
    monkeypatch.setattr(server.gmail, "send_one", lambda *a, **k: sent.append(a) or "id")

    result = call(server.send_email, draft_id=draft["id"])
    assert result["status"] == "confirmation_required"
    assert result["to"] == "priya.raman@example.com"
    assert result["body"] == "Hi Priya, ..."
    assert sent == []


def test_send_email_sends_exactly_one_message(draft, monkeypatch):
    calls = []

    def fake_send(config, to, subject, body):
        calls.append((to, subject, body))
        return "gmail-abc"

    monkeypatch.setattr(server.gmail, "send_one", fake_send)

    result = call(server.send_email, draft_id=draft["id"], confirm=True)
    assert len(calls) == 1
    assert calls[0][0] == "priya.raman@example.com"
    assert result["status"] == "sent"
    assert result["gmail_message_id"] == "gmail-abc"

    # A sent draft cannot be sent twice.
    again = call(server.send_email, draft_id=draft["id"], confirm=True)
    assert "already sent" in again["error"]
    assert len(calls) == 1


def test_send_email_requires_a_single_valid_recipient(fixtures_dir, monkeypatch):
    call(server.import_connections, csv_path=str(fixtures_dir / "connections.csv"))
    # Tom Okafor has no email address in the export.
    tom = next(
        path["contact"]
        for path in call(server.find_warm_paths, company="Bain Capital")["paths"]
        if path["contact"]["full_name"] == "Tom Okafor"
    )
    draft = call(server.save_outreach_draft, contact_id=tom["id"], subject="Hi", body="Hello")
    assert "note" in draft

    sent = []
    monkeypatch.setattr(server.gmail, "send_one", lambda *a, **k: sent.append(a) or "id")
    result = call(server.send_email, draft_id=draft["id"], confirm=True)
    assert "single valid recipient" in result["error"]
    assert sent == []

    blocked = call(
        server.send_email,
        draft_id=draft["id"],
        confirm=True,
        to_email="a@example.com, b@example.com",
    )
    assert "single valid recipient" in blocked["error"]
    assert sent == []


def test_send_email_reports_a_missing_draft():
    assert "error" in call(server.send_email, draft_id=999, confirm=True)


def test_gmail_message_has_one_recipient():
    payload = gmail.build_message("p@example.com", "Subject", "Body")
    assert set(payload) == {"raw"}
    import base64

    decoded = base64.urlsafe_b64decode(payload["raw"]).decode()
    assert decoded.count("To:") == 1
    assert "p@example.com" in decoded
    assert not gmail.valid_recipient("a@example.com, b@example.com")
    assert not gmail.valid_recipient(None)


# --------------------------------------------------------------------------
# Resources
# --------------------------------------------------------------------------


def test_resources_expose_current_state(fixtures_dir):
    import json

    call(server.add_target_company, name="Acme Co", ats_url="https://jobs.lever.co/acme")
    call(server.track_application, company="Acme Co", role="Summer Associate")
    call(server.import_connections, csv_path=str(fixtures_dir / "connections.csv"))

    assert json.loads(call(server.targets_resource))[0]["name"] == "Acme Co"
    assert json.loads(call(server.pipeline_resource))["applications"][0]["role"] == "Summer Associate"
    assert json.loads(call(server.contacts_resource))["total"] == 4
    assert json.loads(call(server.timeline_resource))["track"] == "consulting"
    assert "No base CV found" in call(server.base_cv)


def test_base_cv_resource_reads_the_users_file(tmp_path, monkeypatch):
    cv = tmp_path / "cv.md"
    cv.write_text("# Neeharika\nWharton MBA", encoding="utf-8")
    monkeypatch.setenv("MBA_MCP_BASE_CV", str(cv))
    config_module.get_config(refresh=True)
    assert "Wharton MBA" in call(server.base_cv)


# --------------------------------------------------------------------------
# Profile, starter packs, alumni and email inference
# --------------------------------------------------------------------------


def test_set_profile_merges_fields():
    first = call(server.set_profile, school="Wharton", graduation_year=2028)
    assert first["school"] == "Wharton"
    assert "next_step" in first

    second = call(server.set_profile, track="finance")
    assert second["track"] == "investment_banking"  # alias resolved
    assert second["school"] == "Wharton"  # untouched field survives
    assert second["graduation_year"] == 2028


def test_set_profile_flags_what_is_missing():
    assert "school" in call(server.set_profile, full_name="Neeharika")["hint"]


def test_profile_drives_the_timeline_resource():
    import json

    call(server.set_profile, track="finance")
    assert json.loads(call(server.timeline_resource))["track"] == "investment_banking"
    assert json.loads(call(server.profile_resource))["school"] is None


def test_target_packs_are_listed():
    packs = {pack["pack"] for pack in call(server.list_target_packs)["packs"]}
    assert packs == {"consulting", "investment_banking"}


def test_add_target_pack_seeds_the_target_list(monkeypatch):
    monkeypatch.setattr(
        server.ats, "discover_ats", lambda url, **kw: ("greenhouse", "discovered")
    )
    result = call(server.add_target_pack, pack="finance", priority_max=1)
    assert result["pack"] == "investment_banking"
    assert result["added"]
    assert result["no_readable_board"] == []  # everything resolved via the stub

    names = {target["name"] for target in call(server.list_targets)}
    assert "PJT Partners" in names
    # Pre-resolved boards are used as-is rather than re-discovered.
    pjt = next(t for t in call(server.list_targets) if t["name"] == "PJT Partners")
    assert (pjt["ats_kind"], pjt["ats_slug"]) == ("workday", "pjtpartners|wd1|Careers")


def test_add_target_pack_reports_firms_with_no_board():
    result = call(server.add_target_pack, pack="consulting", priority_max=1)
    assert result["added"] == []
    assert {firm["name"] for firm in result["no_readable_board"]} >= {"Bain & Company"}
    assert "target list" in result["summary"]


def test_add_target_pack_rejects_an_unknown_pack():
    assert "available_packs" in call(server.add_target_pack, pack="crypto")


def test_add_target_pack_respects_priority_max():
    call(server.add_target_pack, pack="consulting", priority_max=1, resolve=False)
    assert len(call(server.list_targets)) == 3  # only the MBB tier


def test_find_alumni_needs_a_school_first(monkeypatch):
    monkeypatch.delenv("MBA_MCP_SCHOOL", raising=False)
    config_module.get_config(refresh=True)
    result = call(server.find_alumni, company="Evercore")
    assert "set_profile" in result["hint"]
    # Company-level searches still work without one.
    assert any("Evercore" in link["label"] for link in result["linkedin_searches"])


def test_find_alumni_builds_searches_and_lists_known_alumni(fixtures_dir):
    call(server.set_profile, school="Wharton", graduation_year=2028)
    call(server.import_connections, csv_path=str(fixtures_dir / "connections.csv"))
    contact_id = call(server.find_warm_paths, company="Bain & Company")["paths"][0]["contact"]["id"]
    call(server.set_contact_email, contact_id=contact_id, email="priya.raman@bain.com")

    result = call(server.find_alumni, company="Bain & Company")
    assert result["school"] == "Wharton"
    assert any("Wharton" in link["url"] for link in result["linkedin_searches"])
    assert "re-export" in result["how_this_works"]
    # Nobody in the fixture export lists a school, so we say so rather than guess.
    assert result["known_alumni"] == []
    assert "no school" in result["hint"].lower()


def test_suggest_email_learns_the_firm_pattern(fixtures_dir):
    call(server.import_connections, csv_path=str(fixtures_dir / "connections.csv"))
    paths = call(server.find_warm_paths, company="Bain & Company")["paths"]
    priya = next(p["contact"] for p in paths if p["contact"]["full_name"] == "Priya Raman")
    tom = next(p["contact"] for p in paths if p["contact"]["full_name"] == "Tom Okafor")

    # Priya already has an address, so there is nothing to guess.
    assert call(server.suggest_email, contact_id=priya["id"])["email"] == "priya.raman@example.com"

    # Tom has none; Priya's address at a different firm gives us nothing.
    assert call(server.suggest_email, contact_id=tom["id"])["suggestions"] == []

    # Give Tom a colleague and the pattern becomes learnable.
    call(server.import_connections, csv_path=str(fixtures_dir / "bain_capital.csv"))
    result = call(server.suggest_email, contact_id=tom["id"])
    best = result["suggestions"][0]
    assert best["email"] == "tom.okafor@baincapital.com"
    assert best["verified"] is False
    assert "Unverified" in result["warning"]


def test_suggest_email_handles_a_missing_contact():
    assert "error" in call(server.suggest_email, contact_id=999)


def test_set_contact_email_validates(fixtures_dir):
    call(server.import_connections, csv_path=str(fixtures_dir / "connections.csv"))
    contact_id = call(server.find_warm_paths, company="Bain Capital")["paths"][0]["contact"]["id"]
    assert "error" in call(server.set_contact_email, contact_id=contact_id, email="not-an-email")
    saved = call(server.set_contact_email, contact_id=contact_id, email="a@bain.com")
    assert saved["email"] == "a@bain.com"
