"""LinkedIn CSV import and warm-path ranking.

There is no LinkedIn API and we do not scrape. The user exports their own
connections from LinkedIn settings and hands us the file; everything here works
off that export plus whatever interactions they log.
"""

from __future__ import annotations

import csv
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

HEADER_MARKERS = ("first name", "firstname")

# Legal and filler tokens carry no signal when matching one company to another.
COMPANY_NOISE = {
    "inc", "inc.", "llc", "l.l.c", "ltd", "ltd.", "limited", "corp", "corp.",
    "corporation", "co", "co.", "company", "plc", "gmbh", "sa", "sas", "nv",
    "bv", "ag", "holdings", "holding", "group", "the", "and", "&",
}

# Words that are common to half of finance and consulting. They are kept during
# normalisation (Bain Capital and Bain & Company are different firms and must
# not collapse into each other) but they cannot carry a match on their own —
# otherwise AQR Capital Management "matches" Bain Capital on the word capital.
GENERIC_TOKENS = {
    "capital", "partners", "partner", "management", "advisors", "advisory",
    "associates", "ventures", "securities", "bank", "banking", "financial",
    "finance", "global", "international", "consulting", "consultants",
    "solutions", "services", "asset", "investments", "investment", "equity",
}

# Title signals. Juniors answer cold notes; seniors carry weight when they do.
JUNIOR_TITLES = (
    "analyst", "associate", "consultant", "intern", "summer", "graduate",
    "avp", "senior associate",
)
SENIOR_TITLES = (
    "partner", "principal", "director", "vice president", "vp", "managing",
    "head of", "chief", "founder",
)

MAX_SCORE = 100
MIN_SCORE = 40


class ImportError_(ValueError):
    """The file the user pointed at is not a LinkedIn connections export."""


# --------------------------------------------------------------------------
# CSV import
# --------------------------------------------------------------------------


def parse_connections_csv(path: str | Path) -> list[dict]:
    """Parse a LinkedIn ``Connections.csv`` export into contact dicts.

    LinkedIn prefixes the real header with a few ``Notes:`` lines, so we scan
    for the header row rather than assuming line one.
    """
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise ImportError_(f"No such file: {file_path}")

    text = file_path.read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if any(marker in line.lower() for marker in HEADER_MARKERS)
        ),
        None,
    )
    if header_index is None:
        raise ImportError_(
            f"{file_path} has no 'First Name' header row — is it a LinkedIn "
            "connections export?"
        )

    reader = csv.DictReader(lines[header_index:])
    contacts: list[dict] = []
    for row in reader:
        contact = _row_to_contact(row)
        if contact:
            contacts.append(contact)
    return contacts


def _row_to_contact(row: dict) -> dict | None:
    field = {(key or "").strip().lower(): (value or "").strip() for key, value in row.items()}
    first = field.get("first name") or field.get("firstname") or ""
    last = field.get("last name") or field.get("lastname") or ""
    full_name = " ".join(part for part in (first, last) if part).strip()
    if not full_name:
        return None
    return {
        "full_name": full_name,
        "company": field.get("company") or None,
        "title": field.get("position") or field.get("title") or None,
        "email": field.get("email address") or field.get("email") or None,
        "linkedin_url": field.get("url") or field.get("profile url") or None,
        # LinkedIn's export has no school column, but school alumni exports do
        # and users often add one by hand.
        "school": _first(field, "school", "university", "education", "alma mater"),
        "grad_year": _parse_year(
            _first(field, "grad year", "graduation year", "class year", "class of", "year")
        ),
        "connected_on": _parse_connected_on(field.get("connected on")),
        "source": "linkedin_csv",
    }


def _first(field: dict, *keys: str) -> str | None:
    for key in keys:
        value = field.get(key)
        if value:
            return value
    return None


def _parse_year(value: str | None) -> int | None:
    """Pull a graduation year out of '2027', 'Class of 2027' or 'MBA 2027'."""
    if not value:
        return None
    match = re.search(r"(19|20)\d{2}", str(value))
    return int(match.group(0)) if match else None


