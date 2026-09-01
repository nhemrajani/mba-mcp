"""Email-pattern inference from the user's own contacts."""

import pytest

from mba_mcp import emails


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Priya Raman", ("priya", "raman")),
        ("José Álvarez", ("jose", "alvarez")),
        ("Mary-Kate O'Brien", ("mary-kate", "obrien")),
        ("John Smith Jr", ("john", "smith")),
        ("Tom van der Berg", ("tom", "berg")),
        ("Cher", None),
        ("", None),
    ],
)
def test_split_name(name, expected):
    assert emails.split_name(name) == expected


@pytest.mark.parametrize(
    "email,pattern",
    [
        ("priya.raman@bain.com", "first.last"),
        ("priyaraman@bain.com", "firstlast"),
        ("p.raman@bain.com", "f.last"),
        ("praman@bain.com", "flast"),
        ("raman.priya@bain.com", "last.first"),
        ("priya@bain.com", "first"),
        ("someoneelse@bain.com", None),
    ],
)
def test_identify_pattern(email, pattern):
    assert emails.identify_pattern("Priya Raman", email) == pattern


def test_consumer_domains_are_ignored():
    assert emails.email_domain("priya@gmail.com") is None
    assert emails.email_domain("priya@bain.com") == "bain.com"
    assert emails.email_domain(None) is None


def test_suggestion_is_high_confidence_when_two_colleagues_agree():
    known = [
        {"full_name": "Priya Raman", "company": "Bain & Company", "email": "priya.raman@bain.com"},
        {"full_name": "Tom Okafor", "company": "Bain & Company", "email": "tom.okafor@bain.com"},
    ]
    target = {"full_name": "Dana Whitfield", "company": "Bain"}
    best = emails.suggest_addresses(target, known)[0]
    assert best["email"] == "dana.whitfield@bain.com"
    assert best["confidence"] == "high"
    assert best["verified"] is False
    assert "2 known addresses" in best["basis"]


def test_single_sample_is_only_medium_confidence():
    known = [{"full_name": "Priya Raman", "company": "Bain", "email": "praman@bain.com"}]
    best = emails.suggest_addresses({"full_name": "Dana Whitfield", "company": "Bain"}, known)[0]
    assert best["email"] == "dwhitfield@bain.com"
    assert best["confidence"] == "medium"


def test_known_domain_but_no_pattern_falls_back_to_low():
    known = [{"full_name": "Priya Raman", "company": "Bain", "email": "xyz123@bain.com"}]
    best = emails.suggest_addresses({"full_name": "Dana Whitfield", "company": "Bain"}, known)[0]
    assert best["confidence"] == "low"
    assert best["email"] == "dana.whitfield@bain.com"


def test_no_domain_means_no_guessing():
    known = [{"full_name": "Priya Raman", "company": "Bain", "email": "priya@gmail.com"}]
    assert emails.suggest_addresses({"full_name": "Dana Whitfield", "company": "Bain"}, known) == []
    assert emails.suggest_addresses({"full_name": "Cher", "company": "Bain"}, known) == []
