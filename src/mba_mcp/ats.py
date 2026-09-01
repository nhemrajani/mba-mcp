"""Applicant-tracking-system adapters.

Resolving a company to its job board is the interesting problem here. Rather
than maintain a registry of every firm, we read the careers URL the user
pastes: the ATS vendors all put the company's board slug in a predictable spot.
When the URL is a marketing careers page rather than the board itself,
:func:`discover_ats` fetches it and looks for the board it embeds or links to —
which is how firms like Citi, PJT and Blackstone resolve without anyone
knowing their Workday tenant name. Adzuna is the keyed fallback of last resort.

Each ``parse_*`` function is pure — it takes decoded JSON and returns
normalised job dicts — so the adapters can be tested against saved fixtures
without network access.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
LEVER_API = "https://api.lever.co/v0/postings/{slug}?mode=json"
ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"
WORKDAY_API = "https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
WORKDAY_JOB = "https://{tenant}.{wd}.myworkdayjobs.com/{site}{path}"
SMARTRECRUITERS_API = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
SMARTRECRUITERS_JOB = "https://jobs.smartrecruiters.com/{slug}/{job_id}"
ADZUNA_API = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"

USER_AGENT = "mba-mcp/0.2 (+https://github.com/)"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TIMEOUT = httpx.Timeout(20.0)

# Workday pages 20 at a time; three pages is plenty for a targeted search.
WORKDAY_PAGE = 20
WORKDAY_MAX_PAGES = 3

ATS_KINDS = ("greenhouse", "lever", "ashby", "workday", "smartrecruiters")

_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._|-]*$")

# Signatures of an embedded or linked board, used when scanning a careers page.
_BOARD_SIGNATURES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)")),
    ("lever", re.compile(r"jobs\.lever\.co/([A-Za-z0-9_-]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_-]+)")),
    ("workday", re.compile(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)")),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)")),
)

# Path segments that are a Workday locale or app route, never the site name.
_WORKDAY_NON_SITE = re.compile(r"^(?:[a-z]{2}-[A-Z]{2}|wday|cxs|job|jobs|details|login)$")


class AtsError(RuntimeError):
    """A job board rejected the request or returned something unusable."""


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------


def detect_ats(url: str) -> tuple[str, str] | None:
    """Return ``(kind, slug)`` for a job-board URL, or ``None`` if unrecognised.

    Handles the public board URLs students actually paste as well as the raw
    API endpoints::

        https://boards.greenhouse.io/acme            -> ("greenhouse", "acme")
        https://jobs.lever.co/acme/1234              -> ("lever", "acme")
        https://jobs.ashbyhq.com/acme                -> ("ashby", "acme")
        https://acme.wd1.myworkdayjobs.com/Careers   -> ("workday", "acme|wd1|Careers")
        https://jobs.smartrecruiters.com/Acme        -> ("smartrecruiters", "Acme")

    Workday needs three coordinates, so its slug is a ``tenant|wd|site``
    triple; :func:`split_workday_slug` takes it apart again.
    """
    if not url or not url.strip():
        return None

    candidate = url.strip()
    if "://" not in candidate:
        candidate = "https://" + candidate

    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    parts = [p for p in parsed.path.split("/") if p]

    if host.endswith("myworkdayjobs.com"):
        return _detect_workday(host, parts)

    if host.endswith("smartrecruiters.com"):
        if "companies" in parts:
            index = parts.index("companies")
            if index + 1 < len(parts):
                return _valid("smartrecruiters", parts[index + 1])
        if parts:
            return _valid("smartrecruiters", parts[0])
        return None

    if host.endswith("greenhouse.io"):
        query_slug = parse_qs(parsed.query).get("for", [""])[0]
        if query_slug:
            return _valid("greenhouse", query_slug)
        if "boards" in parts:
            index = parts.index("boards")
            if index + 1 < len(parts):
                return _valid("greenhouse", parts[index + 1])
        if parts and parts[0] not in {"embed", "v1"}:
            return _valid("greenhouse", parts[0])
        return None

    if host.endswith("lever.co"):
        if "postings" in parts:
            index = parts.index("postings")
            if index + 1 < len(parts):
                return _valid("lever", parts[index + 1])
        if parts:
            return _valid("lever", parts[0])
        return None

    if host.endswith("ashbyhq.com"):
        if "job-board" in parts:
            index = parts.index("job-board")
            if index + 1 < len(parts):
                return _valid("ashby", parts[index + 1])
        if parts:
            return _valid("ashby", parts[0])
        return None

    return None


def _detect_workday(host: str, parts: list[str]) -> tuple[str, str] | None:
    labels = host.split(".")
    if len(labels) < 4:
        return None
    tenant, wd = labels[0], labels[1]
    if not re.fullmatch(r"wd\d+", wd):
        return None

    # The API form carries the site explicitly: /wday/cxs/{tenant}/{site}/jobs
    if "cxs" in parts:
        index = parts.index("cxs")
        if index + 2 < len(parts):
            return _valid("workday", f"{tenant}|{wd}|{parts[index + 2]}")

    site = next((part for part in parts if not _WORKDAY_NON_SITE.match(part)), None)
    return _valid("workday", f"{tenant}|{wd}|{site}") if site else None


def split_workday_slug(slug: str) -> tuple[str, str, str]:
    parts = slug.split("|")
    if len(parts) != 3 or not all(parts):
        raise AtsError(f"Malformed Workday slug '{slug}'; expected tenant|wd|site.")
    return parts[0], parts[1], parts[2]


def _valid(kind: str, slug: str | None) -> tuple[str, str] | None:
    if not slug:
        return None
    slug = slug.strip().strip("/")
    return (kind, slug) if slug and _SLUG_RE.match(slug) else None


def find_board_in_html(html: str) -> tuple[str, str] | None:
    """Spot a board embedded in, or linked from, a careers page's markup."""
    best: tuple[int, str, str] | None = None
    for kind, pattern in _BOARD_SIGNATURES:
        match = pattern.search(html)
        if not match:
            continue
        slug = "|".join(match.groups()) if kind == "workday" else match.group(1)
        detected = _valid(kind, slug)
        if detected and (best is None or match.start() < best[0]):
            best = (match.start(), detected[0], detected[1])
    return (best[1], best[2]) if best else None


