"""FastMCP server — the campaign layer for MBA recruiting.

Tools are data, actions and state. Every piece of language work (tailoring a
CV, drafting an email, prepping a case) belongs to the calling assistant, which
is why nothing here needs a model key.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any

from fastmcp import FastMCP

from . import ats, connections, emails, gmail, linkedin, presets, store, timeline
from .config import Config, get_config
from .db import session, today_iso
from .models import (
    Application,
    ResumeNote,
    Contact,
    EmailSuggestion,
    Followup,
    Interaction,
    Job,
    OutreachDraft,
    Profile,
    Target,
    Timeline,
    WarmPath,
)

INSTRUCTIONS = """
You are this person's recruiting coach. They are a business-school student in
the middle of a recruiting cycle, they are almost certainly overwhelmed, and
they are not technical. Talk like a coach who knows them, not like a database.

How to be useful:
- Open by reading what you already know: the profile, resume, pipeline,
  contacts and timeline resources. Never make them repeat themselves.
- Lead with the two or three things that matter this week. A wall of
  everything that is due is the same as saying nothing.
- Be specific and concrete. "Priya's follow-up is four days overdue and PJT
  closes Friday" beats "you have some outstanding items".
- Ask for one thing at a time. If the profile is empty, get their school and
  what they did before the MBA in conversation, then save it quietly with
  set_profile.
- When they mention something new — a case competition win, a chat that went
  well, a firm they have gone off — write it down with add_resume_note or
  log_interaction. They will not do it themselves.
- Never mention tool names, file paths, or JSON to them.

House rules this server enforces, which you should respect:
- Never auto-submit an application. Draft and track; the human submits.
- Contacts come only from the user's own LinkedIn export. Never scrape
  LinkedIn: find_alumni hands them search links to open themselves.
- Emails from suggest_email are unverified guesses. Show the address and get
  it confirmed before it is used.
- Timeline dates are a curated template, not live firm deadlines. Say so when
  it matters, and tell them to confirm with their career centre.
- If sending email is configured, send_email sends exactly one message and
  only with confirm=True, after they have read the text and said yes.
"""

mcp = FastMCP(name="mba-mcp", instructions=INSTRUCTIONS)


def _config() -> Config:
    config = get_config()
    config.ensure_data_dir()
    return config


def _who(conn, config: Config) -> tuple[str | None, int | None]:
    """The user's school and graduation year: stored profile first, env second."""
    profile = store.get_profile(conn)
    return profile.get("school") or config.school, profile.get("graduation_year")


# --------------------------------------------------------------------------
# Phase 1 — targets & discovery
# --------------------------------------------------------------------------


@mcp.tool
def add_target_company(
    name: str,
    ats_url: str | None = None,
    priority: int = 2,
) -> dict:
    """Add a company to the target list.

    Paste the company's careers or job-board URL as ats_url and the board is
    resolved automatically (Greenhouse, Lever or Ashby). Without one, job
    search for this company falls back to Adzuna if it is configured.

    Args:
        name: Company name as you'd say it, e.g. "Bain & Company".
        ats_url: Careers/job-board URL, e.g. https://boards.greenhouse.io/acme
        priority: 1 = dream firm, 2 = core target, 3 = stretch/backup.
    """
    config = _config()
    detected = ats.detect_ats(ats_url) if ats_url else None
    discovered = False
    if ats_url and not detected:
        # Not a board URL — read the careers page and look for the board on it.
        detected = ats.discover_ats(ats_url)
        discovered = bool(detected)
    with session(config.db_path) as conn:
        row = store.upsert_target(
            conn,
            name=name,
            ats_kind=detected[0] if detected else None,
            ats_slug=detected[1] if detected else None,
            ats_url=ats_url,
            priority=priority,
        )
    result = Target(**row).model_dump()
    if discovered:
        result["note"] = (
            f"That careers page is powered by {detected[0]} — resolved its board "
            "automatically, so find_jobs will read live roles."
        )
    elif ats_url and not detected:
        result["note"] = (
            "Saved, but no job board found on that page. Many firms load "
            "listings with JavaScript or run their own system, which nothing "
            "can read directly. find_jobs will fall back to Adzuna if keys are "
            "configured; otherwise check the careers page by hand, or paste the "
            "board URL if you can find one (Greenhouse, Lever, Ashby, Workday "
            "and SmartRecruiters are all supported)."
        )
    elif not ats_url:
        result["note"] = (
            "No ATS URL given — add one later with add_target_company to enable "
            "direct board search."
        )
    return result


@mcp.tool
def list_targets() -> list[dict]:
    """List every target company, highest priority first."""
    config = _config()
    with session(config.db_path) as conn:
        return [Target(**row).model_dump() for row in store.list_targets(conn)]


