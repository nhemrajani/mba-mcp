from datetime import date

import pytest

from mba_mcp import connections


def test_parse_connections_csv_skips_linkedin_preamble(fixtures_dir):
    contacts = connections.parse_connections_csv(fixtures_dir / "connections.csv")
    assert len(contacts) == 4  # the nameless row is dropped
    priya = contacts[0]
    assert priya["full_name"] == "Priya Raman"
    assert priya["company"] == "Bain & Company"
    assert priya["title"] == "Consultant"
    assert priya["email"] == "priya.raman@example.com"
    assert priya["connected_on"] == "2025-06-18"
    assert priya["source"] == "linkedin_csv"
    assert contacts[1]["email"] is None


def test_parse_connections_csv_handles_slash_dates(fixtures_dir):
    contacts = connections.parse_connections_csv(fixtures_dir / "connections.csv")
    alex = next(c for c in contacts if c["full_name"] == "Alex Nkemdirim")
    assert alex["connected_on"] == "2023-05-14"


def test_parse_connections_csv_rejects_wrong_file(tmp_path):
    path = tmp_path / "notes.csv"
    path.write_text("some,other,file\n1,2,3\n", encoding="utf-8")
    with pytest.raises(connections.ImportError_):
        connections.parse_connections_csv(path)
    with pytest.raises(connections.ImportError_):
        connections.parse_connections_csv(tmp_path / "missing.csv")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Bain & Company", "bain"),
        ("McKinsey & Company, Inc.", "mckinsey"),
        ("Acme Logistics", "acme logistics"),
        (None, ""),
    ],
)
def test_normalise_company_drops_legal_noise(raw, expected):
    assert connections.normalise_company(raw) == expected


def test_company_affinity_ranks_exact_above_partial():
    exact = connections.company_affinity("Bain & Company", "Bain")
    partial = connections.company_affinity("Bain Capital", "Bain")
    assert exact[0] > partial[0]
    assert connections.company_affinity("Acme Logistics", "Bain") is None
    assert connections.company_affinity(None, "Bain") is None


def test_score_contact_rewards_recruiters_and_alumni():
    base = {"full_name": "A", "company": "Bain & Company", "title": "Consultant"}
    recruiter = {**base, "title": "Campus Recruiting Lead"}
    plain, _ = connections.score_contact(base, "Bain")
    boosted, reasons = connections.score_contact(recruiter, "Bain")
    assert boosted > plain
    assert any("recruiting-side" in reason for reason in reasons)

    alum = {**base, "school": "Wharton"}
    scored, reasons = connections.score_contact(alum, "Bain", school="Wharton")
    assert scored > plain
    assert any("alum" in reason for reason in reasons)


def test_score_contact_is_capped():
    contact = {
        "full_name": "A",
        "company": "Bain",
        "title": "Campus Recruiting Partner",
        "school": "Wharton",
        "email": "a@example.com",
        "connected_on": date.today().isoformat(),
    }
    score, _ = connections.score_contact(
        contact, "Bain", school="Wharton", interaction_count=9
    )
    assert score == connections.MAX_SCORE


def test_rank_contacts_orders_by_closeness(fixtures_dir):
    contacts = connections.parse_connections_csv(fixtures_dir / "connections.csv")
    for index, contact in enumerate(contacts, start=1):
        contact["id"] = index

    ranked = connections.rank_contacts(contacts, "Bain & Company", today=date(2026, 9, 1))
    names = [item["contact"]["full_name"] for item in ranked]
    assert names[0] == "Priya Raman"
    assert "Alex Nkemdirim" not in names  # unrelated employer scores below the floor
    assert ranked[0]["score"] > ranked[-1]["score"]
    assert ranked[0]["reasons"]


def test_rank_contacts_counts_logged_interactions(fixtures_dir):
    contacts = connections.parse_connections_csv(fixtures_dir / "connections.csv")
    for index, contact in enumerate(contacts, start=1):
        contact["id"] = index
    history = {2: {"count": 2, "last_occurred_at": "2026-08-01"}}

    today = date(2026, 9, 1)
    cold = connections.rank_contacts(contacts, "Bain Capital", today=today)
    warm = connections.rank_contacts(
        contacts, "Bain Capital", interactions=history, today=today
    )
    tom_cold = next(i for i in cold if i["contact"]["id"] == 2)
    tom_warm = next(i for i in warm if i["contact"]["id"] == 2)
    assert tom_warm["score"] > tom_cold["score"]
    assert tom_warm["last_interaction"] == "2026-08-01"
