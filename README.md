<h1 align="center">mba-mcp</h1>

<p align="center"><strong>Claude, as an MBA recruiting coach that remembers your entire campaign.</strong></p>

<p align="center">
  <img alt="MIT" src="https://img.shields.io/badge/license-MIT-black">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-black">
  <img alt="148 tests" src="https://img.shields.io/badge/tests-148%20offline-black">
  <img alt="no API key" src="https://img.shields.io/badge/API%20keys-none%20required-black">
</p>

An [MCP](https://modelcontextprotocol.io) server that gives Claude persistent memory and live data for business-school recruiting: your CV, your target firms, every application and deadline, and every person you've spoken to.

You talk to Claude the way you already do. It opens with what actually matters this week, because it can see your real campaign instead of asking you to describe it again.

Runs entirely on your laptop. No account, no server, no API key, nothing to pay for.

---

## Why this exists

MBA recruiting is won on **timelines and relationships**, not application volume.

Every LLM can already rewrite your CV — that part is solved and free. What no chat can do is remember that Bain's coffee-chat window closes in nine days, that you know an alum three years ahead of you at Evercore, or that you promised to follow up with her on the 14th. So the work that actually decides outcomes — tracking, timing, following up — falls back to a spreadsheet nobody is still maintaining by November, during the single busiest term of the degree.

This is the missing half: the assistant does the thinking, the server does the remembering.

## What it looks like

Ask *"what should I be doing this week?"* and Claude gets this, then coaches off it:

```
where you are   Applications and resume drops  (closes in 13 days)
                next up: First rounds and HireVue, 44 days away

overdue         Priya Raman (Bain)         3 days
deadlines       PJT Partners               6 days
going cold      Sam Ito (Bain Capital)     last spoke 34 days ago
no contact yet  Blackstone · Centerview · Evercore · Goldman Sachs

pipeline        4 interested · 2 applied · 1 interview
```

Other things it handles, in plain conversation:

| You say | What happens |
|---|---|
| *paste your CV into the chat* | Stored, and used for every tailoring job after |
| *"I won the case competition"* | Kept against your CV, so it surfaces next time you apply |
| *"Any new summer associate roles?"* | Reads your target firms' live job boards |
| *"Who do I know at Evercore?"* | Ranks your own LinkedIn connections, with the reason for each |
| *"Find me Wharton alumni there"* | Builds the LinkedIn searches for you to open |
| *"Which of these firms actually suit me?"* | Honest read of your background against the list |
| *"Draft a note to Priya"* | Written from your real history with her |

## How it works

```
            You  ⇄  Claude                      the thinking: coaching, tailoring,
                      ⇅                          judgement of fit, every word written
                  mba-mcp                        the memory: state, data, actions
                      ⇅
   ┌──────────────┬───┴────────┬─────────────────┐
   SQLite          Job boards   Your LinkedIn     Curated
   on your disk    (5 vendors)  CSV export        recruiting calendars
```

The split is the whole design: **Claude does all the language work, the server does none of it.** The server never calls a model, which is why it needs no API key and costs nothing to run.

About 3,800 lines of Python, plus 1,400 of tests. SQLite for state with append-only migrations, five ATS adapters for live job data, and pure functions — no database, no network — for ranking, date maths and email inference. That separation is why the 148-test suite runs fully offline in under a second.

### The interesting problem: finding a firm's job board

Job listings live behind whichever applicant-tracking system a firm happens to use, and there's no directory of which firm uses what. The obvious fix — maintain a lookup table of companies — rots immediately and never covers the boutique nobody has heard of.

So instead you paste any careers URL and it works backwards:

1. **Is that URL already a job board?** Greenhouse, Lever, Ashby, Workday and SmartRecruiters each put the firm's identifier in a predictable place.
2. **No? Then read the careers page** and find the board it embeds or links to. This is how Citi, PJT Partners, Moelis and Blackstone all resolve — their Workday tenant names are not guessable, but their careers pages link straight to them.
3. **Still nothing?** Fall back to a keyed search, or keep it as a link you track by hand.

No registry to maintain. A firm that switches vendors keeps working; a boutique nobody has heard of works on day one.

## Design constraints

These are the product, not settings. Each one closes off something that would have been easier to build.

| | |
|---|---|
| **Never submits an application** | It drafts and tracks. You submit. Always. |
| **Never scrapes LinkedIn** | LinkedIn has no public people or jobs API, and scraping it gets *your* account restricted. Contacts come from your own data export; alumni search builds links you open yourself. |
| **Never sends bulk email** | One message, only after you approve that exact text, and the same draft can never be sent twice. |
| **Knows nothing about you** | No account, no telemetry, no server. One SQLite file on your laptop. |
| **Makes no model calls** | The assistant already in front of you does the language work. Nothing to bill. |

## Install

Requires Python 3.11+ (macOS ships 3.9, so you may need [python.org](https://www.python.org/downloads/)).

```bash
git clone https://github.com/nhemrajani/mba-mcp && cd mba-mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
mba-mcp info          # shows where your data will live
```

Then point Claude at it — `claude_desktop_config.json` for Claude Desktop, `~/.claude.json` for Claude Code:

```json
{
  "mcpServers": {
    "mba-mcp": {
      "command": "/absolute/path/to/mba-mcp/.venv/bin/mba-mcp",
      "env": { "MBA_MCP_DATA_DIR": "/Users/you/.mba-mcp" }
    }
  }
}
```

Restart Claude, then pick **`start_here`** from the prompt menu — or just say *"help me set up my recruiting campaign."* It asks one question at a time, ends by asking for your CV, and gives you the two things to do this week.

<details>
<summary>Configuration, and the optional extras</summary>

| Variable | Default | What it does |
|---|---|---|
| `MBA_MCP_DATA_DIR` | `~/.mba-mcp` | Database and credentials |
| `MBA_MCP_TRACK` | `consulting` | Default track (`finance`, `banking`, `IB`, `MBB` all resolve) |
| `MBA_MCP_SCHOOL` | unset | Ranks alumni above strangers |
| `ADZUNA_APP_ID` / `_KEY` | unset | Optional free keys, widening job search to firms with no readable board |

Everything is read from the environment; no secret is ever stored in the repo. `set_profile` overrides these in conversation, which is the intended route.

**Letting Claude send email itself** is off by default and deliberately not part of setup — Claude drafting and you pasting takes five seconds and needs nothing. If you want it anyway: enable the Gmail API on a free Google Cloud project, create a Desktop OAuth client, save the JSON to your data dir, then `pip install -e '.[gmail]'` and `mba-mcp auth`. Scope is `gmail.send` only — it cannot read your mail.
</details>

## Everything it can do

**Coaching** · `weekly_checkin` · `suggest_targets` · `save_resume` · `add_resume_note`
**You** · `set_profile`
**Targets & jobs** · `add_target_company` · `add_target_pack` · `list_target_packs` · `list_targets` · `find_jobs`
**Pipeline & timing** · `track_application` · `update_application` · `list_applications` · `get_recruiting_timeline`
**Networking** · `import_connections` · `find_warm_paths` · `find_alumni` · `log_interaction` · `get_followups`
**Outreach** · `suggest_email` · `set_contact_email` · `save_outreach_draft` · `send_email` *(optional)*

**Prompts** · `start_here` · `catch_me_up` · `fit_check` · `tailor_application`
**Resources** Claude reads at will · `resume` · `profile` · `targets` · `pipeline` · `contacts` · `timeline`

## Status, honestly

Working and in use: the tools, both recruiting tracks, all five job-board adapters (verified against live boards), and the full offline test suite.

Not done yet:

- **No packaged release.** A one-click Claude Desktop bundle builds from `scripts/build_mcpb.py`, but it vendors a compiled dependency, so it needs one build per platform before it's worth publishing. Install from source for now.
- **Timelines are curated templates, not live deadlines.** They project a typical calendar onto today's date. Firms move dates every year, and banking moves earlier almost annually — confirm with your career centre. Drop your own JSON in your data dir to override the bundled one.
- **Consulting job search is thin by nature.** MBB and the Big Four run bespoke careers sites no tool can read, so those are tracked as links. Banking fares much better. The campaign layer is where consulting is won anyway.

## Contributing

Good first issues, in rough order of usefulness:

- **Add an ATS adapter.** Oracle/Taleo and Eightfold are the big gaps — between them they cover several bulge-bracket banks. Follow [`ats.py`](src/mba_mcp/ats.py): a URL pattern, a pure `parse_*` function, a saved fixture, a test.
- **Add a track.** Tech and unstructured/off-cycle are unwritten. Copy [`timelines/investment_banking.json`](src/mba_mcp/timelines/investment_banking.json) and cite where the dates come from.
- **Add a non-US calendar.** LBS, INSEAD and HKUST run different cycles and nobody has written them down.
- **Improve warm-path ranking.** [`score_contact`](src/mba_mcp/connections.py) is deliberately simple and explains every score it gives.

```bash
pip install -e '.[dev]' && pytest
```

Tests never touch the network — adapters run against saved fixtures, and the suite fails loudly on any accidental request. Please keep it that way. More detail in [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).
