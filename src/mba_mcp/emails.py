"""Guess a work email from the addresses you already have.

Most LinkedIn exports carry few email addresses, and finance contacts rarely
share one. But firms use a house pattern, so a handful of known addresses at a
domain reveal the rule for everyone else there.

Everything is derived from the user's own contact data — nothing is sent to any
enrichment service. Guesses are always returned labelled unverified, and the
send path still requires the human to approve the address.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Callable, Iterable

# Ordered by how common they are in professional services.
PATTERNS: dict[str, Callable[[str, str], str]] = {
    "first.last": lambda f, l: f"{f}.{l}",
    "firstlast": lambda f, l: f"{f}{l}",
    "f.last": lambda f, l: f"{f[0]}.{l}",
    "flast": lambda f, l: f"{f[0]}{l}",
    "first_last": lambda f, l: f"{f}_{l}",
    "first-last": lambda f, l: f"{f}-{l}",
    "last.first": lambda f, l: f"{l}.{f}",
    "lastf": lambda f, l: f"{l}{f[0]}",
    "firstl": lambda f, l: f"{f}{l[0]}",
    "first": lambda f, l: f,
}

# Personal-mail domains tell us nothing about a firm's convention.
CONSUMER_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "icloud.com", "me.com", "aol.com", "protonmail.com", "proton.me", "live.com",
    "msn.com", "gmx.com", "mail.com", "yandex.com", "qq.com", "163.com",
}

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "phd", "mba", "cfa", "cpa"}


def split_name(full_name: str) -> tuple[str, str] | None:
    """Reduce a display name to lowercase ASCII ``(first, last)``."""
    if not full_name:
        return None
    cleaned = unicodedata.normalize("NFKD", full_name)
    cleaned = cleaned.encode("ascii", "ignore").decode("ascii").lower()
    # Apostrophes never survive into an email local part (O'Brien -> obrien);
    # hyphens routinely do (mary-kate.obrien@).
    cleaned = cleaned.replace("'", "")
    cleaned = re.sub(r"[^a-z\s-]", " ", cleaned)
    parts = [p.strip("-") for p in cleaned.split() if p.strip("-") not in _SUFFIXES]
    parts = [p for p in parts if p]
    if len(parts) < 2:
        return None
    return parts[0], parts[-1]


def email_domain(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1].strip().lower()
    return domain if domain and domain not in CONSUMER_DOMAINS else None


def identify_pattern(full_name: str, email: str) -> str | None:
    """Which house pattern does this known address follow?"""
    name = split_name(full_name)
    if not name or "@" not in email:
        return None
    local = email.split("@", 1)[0].strip().lower()
    first, last = name
    for key, build in PATTERNS.items():
        if build(first, last) == local:
            return key
    return None


def learn_patterns(contacts: Iterable[dict]) -> dict[str, Counter]:
    """Map each work domain to the patterns observed on it."""
    learned: dict[str, Counter] = {}
    for contact in contacts:
        domain = email_domain(contact.get("email"))
        if not domain:
            continue
        pattern = identify_pattern(contact.get("full_name") or "", contact["email"])
        if pattern:
            learned.setdefault(domain, Counter())[pattern] += 1
    return learned


def domains_for_company(contacts: Iterable[dict], company: str) -> Counter:
    """Work domains seen on colleagues at the same company."""
    from .connections import normalise_company

    target = normalise_company(company)
    domains: Counter = Counter()
    if not target:
        return domains
    for contact in contacts:
        if normalise_company(contact.get("company")) != target:
            continue
        domain = email_domain(contact.get("email"))
        if domain:
            domains[domain] += 1
    return domains


def suggest_addresses(
    contact: dict,
    known_contacts: Iterable[dict],
    limit: int = 3,
) -> list[dict]:
    """Rank likely addresses for one contact, with the evidence behind each.

    Every suggestion is a guess. Confidence reflects how much of the firm's
    convention we have actually observed:

    * ``high``   - two or more colleagues share this pattern on this domain
    * ``medium`` - one colleague's address establishes the pattern
    * ``low``    - the domain is known but no pattern is; the house default
    """
    known = list(known_contacts)
    name = split_name(contact.get("full_name") or "")
    if not name:
        return []
    first, last = name

    company = contact.get("company") or ""
    domains = domains_for_company(known, company)
    if not domains:
        return []
    domain, domain_samples = domains.most_common(1)[0]

    learned = learn_patterns(known).get(domain, Counter())
    suggestions: list[dict] = []

    for pattern, count in learned.most_common():
        suggestions.append(
            {
                "email": f"{PATTERNS[pattern](first, last)}@{domain}",
                "pattern": pattern,
                "confidence": "high" if count >= 2 else "medium",
                "basis": f"{count} known address{'es' if count > 1 else ''} at {domain} "
                f"use{'' if count > 1 else 's'} {pattern}",
                "verified": False,
            }
        )

    if not suggestions:
        suggestions.append(
            {
                "email": f"{PATTERNS['first.last'](first, last)}@{domain}",
                "pattern": "first.last",
                "confidence": "low",
                "basis": f"{domain} seen on {domain_samples} colleague"
                f"{'s' if domain_samples > 1 else ''}, but no pattern learned yet — "
                "first.last is the most common convention",
                "verified": False,
            }
        )

    return suggestions[:limit]
