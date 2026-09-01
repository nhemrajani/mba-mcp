"""Deep-link building. Nothing here touches the network by design."""

from datetime import date
from urllib.parse import parse_qs, urlparse

from mba_mcp import linkedin


def _params(url: str) -> dict:
    return {key: value[0] for key, value in parse_qs(urlparse(url).query).items()}


def test_alumni_search_combines_school_and_company():
    url = linkedin.alumni_search_url("Wharton", "Bain & Company")
    assert url.startswith(linkedin.PEOPLE_SEARCH)
    keywords = _params(url)["keywords"]
    assert '"Wharton"' in keywords and '"Bain & Company"' in keywords


def test_alumni_search_can_scope_to_recent_classes():
    url = linkedin.alumni_search_url(
        "Wharton", graduated_within_years=2, today=date(2026, 9, 1)
    )
    keywords = _params(url)["keywords"]
    assert "(2026 OR 2025 OR 2024)" in keywords


def test_school_slug_and_alumni_tool():
    assert linkedin.school_slug("London Business School") == "london-business-school"
    assert linkedin.school_slug("Wharton (UPenn)") == "wharton-upenn"
    url = linkedin.alumni_tool_url("Wharton", "Bain")
    assert url.startswith("https://www.linkedin.com/school/wharton/people/")
    assert _params(url)["keywords"] == "Bain"


def test_job_search_sets_the_recency_filter():
    url = linkedin.job_search_url("summer associate", "New York", "Evercore", posted_within_days=7)
    params = _params(url)
    assert params["f_TPR"] == "r604800"
    assert params["keywords"] == "Evercore summer associate"
    assert params["location"] == "New York"
    assert "f_TPR" not in _params(linkedin.job_search_url("x", posted_within_days=99))


def test_search_links_cover_alumni_juniors_and_jobs():
    links = linkedin.search_links(company="Evercore", school="Wharton", keywords="banking")
    labels = " ".join(link["label"] for link in links)
    assert "alumni" in labels.lower()
    assert "Evercore" in labels
    assert all(link["url"].startswith("https://www.linkedin.com/") for link in links)
    assert all(link["what_to_do"] for link in links)


def test_search_links_degrade_without_a_school():
    links = linkedin.search_links(company="Evercore")
    assert links and all("alumni" not in link["label"].lower() for link in links)
    assert linkedin.search_links() == []