def _parse_connected_on(value: str | None) -> str | None:
    if not value:
        return None
    for fmt in ("%d %b %Y", "%d %B %Y", "%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------
# Warm-path ranking
# --------------------------------------------------------------------------


def normalise_company(name: str | None) -> str:
    if not name:
        return ""
    cleaned = re.sub(r"[^\w\s&]", " ", name.lower())
    tokens = [t for t in cleaned.split() if t not in COMPANY_NOISE]
    return " ".join(tokens)


def company_tokens(name: str | None) -> set[str]:
    return {token for token in normalise_company(name).split() if len(token) > 1}


def company_affinity(contact_company: str | None, target: str) -> tuple[int, str] | None:
    """Score how close a contact's employer is to the target company."""
    left, right = normalise_company(contact_company), normalise_company(target)
    if not left or not right:
        return None
    if left == right:
        return 70, f"works at {contact_company}"

    left_tokens, right_tokens = company_tokens(contact_company), company_tokens(target)
    if not left_tokens or not right_tokens:
        return None
    if left_tokens <= right_tokens or right_tokens <= left_tokens:
        return 55, f"at {contact_company} (name matches {target})"

    shared = (left_tokens & right_tokens) - GENERIC_TOKENS
    if shared:
        return 40, f"at {contact_company} (shares '{' '.join(sorted(shared))}' with {target})"
    return None


def score_contact(
    contact: dict,
    company: str,
    school: str | None = None,
    interaction_count: int = 0,
    last_interaction: str | None = None,
    today: date | None = None,
    graduation_year: int | None = None,
) -> tuple[int, list[str]]:
    """Rank one contact against a target company.

    Returns ``(score, reasons)``. Reasons are surfaced to the assistant so it
    can explain *why* a path is warm when it drafts outreach.
    """
    today = today or date.today()
    score = 0
    reasons: list[str] = []

    affinity = company_affinity(contact.get("company"), company)
    if affinity:
        points, reason = affinity
        score += points
        reasons.append(reason)

    if school and contact.get("school"):
        if normalise_company(contact["school"]) == normalise_company(school):
            score += 20
            reasons.append(f"alum of {contact['school']}")

    if school and contact.get("grad_year") and graduation_year:
        gap = abs(int(contact["grad_year"]) - int(graduation_year))
        if gap <= 3 and any("alum" in reason for reason in reasons):
            score += 10
            reasons.append(f"class of {contact['grad_year']} — overlapped with you")

    title = (contact.get("title") or "").lower()
    if any(word in title for word in ("recruit", "talent", "campus", "university")):
        score += 10
        reasons.append("recruiting-side role")
    elif any(word in title for word in JUNIOR_TITLES):
        # Juniors reply more often, know the current process, and can refer.
        score += 8
        reasons.append("junior enough to reply")
    elif any(word in title for word in SENIOR_TITLES):
        score += 5
        reasons.append("senior enough to refer")

    years_out = _years_out(contact.get("grad_year"), today)
    if years_out is not None and years_out <= 5:
        score += 5
        reasons.append(f"recent grad ({contact['grad_year']})")

    if interaction_count:
        score += min(10, 5 * interaction_count)
        reasons.append(
            f"{interaction_count} logged interaction{'s' if interaction_count > 1 else ''}"
        )

    if contact.get("email"):
        score += 5
        reasons.append("email on file")

    years = _years_since(contact.get("connected_on"), today)
    if years is not None and years <= 2:
        score += 5
        reasons.append("connected recently")

    if last_interaction:
        reasons.append(f"last contact {last_interaction}")

    return min(score, MAX_SCORE), reasons


def rank_contacts(
    contacts: Iterable[dict],
    company: str,
    school: str | None = None,
    interactions: dict[int, dict] | None = None,
    min_score: int = MIN_SCORE,
    today: date | None = None,
    graduation_year: int | None = None,
) -> list[dict]:
    """Rank stored contacts against a target company, closest first."""
    interactions = interactions or {}
    ranked: list[dict] = []
    for contact in contacts:
        history: dict[str, Any] = interactions.get(contact.get("id"), {}) or {}
        score, reasons = score_contact(
            contact,
            company,
            school=school,
            interaction_count=history.get("count", 0),
            last_interaction=history.get("last_occurred_at"),
            today=today,
            graduation_year=graduation_year,
        )
        if score >= min_score:
            ranked.append(
                {
                    "contact": contact,
                    "score": score,
                    "reasons": reasons,
                    "interaction_count": history.get("count", 0),
                    "last_interaction": history.get("last_occurred_at"),
                }
            )
    ranked.sort(key=lambda item: (-item["score"], item["contact"].get("full_name", "")))
    return ranked


def _years_out(grad_year: int | None, today: date) -> int | None:
    if not grad_year:
        return None
    try:
        return today.year - int(grad_year)
    except (TypeError, ValueError):
        return None


def _years_since(iso_date: str | None, today: date) -> float | None:
    if not iso_date:
        return None
    try:
        then = date.fromisoformat(iso_date)
    except ValueError:
        return None
    return (today - then).days / 365.25