@mcp.tool
def find_jobs(
    company: str | None = None,
    keywords: str | None = None,
    location: str | None = None,
    limit: int = 50,
) -> dict:
    """Find open roles on target companies' job boards.

    Args:
        company: One target company; omit to sweep every target.
        keywords: All words must appear in the title or location, e.g.
            "summer associate".
        location: Substring match on the posting's location, e.g. "London".
        limit: Maximum roles to return across all companies.
    """
    config = _config()
    with session(config.db_path) as conn:
        if company:
            target = store.get_target_by_name(conn, company)
            targets = [target] if target else [{"name": company, "ats_kind": None, "ats_slug": None}]
        else:
            targets = store.list_targets(conn)

    if not targets:
        return {
            "jobs": [],
            "checked": [],
            "errors": [],
            "note": "No target companies yet — add one with add_target_company.",
        }

    jobs: list[dict] = []
    checked: list[dict] = []
    errors: list[dict] = []

    for target in targets:
        name = target["name"]
        found: list[dict] = []
        try:
            if target.get("ats_kind") and target.get("ats_slug"):
                found = ats.fetch_board(
                    target["ats_kind"],
                    target["ats_slug"],
                    name,
                    keywords=keywords,
                    location=location,
                )
                source = target["ats_kind"]
            elif config.adzuna_enabled:
                found = ats.fetch_adzuna(
                    config.adzuna_app_id,
                    config.adzuna_app_key,
                    country=config.adzuna_country,
                    company=name,
                    keywords=keywords,
                    location=location,
                )
                source = "adzuna"
            else:
                errors.append(
                    {
                        "company": name,
                        "error": "No ATS URL on this target and no Adzuna keys "
                        "configured. Re-add it with its job-board URL.",
                    }
                )
                continue
        except ats.AtsError as exc:
            errors.append({"company": name, "error": str(exc)})
            continue

        matched = [job for job in found if ats.matches(job, keywords, location)]
        checked.append({"company": name, "source": source, "open_roles": len(found), "matched": len(matched)})
        jobs.extend(matched)

    jobs.sort(key=lambda job: (job.get("posted_at") or "", job.get("company", "")), reverse=True)
    return {
        "jobs": [Job(**job).model_dump() for job in jobs[:limit]],
        "total_matched": len(jobs),
        "checked": checked,
        "errors": errors,
    }


# --------------------------------------------------------------------------
# Phase 2 — pipeline & timeline
# --------------------------------------------------------------------------


@mcp.tool
def track_application(
    company: str,
    role: str,
    url: str | None = None,
    status: str = "interested",
    deadline: str | None = None,
    notes: str | None = None,
    jd_text: str | None = None,
) -> dict:
    """Add a role to the application pipeline.

    This tracks an application; it never submits one.

    Pass jd_text when the user has the posting to hand — storing it means you
    can tailor their CV against the real requirements later instead of guessing
    at what the firm asked for.

    Args:
        company: Firm name.
        role: Role title as posted.
        url: Posting or portal URL.
        status: interested | applied | interview | offer | rejected.
        deadline: ISO date (YYYY-MM-DD) the application is due.
        notes: Anything you want to remember about this one.
        jd_text: The job description, pasted in full.
    """
    config = _config()
    with session(config.db_path) as conn:
        row = store.add_application(
            conn, company=company, role=role, url=url, status=status,
            deadline=deadline, notes=notes, jd_text=jd_text,
        )
    return Application(**row).model_dump()


@mcp.tool
def update_application(
    id: int,
    status: str | None = None,
    deadline: str | None = None,
    notes: str | None = None,
) -> dict:
    """Move an application along the pipeline or revise its deadline/notes.

    Args:
        id: Application id from list_applications.
        status: interested | applied | interview | offer | rejected.
        deadline: ISO date (YYYY-MM-DD).
        notes: Replaces the stored notes.
    """
    config = _config()
    with session(config.db_path) as conn:
        row = store.update_application(
            conn, id, status=status, deadline=deadline, notes=notes
        )
    return Application(**row).model_dump()


@mcp.tool
def list_applications(status: str | None = None) -> dict:
    """The pipeline, soonest deadline first, with a count per status.

    Args:
        status: Optional filter — interested | applied | interview | offer | rejected.
    """
    config = _config()
    with session(config.db_path) as conn:
        rows = store.list_applications(conn, status=status)
        counts: dict[str, int] = {}
        for row in store.list_applications(conn):
            counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {
        "applications": [Application(**row).model_dump() for row in rows],
        "counts_by_status": counts,
        "today": today_iso(),
    }


@mcp.tool
def get_recruiting_timeline(track: str = "consulting") -> dict:
    """Key dates for a recruiting track, projected onto the current cycle.

    Dates are a curated template of a typical calendar, not live firm
    deadlines — tell the user to confirm against their career centre.

    Args:
        track: Recruiting track, e.g. "consulting".
    """
    config = _config()
    try:
        rendered = timeline.get_timeline(track, overrides_dir=config.timeline_overrides_dir)
    except timeline.UnknownTrack as exc:
        return {"error": str(exc), "available_tracks": timeline.available_tracks(config.timeline_overrides_dir)}
    return Timeline(**rendered).model_dump()


# --------------------------------------------------------------------------
# Phase 3 — networking
# --------------------------------------------------------------------------