def discover_ats(url: str, client: httpx.Client | None = None) -> tuple[str, str] | None:
    """Resolve a company's board from any careers URL.

    Tries the URL itself first; if it isn't a board, fetches the page and looks
    for one. Returns ``None`` rather than raising — a firm whose board we can't
    find is a normal outcome, not an error.
    """
    direct = detect_ats(url)
    if direct:
        return direct

    target = url.strip()
    if "://" not in target:
        target = "https://" + target

    owned = client is None
    client = client or httpx.Client(
        timeout=TIMEOUT, headers={"User-Agent": BROWSER_UA}, follow_redirects=True
    )
    try:
        response = client.get(target)
        if response.status_code >= 400:
            return None
        return find_board_in_html(response.text)
    except httpx.HTTPError:
        return None
    finally:
        if owned:
            client.close()


# --------------------------------------------------------------------------
# Parsers — pure, fixture-testable
# --------------------------------------------------------------------------


def parse_greenhouse(payload: Any, company: str) -> list[dict]:
    jobs = []
    for job in _items(payload, "jobs"):
        url = job.get("absolute_url")
        title = job.get("title")
        if not url or not title:
            continue
        location = (job.get("location") or {}).get("name")
        jobs.append(
            _job(
                company=company,
                title=title,
                location=location,
                url=url,
                posted_at=job.get("first_published") or job.get("updated_at"),
                source="greenhouse",
            )
        )
    return jobs


def parse_lever(payload: Any, company: str) -> list[dict]:
    jobs = []
    for job in _items(payload, None):
        url = job.get("hostedUrl") or job.get("applyUrl")
        title = job.get("text")
        if not url or not title:
            continue
        categories = job.get("categories") or {}
        jobs.append(
            _job(
                company=company,
                title=title,
                location=categories.get("location"),
                url=url,
                posted_at=_from_epoch_ms(job.get("createdAt")),
                source="lever",
            )
        )
    return jobs


