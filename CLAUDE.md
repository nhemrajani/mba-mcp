# MBA MCP — Build Brief

This file is the spec and the guardrails. Build phase by phase — each phase is
independently shippable.

## Goal

An open-source MCP server that lets an AI assistant act as a business-school
student's recruiting coach. The assistant does the reasoning (coaching,
tailoring, drafting, judgement of fit); the server provides memory, data and
actions. Local-first, MIT-licensed, free to run — no keys required for anything
on the main path.

**The user is overwhelmed and non-technical.** They should never see a tool
name, a file path, or a config file. The server's job is to remember everything
so they never have to repeat themselves, and to hand the assistant enough real
state that it can open with "these two things matter this week" instead of
"tell me about yourself".

## The wedge — do not drift from this

MBA recruiting is won on timelines and relationships, not application volume.
The differentiated core is the **campaign layer**: target-company lists,
cycle-aware deadlines, a networking pipeline, and human-approved warm outreach.
CV tailoring and case/coursework prep are expansions, not the launch — any LLM
does those for free, so they are never the reason to use this tool. Build the
spine first; earn daily-use habit; layer prep later.

Build one recruiting track end to end before adding others. Tracks: consulting,
investment banking, tech, unstructured/off-cycle.
**Shipped: consulting (v1), investment banking (v2). Unwritten: tech,
unstructured/off-cycle.**

## Non-goals (hard)

- No auto-submitting applications. Ever. Draft + track + human submits.
- No live LinkedIn scraping, ever — it breaks LinkedIn's terms and risks the
  user's own account. Contacts come from their own CSV export. Alumni discovery
  builds search URLs the human opens themselves; the server never fetches
  linkedin.com.
- No third-party contact-enrichment services. Email inference works only from
  addresses the user already has, and every guess is labelled unverified.
- No bulk/automated email sending. Every send is one message, explicitly
  confirmed by the user. Sending is an off-by-default extra, not part of setup:
  the coach drafts, the human pastes. Anything that drags a Google Cloud
  console into onboarding has failed the non-technical test.
- No reading the user's Claude or ChatGPT conversation history — neither
  product exposes it, and the server does not need it. The server *is* the
  memory: state lives here, so every new chat starts informed.
- The server makes no paid model API calls — the calling assistant does all
  language work. No model key required.

## Architecture & stack

- Python 3.11+, FastMCP for the server.
- SQLite for local state (via `sqlite3`).
- httpx for ATS job-board calls.
- google-api-python-client + google-auth-oauthlib for Gmail send.
- pydantic for data models. pytest for tests.
- Single local process; state persists in a SQLite file under a configurable
  data dir.

## Config / BYOK

All secrets from environment variables or the MCP client's server `env` block —
never hardcoded.

- `MBA_MCP_DATA_DIR` — where the SQLite DB + credentials live (default
  `~/.mba-mcp`).
- `GMAIL_OAUTH_CLIENT_SECRET` / token cache path — user supplies their own
  Google Cloud OAuth client (desktop app type). In testing mode this works for
  the user themselves with no Google verification.
- `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` — optional, for broad job-board search
  (free tier).
- No model key needed.

## Data sources & access notes

- Greenhouse (public, no auth):
  `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs`
- Lever (public): `GET https://api.lever.co/v0/postings/{company}?mode=json`
- Ashby (public posting API):
  `GET https://api.ashbyhq.com/posting-api/job-board/{company}`
- Workday (the JSON its own career pages call, no auth):
  `POST https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs`
  with `{"appliedFacets":{},"limit":20,"offset":0,"searchText":""}`. Takes a
  server-side query; `postedOn` is prose ("Posted 3 Days Ago") so dates are
  approximate. This is what most banks use.
- SmartRecruiters (public):
  `GET https://api.smartrecruiters.com/v1/companies/{company}/postings`
- Adzuna (optional, keyed): broad multi-board search fallback.
- LinkedIn: no API for jobs or people. Connections come from the user's own CSV
  export. Everything else is a deep link the user clicks.

**First real engineering problem — resolving a company to its ATS.** Don't
build a big registry. The user pastes any careers URL:

1. If the URL *is* a board, parse the vendor and slug out of it.
2. If it is a marketing careers page, fetch it and look for a board it embeds
   or links to (`discover_ats`). This is how Citi, PJT, Moelis and Blackstone
   resolve — their Workday tenant names are not guessable.
3. Otherwise fall back to Adzuna, or keep it as a link the user tracks by hand.

Starter packs in `presets/` are a convenience for onboarding, not a registry:
they carry a careers URL, and the board is resolved through the same discovery
path at add time. Only pre-resolve a board in a preset when it has been
verified against the live API.

## MCP tools — v1

### The coach

- `weekly_checkin(lookahead_days?, stale_after_days?)` → everything needing
  attention in one call: overdue follow-ups, closing deadlines, stalled
  applications, contacts going cold, target firms with nobody spoken to, and
  where the user sits in the cycle. Facts only — the coaching is the
  assistant's job.
- `suggest_targets(limit?, include_current?)` → candidate firms annotated with
  what is *known* (board readable, people the user already knows there).
  Deliberately does not score fit: "suits my profile" is a judgement about a
  person, made by the assistant against the resume.
- `save_resume(text)` → the CV, pasted straight into the chat. No files.
- `add_resume_note(note, kind?)` → things that happened since the CV was
  written, so the assistant can draw on them and refresh the CV later.

### Profile

- `set_profile(school?, graduation_year?, track?, full_name?, email?,
  target_locations?, background?, goals?, hard_constraints?)` → the user's
  profile. School and graduation year drive alumni ranking; background, goals
  and constraints drive fit. Fill these from conversation, not interrogation.

### Targets & discovery