@mcp.tool
def import_connections(csv_path: str) -> dict:
    """Import the user's own LinkedIn connections export (Connections.csv).

    Re-running is safe: contacts are matched on name plus company and updated
    in place.

    Args:
        csv_path: Path to the CSV downloaded from LinkedIn's data export.
    """
    config = _config()
    try:
        parsed = connections.parse_connections_csv(csv_path)
    except connections.ImportError_ as exc:
        return {"error": str(exc)}

    with session(config.db_path) as conn:
        result = store.upsert_contacts(conn, parsed)
        result["total_contacts"] = store.count_contacts(conn)
    result["parsed_rows"] = len(parsed)
    if not any(contact.get("email") for contact in parsed):
        result["note"] = (
            "No email addresses in this export — LinkedIn only includes them "
            "for connections who share them. Outreach drafts will need an "
            "address supplied by hand."
        )
    return result


@mcp.tool
def find_warm_paths(company: str, limit: int = 10) -> dict:
    """Rank stored contacts by how warm a path they are into a company.

    Scoring is transparent: each result carries the reasons behind its score
    (same employer, alum of your school, recruiting-side role, prior
    interactions, recency of the connection).

    Args:
        company: Target company name.
        limit: Maximum contacts to return.
    """
    config = _config()
    with session(config.db_path) as conn:
        contacts = store.list_contacts(conn)
        history = store.interaction_summary(conn)
        school, graduation_year = _who(conn, config)
        total = len(contacts)

    ranked = connections.rank_contacts(
        contacts,
        company,
        school=school,
        interactions=history,
        graduation_year=graduation_year,
    )
    paths = [
        WarmPath(
            contact=Contact(**item["contact"]),
            score=item["score"],
            reasons=item["reasons"],
            interaction_count=item["interaction_count"],
            last_interaction=item["last_interaction"],
        ).model_dump()
        for item in ranked[:limit]
    ]
    result: dict[str, Any] = {
        "company": company,
        "paths": paths,
        "total_matches": len(ranked),
        "contacts_searched": total,
    }
    if total == 0:
        result["note"] = "No contacts imported yet — run import_connections first."
    elif not ranked:
        result["note"] = (
            f"No stored contact is close to {company}. Cold outreach to an "
            "alum found through your school's directory is the next best move."
        )
    if not school:
        result["hint"] = (
            "Tell me your business school with set_profile and alumni get ranked "
            "above strangers."
        )
    return result


@mcp.tool
def log_interaction(
    contact_id: int,
    kind: str,
    notes: str | None = None,
    next_followup: str | None = None,
    occurred_at: str | None = None,
) -> dict:
    """Log a touchpoint with a contact and set when to circle back.

    Args:
        contact_id: Contact id from find_warm_paths.
        kind: coffee_chat | call | email | event | referral | intro | note.
        notes: What was said, what they care about, what you promised.
        next_followup: ISO date to resurface this contact (YYYY-MM-DD).
        occurred_at: ISO date it happened; defaults to today.
    """
    config = _config()
    with session(config.db_path) as conn:
        try:
            row = store.add_interaction(
                conn, contact_id, kind, notes=notes,
                next_followup=next_followup, occurred_at=occurred_at,
            )
        except store.NotFound as exc:
            return {"error": str(exc)}
        contact = store.get_contact(conn, contact_id)
    result = Interaction(**row).model_dump()
    result["contact"] = Contact(**contact).model_dump()
    if not next_followup:
        result["hint"] = (
            "No follow-up date set — this contact will not resurface in "
            "get_followups."
        )
    return result


@mcp.tool
def get_followups(within_days: int = 0) -> dict:
    """Contacts owed a follow-up, most overdue first.

    Args:
        within_days: Also include follow-ups due this many days ahead.
    """
    config = _config()
    today = date.today()
    horizon = (today + timedelta(days=max(0, within_days))).isoformat()
    with session(config.db_path) as conn:
        rows = store.due_followups(conn, horizon)

    followups = [
        Followup(
            contact=Contact(**row),
            due_on=row["due_on"],
            days_overdue=(today - date.fromisoformat(row["due_on"])).days,
            last_kind=row.get("last_kind"),
            last_notes=row.get("last_notes"),
            interaction_id=row["interaction_id"],
        ).model_dump()
        for row in rows
    ]
    return {"today": today.isoformat(), "due": followups, "count": len(followups)}


# --------------------------------------------------------------------------
# Phase 4 — outreach
# --------------------------------------------------------------------------


