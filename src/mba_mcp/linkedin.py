"""LinkedIn deep links — search URLs a human clicks, not pages a bot reads.

LinkedIn has no public jobs or people API, and scraping it risks the user's own
account. What is entirely legitimate is constructing the search URL they would
have typed themselves: we pre-fill the school, company and keyword filters, the
user opens it in their browser while logged in as themselves, and anyone they
connect with turns up in their next CSV export.

Everything here is pure string building. No requests are made.
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlencode

PEOPLE_SEARCH = "https://www.linkedin.com/search/results/people/"
JOB_SEARCH = "https://www.linkedin.com/jobs/search/"
SCHOOL_ALUMNI = "https://www.linkedin.com/school/{slug}/people/"

# LinkedIn's "posted in the last N" filter, in seconds.
POSTED_WINDOWS = {1: "r86400", 7: "r604800", 30: "r2592000"}


def school_slug(school: str) -> str:
    """Best-effort LinkedIn school slug, e.g. 'Wharton' -> 'wharton'.

    LinkedIn slugs are not derivable in general, so the alumni-tool link is
    offered as a *likely* URL alongside a search that always works.
    """
    slug = re.sub(r"[^\w\s-]", "", school.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")


def alumni_search_url(
    school: str,
    company: str | None = None,
    keywords: str | None = None,
    graduated_within_years: int | None = None,
    today: date | None = None,
) -> str:
    """People search scoped to a school, optionally at one company."""
    terms = [f'"{school}"']
    if company:
        terms.append(f'"{company}"')
    if keywords:
        terms.append(keywords)
    if graduated_within_years:
        today = today or date.today()
        years = [str(today.year - offset) for offset in range(graduated_within_years + 1)]
        terms.append("(" + " OR ".join(years) + ")")
    return PEOPLE_SEARCH + "?" + urlencode({"keywords": " ".join(terms), "origin": "GLOBAL_SEARCH_HEADER"})


def alumni_tool_url(school: str, company: str | None = None) -> str:
    """The school's own alumni browser, which filters by employer directly."""
    url = SCHOOL_ALUMNI.format(slug=school_slug(school))
    return url + "?" + urlencode({"keywords": company}) if company else url


def people_at_company_url(company: str, keywords: str | None = None) -> str:
    terms = [f'"{company}"']
    if keywords:
        terms.append(keywords)
    return PEOPLE_SEARCH + "?" + urlencode({"keywords": " ".join(terms)})


def job_search_url(
    keywords: str | None = None,
    location: str | None = None,
    company: str | None = None,
    posted_within_days: int = 7,
) -> str:
    """A LinkedIn Jobs search the user can open and save as an alert."""
    query = " ".join(part for part in [company, keywords] if part)
    params: dict[str, str] = {}
    if query:
        params["keywords"] = query
    if location:
        params["location"] = location
    window = POSTED_WINDOWS.get(posted_within_days)
    if window:
        params["f_TPR"] = window
    return JOB_SEARCH + ("?" + urlencode(params) if params else "")


def search_links(
    company: str | None = None,
    school: str | None = None,
    keywords: str | None = None,
    location: str | None = None,
    graduated_within_years: int = 5,
) -> list[dict]:
    """Build the set of searches worth running for a target, with instructions."""
    links: list[dict] = []

    if school and company:
        links.append(
            {
                "label": f"{school} alumni at {company}",
                "url": alumni_search_url(school, company, graduated_within_years=graduated_within_years),
                "why": "Shared-school cold outreach gets answered far more often than a stranger's.",
                "what_to_do": "Open it, connect with 3-5 people, then re-export your "
                "connections and run import_connections again so they become warm paths.",
            }
        )
        links.append(
            {
                "label": f"{school} alumni browser, filtered to {company}",
                "url": alumni_tool_url(school, company),
                "why": "The school's own alumni tool shows where graduates actually landed.",
                "what_to_do": "If the link 404s, LinkedIn spells your school differently — "
                "search for the school page and use its URL slug.",
            }
        )

    if company:
        links.append(
            {
                "label": f"Recent grads and juniors at {company}",
                "url": people_at_company_url(company, keywords or "Associate OR Analyst"),
                "why": "Junior people reply more, know the current process, and can refer.",
                "what_to_do": "Prefer people 1-4 years out over senior partners for a first chat.",
            }
        )
        links.append(
            {
                "label": f"{company} jobs posted this week",
                "url": job_search_url(keywords, location, company, posted_within_days=7),
                "why": "Catches postings syndicated to LinkedIn that never hit the company board.",
                "what_to_do": "Apply on the company's own site where you can — "
                "find_jobs already reads it.",
            }
        )
    elif keywords or location:
        links.append(
            {
                "label": "Job search",
                "url": job_search_url(keywords, location, posted_within_days=7),
                "why": "Broad sweep across every employer.",
                "what_to_do": "Save it as a LinkedIn job alert so new roles email you daily.",
            }
        )

    return links