def parse_ashby(payload: Any, company: str) -> list[dict]:
    jobs = []
    for job in _items(payload, "jobs"):
        if job.get("isListed") is False:
            continue
        url = job.get("jobUrl") or job.get("applyUrl")
        title = job.get("title")
        if not url or not title:
            continue
        jobs.append(
            _job(
                company=company,
                title=title,
                location=job.get("location"),
                url=url,
                posted_at=job.get("publishedAt") or job.get("updatedAt"),
                source="ashby",
            )
        )
    return jobs


def parse_workday(payload: Any, company: str, slug: str, today: date | None = None) -> list[dict]:
    """Workday reports age as prose ('Posted 3 Days Ago'), so dates are approximate."""
    tenant, wd, site = split_workday_slug(slug)
    jobs = []
    for job in _items(payload, "jobPostings"):
        path = job.get("externalPath")
        title = job.get("title")
        if not path or not title:
            continue
        jobs.append(
            _job(
                company=company,
                title=title,
                location=job.get("locationsText"),
                url=WORKDAY_JOB.format(tenant=tenant, wd=wd, site=site, path=path),
                posted_at=_from_posted_on(job.get("postedOn"), today),
                source="workday",
            )
        )
    return jobs


def parse_smartrecruiters(payload: Any, company: str, slug: str | None = None) -> list[dict]:
    jobs = []
    for job in _items(payload, "content"):
        job_id = job.get("id")
        title = job.get("name")
        if not job_id or not title:
            continue
        identifier = (job.get("company") or {}).get("identifier") or slug or ""
        location = job.get("location") or {}
        where = location.get("fullLocation") or ", ".join(
            part for part in (location.get("city"), location.get("region")) if part
        )
        jobs.append(
            _job(
                company=company,
                title=title,
                location=where or None,
                url=SMARTRECRUITERS_JOB.format(slug=identifier, job_id=job_id),
                posted_at=job.get("releasedDate"),
                source="smartrecruiters",
            )
        )
    return jobs


def parse_adzuna(payload: Any, company: str | None = None) -> list[dict]:
    jobs = []
    for job in _items(payload, "results"):
        url = job.get("redirect_url")
        title = job.get("title")
        if not url or not title:
            continue
        jobs.append(
            _job(
                company=(job.get("company") or {}).get("display_name") or company or "",
                title=_strip_tags(title),
                location=(job.get("location") or {}).get("display_name"),
                url=url,
                posted_at=job.get("created"),
                source="adzuna",
            )
        )
    return jobs


def _items(payload: Any, key: str | None) -> list[dict]:
    if key is not None and isinstance(payload, dict):
        payload = payload.get(key) or []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _job(**fields: Any) -> dict:
    fields["posted_at"] = _normalise_date(fields.get("posted_at"))
    location = fields.get("location")
    fields["location"] = location.strip() if isinstance(location, str) and location.strip() else None
    fields["title"] = str(fields["title"]).strip()
    return fields


def _normalise_date(value: Any) -> str | None:
    """Reduce whatever the board returned to a plain ``YYYY-MM-DD``."""
    if not value:
        return None
    if isinstance(value, (int, float)):
        return _from_epoch_ms(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) else None