@mcp.tool
def save_outreach_draft(
    contact_id: int,
    subject: str,
    body: str,
    to_email: str | None = None,
) -> dict:
    """Store an outreach email you have written for a contact.

    Nothing is sent here. Show the draft to the user, revise it with them, then
    call send_email with confirm=True once they approve.

    Args:
        contact_id: Contact id from find_warm_paths.
        subject: Subject line.
        body: Plain-text body.
        to_email: Recipient, if the contact has no email on file.
    """
    config = _config()
    with session(config.db_path) as conn:
        try:
            row = store.save_draft(conn, contact_id, subject, body, to_email=to_email)
        except store.NotFound as exc:
            return {"error": str(exc)}
    result = OutreachDraft(**row).model_dump()
    if not row.get("to_email"):
        result["note"] = (
            "No email address for this contact. Pass to_email when you send, "
            "or the send will be refused."
        )
    result["next_step"] = (
        "Show this to the user verbatim. Send only after they say yes, with "
        f"send_email(draft_id={row['id']}, confirm=True)."
    )
    return result


@mcp.tool
def send_email(draft_id: int, confirm: bool = False, to_email: str | None = None) -> dict:
    """Send exactly one saved draft from the user's own Gmail account.

    Requires confirm=True, which stands for an explicit human yes to this
    specific message. One call sends one email; never loop this tool over a
    list of contacts.

    Args:
        draft_id: Draft id from save_outreach_draft.
        confirm: Must be True, and only after the user has approved the text.
        to_email: Override or supply the recipient address.
    """
    config = _config()
    with session(config.db_path) as conn:
        try:
            draft = store.get_draft(conn, draft_id)
        except store.NotFound as exc:
            return {"error": str(exc)}

        if draft["status"] == "sent":
            return {
                "error": f"Draft {draft_id} was already sent at {draft['sent_at']}.",
                "gmail_message_id": draft["gmail_message_id"],
            }

        recipient = (to_email or draft["to_email"] or "").strip()
        if not gmail.valid_recipient(recipient):
            return {
                "error": "A single valid recipient address is required. Pass "
                "to_email, or store one on the contact.",
                "draft": OutreachDraft(**draft).model_dump(),
            }

        if not confirm:
            return {
                "status": "confirmation_required",
                "message": "Nothing sent. Show this to the user and call again "
                "with confirm=True only if they approve.",
                "to": recipient,
                "subject": draft["subject"],
                "body": draft["body"],
            }

        try:
            message_id = gmail.send_one(config, recipient, draft["subject"], draft["body"])
        except gmail.GmailNotConfigured as exc:
            return {"error": str(exc)}

        sent = store.mark_draft_sent(conn, draft_id, message_id)

    result = OutreachDraft(**sent).model_dump()
    result["status_message"] = f"Sent one message to {recipient}."
    return result



# --------------------------------------------------------------------------
# Profile — who the user is
# --------------------------------------------------------------------------


@mcp.tool
def set_profile(
    school: str | None = None,
    graduation_year: int | None = None,
    track: str | None = None,
    full_name: str | None = None,
    email: str | None = None,
    target_locations: str | None = None,
    background: str | None = None,
    goals: str | None = None,
    hard_constraints: str | None = None,
) -> dict:
    """Save who the user is. Ask for this once, at the start.

    School and graduation year make alumni outreach work. Background, goals and
    constraints are what let you judge fit properly instead of guessing — fill
    them in from what the user tells you in conversation, not by interrogating
    them. Only the fields you pass are changed.

    Args:
        school: Business school, e.g. "Wharton" or "London Business School".
        graduation_year: Expected graduation year, e.g. 2028.
        track: consulting | investment_banking (aliases: finance, banking, MBB).
        full_name: The user's name, used when drafting outreach.
        email: The user's own email address.
        target_locations: Preferred cities, e.g. "New York, London".
        background: What they did before the MBA, in their own words.
        goals: What they actually want out of recruiting, including the honest version.
        hard_constraints: Visa status, geography, family, anything non-negotiable.
    """
    config = _config()
    with session(config.db_path) as conn:
        row = store.set_profile(
            conn,
            school=school,
            graduation_year=graduation_year,
            track=timeline.resolve_track(track) if track else None,
            full_name=full_name,
            email=email,
            target_locations=target_locations,
            background=background,
            goals=goals,
            hard_constraints=hard_constraints,
        )
    result = Profile(**row).model_dump()
    missing = [field for field in ("school", "graduation_year") if not row.get(field)]
    if missing:
        result["hint"] = f"Still missing: {', '.join(missing)} — alumni ranking needs them."
    else:
        result["next_step"] = (
            "Try add_target_pack to seed a target list, then find_alumni to build "
            "LinkedIn searches for your school at those firms."
        )
    return result


# --------------------------------------------------------------------------
# Starter packs — install to first target list in one step
# --------------------------------------------------------------------------


@mcp.tool
def list_target_packs() -> dict:
    """Curated starter lists of firms, one per track."""
    config = _config()
    return {"packs": presets.describe_packs(config.data_dir / "presets")}


