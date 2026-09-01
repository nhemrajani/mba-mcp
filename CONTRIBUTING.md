# Contributing

Thanks for helping. This project is for students who are in the middle of
recruiting and cannot afford a tool that surprises them, so the bar for changes
is less "does it work" and more "would I trust it during superday week".

## The guardrails are not negotiable

A change that weakens any of these will be declined, however useful it is:

1. **No auto-submitting applications.** Draft and track. The human submits.
2. **No LinkedIn scraping.** Contacts come from the user's own data export.
   Alumni discovery hands the user a link they click themselves.
3. **No bulk email.** `send_email` sends one message, after explicit
   confirmation, and refuses a draft that has already been sent.
4. **No hardcoded secrets.** Everything sensitive comes from the environment.
5. **The server stays deterministic.** Data, actions and state. No model calls —
   language and judgement belong to the assistant.

If you think one of these is wrong, open an issue and argue the case before
writing code.

## Layout

```
src/mba_mcp/
  config.py        env loading; no secret is ever read from the repo
  db.py            SQLite connection + append-only migrations
  store.py         CRUD only, no judgement
  models.py        pydantic records returned by tools
  ats.py           board detection, careers-page discovery, vendor parsers
  connections.py   LinkedIn CSV import + warm-path ranking
  emails.py        email-pattern inference from the user's own contacts
  linkedin.py      deep-link builders (pure strings, no requests)
  timeline.py      cycle-aware timeline rendering
  presets.py       starter packs of firms
  gmail.py         OAuth + single-message send
  server.py        FastMCP tools and resources — wiring only
```

The split matters: pure logic (`ats`, `connections`, `emails`, `linkedin`,
`timeline`) never touches the database, and `store.py` never makes a decision.
That is why the whole suite runs offline in under a second.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev,gmail]'
pytest
```

## Tests must stay offline

Every test runs without a network. ATS adapters are exercised against saved
JSON in `tests/fixtures/`, and `tests/test_server.py` has an autouse fixture
that makes any accidental network call fail loudly. If you add an adapter, save
a real (trimmed, anonymised) response as a fixture rather than mocking a shape
you have imagined.

## Adding an ATS adapter

The highest-value contribution. Four steps, all in one PR:

1. A URL pattern in `detect_ats`, plus a signature in `_BOARD_SIGNATURES` so a
   careers page that links to that board is discovered automatically.
2. A pure `parse_<vendor>(payload, company) -> list[dict]` returning the
   normalised shape: `company`, `title`, `location`, `url`, `posted_at`,
   `source`.
3. A fetch path wired into `fetch_board`. If the vendor's API takes a query,
   push keywords down to it rather than filtering client-side.
4. A fixture and tests: detection, parsing, a junk payload, and an HTTP error.

Oracle/Taleo and Eightfold are the biggest gaps — together they cover several
bulge-bracket banks.

## Adding a track timeline

Copy `src/mba_mcp/timelines/investment_banking.json`. Milestones are `MM-DD`
windows inside a cycle that starts at `cycle_start_month`; set that month so
the earliest milestone lands in the right calendar year. Say where your dates
came from in the PR, and keep the `disclaimer` honest — these are templates,
never live deadlines.

## Style

Match the surrounding code. Comments explain *why*, not *what*. Docstrings on
tools are read by the assistant at runtime, so write them for that reader:
say what the tool is for, what the arguments mean, and what the human is
expected to do with the result.