- `add_target_company(name, ats_url?, priority?)` → target record (detects the
  board from the URL, or discovers it from the careers page)
- `add_target_pack(pack, resolve?, priority_max?)` → seed a whole track's
  target list at once
- `list_target_packs()` → available starter packs
- `list_targets()` → all targets
- `find_jobs(company?, keywords?, location?)` → open roles from targets' ATS
  (or Adzuna). Returns title, location, url, posted_at.

### Pipeline & timeline

- `track_application(company, role, url, status="interested", deadline?)` →
  application record
- `update_application(id, status?, deadline?, notes?)` → updated record
  (statuses: interested → applied → interview → offer → rejected)
- `list_applications(status?)` → pipeline view
- `get_recruiting_timeline(track)` → cycle-aware key dates for the track,
  expressed relative to today (curated template per track, stored as data)

### Networking & outreach

- `import_connections(csv_path)` → count imported; stores name, company, title,
  connected_on
- `find_warm_paths(company)` → stored contacts + alumni at/near that company,
  ranked by closeness, each with the reasons behind its score
- `find_alumni(company?, keywords?, graduated_within_years?)` → alumni already
  in contacts, plus LinkedIn searches the *user* opens (never fetched here)
- `log_interaction(contact_id, kind, notes, next_followup?)` → interaction
  record
- `get_followups()` → contacts due for follow-up (sorted by date)
- `suggest_email(contact_id)` → likely work addresses, inferred from the firm's
  convention as seen in the user's own contacts, always labelled unverified
- `set_contact_email(contact_id, email)` → save a confirmed address
- `save_outreach_draft(contact_id, subject, body)` → stored draft (the
  assistant writes the text; this persists it)
- `send_email(draft_id)` → sends via the user's Gmail. Requires an explicit
  confirmation flag; sends exactly one message; never loops.

## MCP resources (read-only context for the assistant)

- `base_cv` — the user's master CV text/file (so the assistant can tailor
  against a JD)
- `resume` — the stored CV plus every update logged since it was written
- `profile`, `targets`, `pipeline`, `contacts`, `timeline` — current state, so
  the assistant reasons over real data

## MCP prompts (how a coaching conversation starts)

`start_here` (onboarding in one conversation) · `catch_me_up` (the Monday
check-in) · `fit_check` (which firms suit me) · `tailor_application` (work
through one posting). Prompt names must not collide with tool names — they
share a Python module namespace even though MCP keeps separate registries.

## Build phases — each ships on its own

- **Phase 0 — scaffold.** FastMCP server, SQLite schema, config/env loading,
  README, MIT license. Smoke test: server connects to Claude Code and lists
  tools.
- **Phase 1 — targets + discovery.** `add_target_company`, `list_targets`,
  `find_jobs` (Greenhouse first, then Lever, then Ashby). Shippable outcome:
  "show me open roles at my target firms" works end to end.
- **Phase 2 — pipeline + timeline.** Application tracking tools +
  `get_recruiting_timeline` for the chosen track. Shippable: a live pipeline
  with deadlines.
- **Phase 3 — networking.** `import_connections`, `find_warm_paths`,
  `log_interaction`, `get_followups`. Shippable: paste your LinkedIn export,
  get warm intro paths to a target.
- **Phase 4 — outreach.** `save_outreach_draft`, `send_email` via Gmail
  (confirm-to-send). Shippable: draft and send a tailored cold email from your
  own account.
- **Phase 5 — shipped.** Investment banking track; Workday and SmartRecruiters
  adapters; careers-page board discovery; profile and alumni tooling; email
  inference; starter packs; one-click `.mcpb` bundle for Claude Desktop.
- **Phase 6 — shipped.** The coach layer: resume pasted into the chat, running
  resume notes, the weekly check-in, fit-and-targeting data, coaching
  instructions and prompt starters. Gmail sending demoted to an off-by-default
  extra so nothing on the main path needs a terminal or a Google account.
- **Phase 7 — later.** Track-specific prep (cases / technicals) grounded in the
  user's own materials. Still not the wedge — do not lead with it.

## Guardrails for the build (repeat to yourself)

1. No auto-submit. No LinkedIn scraping. No bulk email.
2. `send_email` sends one confirmed message at a time.
3. Never hardcode secrets; read from env/config.
4. Store only what the tool needs; don't cache third-party data you don't use.
5. Keep the server deterministic — data + actions + state. Language/reasoning
   belongs to the assistant.

## Testing

- Unit tests for each ATS parser against saved sample JSON
  (Greenhouse/Lever/Ashby).
- Unit tests for the CSV importer and `find_warm_paths` matching.
- Schema/migration test for the SQLite layer.
- Manual checklist for the Gmail OAuth flow and a live one-message send.

## Repo map

```
src/mba_mcp/
  config.py        env/config loading, data dir resolution
  db.py            SQLite connection + append-only migrations
  store.py         CRUD only — no judgement in the data layer
  models.py        pydantic records
  ats.py           board detection, careers-page discovery, vendor parsers
  connections.py   LinkedIn CSV import + warm-path ranking
  emails.py        email-pattern inference from the user's own contacts
  linkedin.py      deep-link builders (pure strings, no requests)
  timeline.py      cycle-aware timeline rendering
  presets.py       starter packs of firms per track
  gmail.py         OAuth + single-message send
  server.py        FastMCP tools + resources — wiring only
  timelines/       curated per-track timeline templates (JSON data)
  presets/         starter target lists per track (JSON data)
scripts/           build_mcpb.py — the one-click Claude Desktop bundle
tests/             unit tests + saved ATS/CSV fixtures; must stay offline
```

Pure logic (`ats`, `connections`, `emails`, `linkedin`, `timeline`) never
touches the database, and `store.py` never makes a decision. Keep it that way —
it is why the suite runs offline in under a second.