@mcp.tool
def add_target_pack(pack: str, resolve: bool = True, priority_max: int = 3) -> dict:
    """Add a whole track's worth of target firms at once.

    Each firm's job board is resolved from its careers page as it is added, so
    find_jobs works immediately for the firms that have a readable board.

    Args:
        pack: consulting | investment_banking (aliases: finance, banking, MBB).
        resolve: Look up each firm's board from its careers page. Off is faster.
        priority_max: 1 adds only the top-tier firms, 3 adds everything.
    """
    config = _config()
    overrides = config.data_dir / "presets"
    try:
        data = presets.load_pack(pack, overrides_dir=overrides)
    except presets.UnknownPack as exc:
        return {"error": str(exc), "available_packs": presets.available_packs(overrides)}

    companies = [
        entry
        for entry in data.get("companies", [])
        if int(entry.get("priority", 2)) <= priority_max
    ]

    def resolve_one(entry: dict) -> tuple[dict, tuple[str, str] | None, bool]:
        if entry.get("ats") and entry.get("slug"):
            return entry, (entry["ats"], entry["slug"]), False
        url = entry.get("careers_url")
        if resolve and url:
            return entry, ats.discover_ats(url), True
        return entry, None, False

    with ThreadPoolExecutor(max_workers=8) as pool:
        resolved = list(pool.map(resolve_one, companies))

    added, unresolved = [], []
    with session(config.db_path) as conn:
        for entry, board, was_discovered in resolved:
            row = store.upsert_target(
                conn,
                name=entry["name"],
                ats_kind=board[0] if board else None,
                ats_slug=board[1] if board else None,
                ats_url=entry.get("careers_url"),
                priority=int(entry.get("priority", 2)),
            )
            record = {"name": row["name"], "id": row["id"], "board": row["ats_kind"]}
            if board:
                record["discovered"] = was_discovered
                added.append(record)
            else:
                unresolved.append(
                    {"name": row["name"], "careers_url": entry.get("careers_url")}
                )

    return {
        "pack": data.get("pack", pack),
        "label": data.get("label", ""),
        "note": data.get("note", ""),
        "added": added,
        "no_readable_board": unresolved,
        "summary": (
            f"{len(added) + len(unresolved)} firms on the target list; "
            f"{len(added)} have a live job board. The rest run their own careers "
            "site — track those by hand with track_application."
        ),
    }


# --------------------------------------------------------------------------
# Alumni — LinkedIn searches the user runs themselves
# --------------------------------------------------------------------------


@mcp.tool
def find_alumni(
    company: str | None = None,
    keywords: str | None = None,
    graduated_within_years: int = 5,
    limit: int = 10,
) -> dict:
    """Find people from the user's school to reach out to, at a target firm.

    Returns two things: alumni already in their imported contacts, and ready-made
    LinkedIn searches for the ones they have not met yet. This server never
    reads LinkedIn — the user opens the search links themselves, connects as a
    human, and re-imports their export to turn new connections into warm paths.

    Args:
        company: Target firm. Omit for a school-wide search.
        keywords: Extra filter, e.g. "investment banking" or "Associate".
        graduated_within_years: How recent a grad to look for. Recent grads reply most.
        limit: Maximum known contacts to return.
    """
    config = _config()
    with session(config.db_path) as conn:
        school, graduation_year = _who(conn, config)
        contacts = store.list_contacts(conn)
        history = store.interaction_summary(conn)

    known: list[dict] = []
    if school:
        target_school = connections.normalise_company(school)
        alumni = [
            contact
            for contact in contacts
            if connections.normalise_company(contact.get("school")) == target_school
        ]
        if company:
            ranked = connections.rank_contacts(
                alumni,
                company,
                school=school,
                interactions=history,
                graduation_year=graduation_year,
                min_score=0,
            )
            known = [
                WarmPath(
                    contact=Contact(**item["contact"]),
                    score=item["score"],
                    reasons=item["reasons"],
                    interaction_count=item["interaction_count"],
                    last_interaction=item["last_interaction"],
                ).model_dump()
                for item in ranked[:limit]
            ]
        else:
            known = [Contact(**contact).model_dump() for contact in alumni[:limit]]

    result: dict[str, Any] = {
        "school": school,
        "company": company,
        "known_alumni": known,
        "linkedin_searches": linkedin.search_links(
            company=company,
            school=school,
            keywords=keywords,
            location=None,
            graduated_within_years=graduated_within_years,
        ),
        "how_this_works": (
            "Open the searches yourself while signed in to LinkedIn. Connect with "
            "a short note, then re-export your connections and run "
            "import_connections — new connections become ranked warm paths."
        ),
    }
    if not school:
        result["hint"] = (
            "No school on file, so alumni searches can't be built. Run "
            "set_profile(school=...) first."
        )
    elif not known and not contacts:
        result["hint"] = (
            "No contacts imported yet. import_connections turns your LinkedIn "
            "export into warm paths."
        )
    elif not known:
        result["hint"] = (
            "None of your imported contacts list a school. LinkedIn's export "
            "has no school column — add one to the CSV, or rely on the searches below."
        )
    return result


# --------------------------------------------------------------------------
# Email inference
# --------------------------------------------------------------------------