def _from_epoch_ms(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _from_posted_on(value: Any, today: date | None = None) -> str | None:
    """Turn 'Posted 3 Days Ago' into a date. Approximate by construction."""
    if not value:
        return None
    text = str(value).strip().lower()
    today = today or date.today()
    if "today" in text:
        return today.isoformat()
    if "yesterday" in text:
        return (today - timedelta(days=1)).isoformat()
    match = re.search(r"(\d+)\+?\s*day", text)
    if match:
        return (today - timedelta(days=int(match.group(1)))).isoformat()
    match = re.search(r"(\d+)\+?\s*month", text)
    if match:
        return (today - timedelta(days=30 * int(match.group(1)))).isoformat()
    return None


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------


def board_url(kind: str, slug: str) -> str:
    """The public URL a human can open for this board."""
    if kind == "greenhouse":
        return GREENHOUSE_API.format(slug=slug)
    if kind == "lever":
        return LEVER_API.format(slug=slug)
    if kind == "ashby":
        return ASHBY_API.format(slug=slug)
    if kind == "workday":
        tenant, wd, site = split_workday_slug(slug)
        return WORKDAY_API.format(tenant=tenant, wd=wd, site=site)
    if kind == "smartrecruiters":
        return SMARTRECRUITERS_API.format(slug=slug)
    raise AtsError(f"Unknown ATS: {kind}")


def fetch_board(
    kind: str,
    slug: str,
    company: str,
    keywords: str | None = None,
    location: str | None = None,
    client: httpx.Client | None = None,
) -> list[dict]:
    """Fetch and normalise open roles from one company's board.

    Greenhouse, Lever and Ashby return the whole board and are filtered
    client-side; Workday and SmartRecruiters take a query, so keywords are
    pushed down to the API.
    """
    if kind == "workday":
        return _fetch_workday(slug, company, keywords, client)
    if kind == "smartrecruiters":
        return _fetch_smartrecruiters(slug, company, keywords, location, client)

    parser = {
        "greenhouse": parse_greenhouse,
        "lever": parse_lever,
        "ashby": parse_ashby,
    }.get(kind)
    if parser is None:
        raise AtsError(f"Unknown ATS: {kind}")
    return parser(_get_json(board_url(kind, slug), client=client), company)


def _fetch_workday(
    slug: str, company: str, keywords: str | None, client: httpx.Client | None
) -> list[dict]:
    url = board_url("workday", slug)
    jobs: list[dict] = []
    owned = client is None
    client = client or httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    try:
        for page in range(WORKDAY_MAX_PAGES):
            body = {
                "appliedFacets": {},
                "limit": WORKDAY_PAGE,
                "offset": page * WORKDAY_PAGE,
                "searchText": keywords or "",
            }
            try:
                response = client.post(url, json=body)
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPStatusError as exc:
                raise AtsError(f"{url} returned HTTP {exc.response.status_code}") from exc
            except httpx.HTTPError as exc:
                raise AtsError(f"{url} failed: {exc}") from exc
            except ValueError as exc:
                raise AtsError(f"{url} returned invalid JSON") from exc

            batch = parse_workday(payload, company, slug)
            jobs.extend(batch)
            if len(batch) < WORKDAY_PAGE:
                break
    finally:
        if owned:
            client.close()
    return jobs


def _fetch_smartrecruiters(
    slug: str,
    company: str,
    keywords: str | None,
    location: str | None,
    client: httpx.Client | None,
) -> list[dict]:
    params: dict[str, Any] = {"limit": 100}
    if keywords:
        params["q"] = keywords
    if location:
        params["location"] = location
    payload = _get_json(board_url("smartrecruiters", slug), params=params, client=client)
    return parse_smartrecruiters(payload, company, slug)


def fetch_adzuna(
    app_id: str,
    app_key: str,
    country: str = "us",
    company: str | None = None,
    keywords: str | None = None,
    location: str | None = None,
    limit: int = 25,
    client: httpx.Client | None = None,
) -> list[dict]:
    """Keyed fallback search for companies with no detectable board."""
    what = " ".join(part for part in [company, keywords] if part)
    params: dict[str, Any] = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": max(1, min(limit, 50)),
        "content-type": "application/json",
    }
    if what:
        params["what"] = what
    if company:
        params["company"] = company
    if location:
        params["where"] = location
    payload = _get_json(ADZUNA_API.format(country=country), params=params, client=client)
    return parse_adzuna(payload, company)


def _get_json(url: str, params: dict | None = None, client: httpx.Client | None = None) -> Any:
    owned = client is None
    client = client or httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise AtsError(f"{url} returned HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise AtsError(f"{url} failed: {exc}") from exc
    except ValueError as exc:
        raise AtsError(f"{url} returned invalid JSON") from exc
    finally:
        if owned:
            client.close()


def matches(job: dict, keywords: str | None, location: str | None) -> bool:
    """Client-side filter — most board APIs offer no query parameters."""
    if keywords:
        haystack = f"{job.get('title', '')} {job.get('location') or ''}".lower()
        if not all(term in haystack for term in keywords.lower().split()):
            return False
    if location:
        if location.lower() not in (job.get("location") or "").lower():
            return False
    return True