@mcp.tool
def suggest_email(contact_id: int) -> dict:
    """Work out a contact's likely work email from addresses already on file.

    Learns each firm's convention from colleagues whose addresses you already
    have. Every result is an unverified guess — show it to the user, let them
    sanity-check it, and expect a bounce sometimes.

    Args:
        contact_id: Contact id from find_warm_paths or find_alumni.
    """
    config = _config()
    with session(config.db_path) as conn:
        try:
            contact = store.get_contact(conn, contact_id)
        except store.NotFound as exc:
            return {"error": str(exc)}
        everyone = store.list_contacts(conn)

    if contact.get("email"):
        return {
            "contact": Contact(**contact).model_dump(),
            "email": contact["email"],
            "suggestions": [],
            "note": "This contact already has a known address; no guessing needed.",
        }

    suggestions = emails.suggest_addresses(contact, everyone)
    result: dict[str, Any] = {
        "contact": Contact(**contact).model_dump(),
        "suggestions": [EmailSuggestion(**item).model_dump() for item in suggestions],
        "warning": "Unverified guesses derived from your own contacts. Confirm with "
        "the user before sending, and never send to more than one guess at a time.",
    }
    if not suggestions:
        result["note"] = (
            f"No work addresses on file for anyone at {contact.get('company') or 'that firm'}, "
            "so there is no pattern to learn from. Check the firm's website footer "
            "or ask for their address in a LinkedIn message."
        )
    else:
        result["next_step"] = (
            "Once confirmed, save it with set_contact_email so future drafts use it."
        )
    return result


@mcp.tool
def set_contact_email(contact_id: int, email: str) -> dict:
    """Save a confirmed email address on a contact.

    Args:
        contact_id: Contact id.
        email: The address, once the user has confirmed it is right.
    """
    config = _config()
    if not gmail.valid_recipient(email):
        return {"error": f"'{email}' is not a single valid email address."}
    with session(config.db_path) as conn:
        try:
            row = store.set_contact_email(conn, contact_id, email)
        except store.NotFound as exc:
            return {"error": str(exc)}
    return Contact(**row).model_dump()



# --------------------------------------------------------------------------
# The coach — resume, the weekly check-in, and fit
# --------------------------------------------------------------------------


@mcp.tool
def save_resume(text: str) -> dict:
    """Store the user's CV so it can be tailored against real postings.

    The user pastes it straight into the chat — no files, no folders. Replaces
    whatever was stored before, so read the current one back first if you are
    only editing part of it.

    Args:
        text: The full CV as plain text or Markdown.
    """
    config = _config()
    with session(config.db_path) as conn:
        row = store.save_resume(conn, text)
        notes = store.list_resume_notes(conn)
    return {
        "saved": True,
        "characters": len(row["text"] or ""),
        "updated_at": row["updated_at"],
        "pending_updates": len(notes),
        "next_step": (
            "It is now available as the resume resource for tailoring. If they "
            "mention something newer than the CV, capture it with add_resume_note."
        ),
    }


@mcp.tool
def add_resume_note(note: str, kind: str = "update") -> dict:
    """Capture something that happened since the CV was last written.

    A case competition win, a new leadership role, a project that finished.
    These accumulate so the CV can be refreshed properly later, and so you can
    draw on recent material the CV does not mention yet.

    Args:
        note: What happened, in enough detail to write a bullet from later.
        kind: update | win | project | skill | feedback.
    """
    config = _config()
    with session(config.db_path) as conn:
        row = store.add_resume_note(conn, note, kind)
    return ResumeNote(**row).model_dump()


@mcp.tool
def weekly_checkin(lookahead_days: int = 14, stale_after_days: int = 21) -> dict:
    """Everything that needs attention this week, in one call.

    This is the habit: what is overdue, what closes soon, who has gone quiet,
    which target firms nobody has spoken to yet, and where the user sits in the
    cycle. The numbers are facts — the coaching is yours. Lead with the two or
    three things that actually matter, not the whole list.

    Args:
        lookahead_days: How far ahead to look for deadlines.
        stale_after_days: How long an application sits untouched before it counts as stalled.
    """
    config = _config()
    today = date.today()
    horizon = (today + timedelta(days=max(0, lookahead_days))).isoformat()
    stale_before = (today - timedelta(days=max(1, stale_after_days))).isoformat()

    with session(config.db_path) as conn:
        track = store.get_profile(conn).get("track") or config.track
        overdue = store.due_followups(conn, today.isoformat())
        deadlines = store.upcoming_deadlines(conn, horizon)
        stalled = store.stale_applications(conn, stale_before, ("interested", "applied"))
        cold = store.going_cold(conn, stale_before)
        untouched = store.targets_without_contact(conn)
        applications = store.list_applications(conn)
        resume = store.get_resume(conn)
        contacts = store.count_contacts(conn)

    counts: dict[str, int] = {}
    for row in applications:
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    try:
        cycle = timeline.get_timeline(track, overrides_dir=config.timeline_overrides_dir, today=today)
        active = [m for m in cycle["milestones"] if m["status"] == "active"]
        upcoming = [m for m in cycle["milestones"] if m["status"] == "upcoming"]
        where_you_are = {
            "track": cycle["track"],
            "happening_now": [
                {"name": m["name"], "ends_on": m["ends_on"], "actions": m["actions"]}
                for m in active
            ],
            "next_up": (
                {"name": upcoming[0]["name"], "starts_on": upcoming[0]["starts_on"],
                 "days_away": upcoming[0]["days_until"]}
                if upcoming else None
            ),
        }
    except timeline.UnknownTrack:
        where_you_are = {"track": track, "happening_now": [], "next_up": None}

    return {
        "today": today.isoformat(),
        "where_you_are": where_you_are,
        "overdue_followups": [
            {
                "contact_id": row["id"],
                "name": row["full_name"],
                "company": row["company"],
                "due_on": row["due_on"],
                "days_overdue": (today - date.fromisoformat(row["due_on"])).days,
                "last_notes": row.get("last_notes"),
            }
            for row in overdue
        ],
        "deadlines": [
            {
                "id": row["id"],
                "company": row["company"],
                "role": row["role"],
                "deadline": row["deadline"],
                "days_left": row["days_until_deadline"],
                "status": row["status"],
            }
            for row in deadlines
        ],
        "stalled_applications": [
            {"id": row["id"], "company": row["company"], "role": row["role"],
             "status": row["status"], "last_touched": row["updated_at"]}
            for row in stalled
        ],
        "going_cold": [
            {"contact_id": row["id"], "name": row["full_name"], "company": row["company"],
             "last_spoke": row["last_occurred_at"]}
            for row in cold
        ],
        "targets_nobody_has_spoken_to": [
            {"name": row["name"], "priority": row["priority"]} for row in untouched
        ],
        "pipeline": counts,
        "housekeeping": {
            "resume_on_file": bool(resume.get("text")),
            "resume_updated": resume.get("updated_at"),
            "contacts_imported": contacts,
        },
    }


@mcp.tool
def suggest_targets(limit: int = 12, include_current: bool = False) -> dict:
    """Firms worth considering, with the evidence needed to judge fit.

    Returns candidates the user has not targeted yet, each annotated with what
    is actually known: whether their job board can be read, and how many of the
    user's own contacts already work there. Judge fit yourself against their
    resume and background — this tool deliberately does not score it, because
    "suits my profile" is a judgement about a person, not a lookup.

    Args:
        limit: Maximum candidates to return.
        include_current: Also return firms already on the target list.
    """
    config = _config()
    overrides = config.data_dir / "presets"

    with session(config.db_path) as conn:
        profile = store.get_profile(conn)
        resume = store.get_resume(conn)
        existing = {t["name"].strip().lower(): t for t in store.list_targets(conn)}
        contacts = store.list_contacts(conn)

    track = profile.get("track") or config.track
    try:
        pack = presets.load_pack(track, overrides_dir=overrides)
    except presets.UnknownPack:
        pack = {"companies": [], "label": track}

    def contacts_at(company: str) -> list[dict]:
        return [
            contact
            for contact in contacts
            if connections.company_affinity(contact.get("company"), company)
        ]

    candidates = []
    for entry in pack.get("companies", []):
        already = entry["name"].strip().lower() in existing
        if already and not include_current:
            continue
        inside = contacts_at(entry["name"])
        candidates.append(
            {
                "name": entry["name"],
                "careers_url": entry.get("careers_url"),
                "board_readable": bool(entry.get("ats")),
                "already_targeted": already,
                "people_you_know_there": len(inside),
                "who": [
                    {"id": c["id"], "name": c["full_name"], "title": c.get("title")}
                    for c in inside[:3]
                ],
                "tier_hint": entry.get("priority", 2),
            }
        )

    candidates.sort(key=lambda c: (-c["people_you_know_there"], c["tier_hint"], c["name"]))

    return {
        "track": track,
        "pack": pack.get("label", track),
        "candidates": candidates[:limit],
        "you": {
            "background": profile.get("background"),
            "goals": profile.get("goals"),
            "hard_constraints": profile.get("hard_constraints"),
            "target_locations": profile.get("target_locations"),
            "resume_on_file": bool(resume.get("text")),
        },
        "how_to_use_this": (
            "Read the resume resource, then say which of these actually fit and "
            "which are a stretch, and why. Firms where they already know someone "
            "are listed first because a warm path beats a marginally better fit. "
            "If the list is thin, ask what they want and add firms yourself with "
            "add_target_company."
        ),
    }


# --------------------------------------------------------------------------
# Resources — read-only state for the assistant to reason over
# --------------------------------------------------------------------------


def _json(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str)


@mcp.resource("mba://resume", mime_type="text/markdown")
def resume_resource() -> str:
    """The user's CV, plus everything that has happened since it was written."""
    config = _config()
    with session(config.db_path) as conn:
        stored = store.get_resume(conn)
        notes = store.list_resume_notes(conn)

    text = stored.get("text")
    if not text and config.base_cv.is_file():
        text = config.base_cv.read_text(encoding="utf-8", errors="replace")
    if not text:
        return (
            "No CV on file yet. Ask the user to paste theirs into the chat and "
            "store it with save_resume — they do not need to find a file or a folder."
        )

    parts = [text]
    if notes:
        parts.append("\n\n---\n\n## Since this CV was written\n")
        parts.extend(f"- **{note['added_on']}** ({note['kind']}): {note['note']}" for note in notes)
    return "\n".join(parts)


@mcp.resource("mba://base_cv", mime_type="text/markdown")
def base_cv() -> str:
    """Deprecated alias for the resume resource."""
    return resume_resource()


@mcp.resource("mba://profile", mime_type="application/json")
def profile_resource() -> str:
    """Who the user is: school, graduation year, track."""
    config = _config()
    with session(config.db_path) as conn:
        profile = store.get_profile(conn)
    profile.setdefault("school", None)
    return _json({**profile, "school_from_env": config.school, "track_default": config.track})


@mcp.resource("mba://targets", mime_type="application/json")
def targets_resource() -> str:
    """Current target company list."""
    config = _config()
    with session(config.db_path) as conn:
        return _json(store.list_targets(conn))


@mcp.resource("mba://pipeline", mime_type="application/json")
def pipeline_resource() -> str:
    """Current application pipeline with deadline countdowns."""
    config = _config()
    with session(config.db_path) as conn:
        return _json({"today": today_iso(), "applications": store.list_applications(conn)})


@mcp.resource("mba://contacts", mime_type="application/json")
def contacts_resource() -> str:
    """Imported contacts and their follow-up state."""
    config = _config()
    with session(config.db_path) as conn:
        return _json(
            {
                "total": store.count_contacts(conn),
                "contacts": store.list_contacts(conn, limit=500),
                "due_followups": store.due_followups(conn, today_iso()),
            }
        )


@mcp.resource("mba://timeline", mime_type="application/json")
def timeline_resource() -> str:
    """Key dates for the user's track, projected onto this cycle."""
    config = _config()
    with session(config.db_path) as conn:
        track = store.get_profile(conn).get("track") or config.track
    try:
        return _json(timeline.get_timeline(track, overrides_dir=config.timeline_overrides_dir))
    except timeline.UnknownTrack as exc:
        return _json({"error": str(exc)})




# --------------------------------------------------------------------------
# Prompts — how a coaching conversation starts
# --------------------------------------------------------------------------


@mcp.prompt
def start_here() -> str:
    """Set up the campaign from scratch, in one conversation."""
    return (
        "Help me set up my recruiting campaign. Ask me one question at a time, "
        "in plain English, and save what I tell you as we go:\n\n"
        "1. My name, business school and graduation year.\n"
        "2. What I did before the MBA, and what I actually want out of "
        "recruiting — including the honest version, not the interview answer.\n"
        "3. Anything non-negotiable: visa status, city, family.\n"
        "4. Which track I am recruiting for.\n"
        "5. Then ask me to paste my CV straight into the chat.\n\n"
        "Once you have that, seed a target list for my track, tell me where I "
        "am in the cycle right now, and give me the two things to do this week. "
        "Then explain, in one short paragraph, what you can do for me from here."
    )


@mcp.prompt
def catch_me_up() -> str:
    """The Monday-morning coaching session. (The weekly_checkin tool feeds it.)"""
    return (
        "Run my weekly check-in. Look at what is overdue, what closes soon, who "
        "has gone quiet, and which of my target firms I still have not spoken to "
        "anyone at.\n\n"
        "Then coach me: tell me the two or three things that actually matter this "
        "week and why, in order. Be direct about anything I am letting slip. End "
        "with a short list of what to do, specific enough that I can start on it "
        "now — names, firms, dates."
    )


@mcp.prompt
def fit_check() -> str:
    """Which firms actually suit me, and where am I stretching?"""
    return (
        "Read my CV and my profile, then look at the firms worth considering for "
        "my track.\n\n"
        "Tell me honestly: which of these fit my background, which are a stretch "
        "and what would have to be true for the stretch ones to work, and which I "
        "should drop. Say where my story is strong and where it is thin for this "
        "track. If there are firms outside the list that suit me better given what "
        "I actually want, say so and add them."
    )


@mcp.prompt
def tailor_application(company: str, role: str = "") -> str:
    """Tailor the CV and application material to one specific posting."""
    return (
        f"I am applying to {company}"
        + (f" for the {role} role" if role else "")
        + ". Use the job description I have stored for it if there is one; ask me "
        "to paste it if not.\n\n"
        "Then work through it with me:\n"
        "1. What this firm is actually screening for in this role.\n"
        "2. Which of my experiences map onto that, using my real CV and anything "
        "I have added since — quote my own wording back to me and sharpen it.\n"
        "3. Where I am weak against this posting, and how to handle that honestly "
        "rather than hide it.\n"
        "4. A tailored version of the relevant CV bullets, and my 'why this firm' "
        "answer in three sentences.\n\n"
        "Do not invent experience I do not have. If something is missing, tell me "
        "it is missing."
    )


def main() -> None:
    _config()
    mcp.run()
