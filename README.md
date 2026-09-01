<h1 align="center">mba-mcp</h1>

<p align="center">
  <strong>A recruiting coach that actually remembers your campaign.</strong><br>
  Paste your CV, tell it what you want, and it tracks the firms, deadlines, applications and people for you.
</p>

<p align="center">
  <a href="#install-in-two-minutes">Install</a> ·
  <a href="#what-you-can-say">What you can say</a> ·
  <a href="#the-guardrails">Guardrails</a> ·
  <a href="#contributing">Contribute</a> ·
  <img alt="MIT" src="https://img.shields.io/badge/license-MIT-black"> ·
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-black">
</p>

---

MBA recruiting is won on **timelines and relationships**, not application volume. Every LLM can already rewrite your CV. None of them know that Bain's coffee-chat window closes in nine days, that you have a Wharton alum three years ahead of you sitting in Evercore's New York office, or that you promised to follow up with her on the 14th.

This gives Claude that memory. It's free, it runs entirely on your laptop, and there's no account to make.

You talk to it like a coach. It reads your CV, knows your pipeline, and opens with the two things that matter this week instead of asking you to explain yourself again.

**Tracks:** consulting and investment banking, both end to end.

---

## Install in two minutes

### The easy way — Claude Desktop, no terminal

1. Download **`mba-mcp.mcpb`** from the [latest release](../../releases/latest).
2. Double-click it. Claude Desktop opens and asks you to confirm the install.
3. Fill in the two boxes it shows you — your business school and your track. That's it.
4. Say to Claude: **"Set up my recruiting campaign."**

> **One prerequisite:** Python 3.11 or newer. macOS ships with 3.9, so if Claude says the server won't start, install Python from [python.org](https://www.python.org/downloads/) (the big yellow button) and reinstall the extension. Nothing else to configure.

### The terminal way — Claude Code, one line

```bash
claude mcp add mba-mcp --env MBA_MCP_SCHOOL="Wharton" --env MBA_MCP_TRACK="consulting" -- uvx --from git+https://github.com/nhemrajani/mba-mcp mba-mcp
```

Or clone it and point Claude at the checkout:

```bash
git clone https://github.com/nhemrajani/mba-mcp && cd mba-mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[gmail]'
mba-mcp info    # shows where your data will live
```

<details>
<summary>Manual config for Claude Desktop or any other MCP client</summary>

Add this to `claude_desktop_config.json` (Desktop) or `~/.claude.json` (Code). Every secret lives in `env`; nothing is read from the repo.

```json
{
  "mcpServers": {
    "mba-mcp": {
      "command": "/absolute/path/to/mba-mcp/.venv/bin/mba-mcp",
      "env": {
        "MBA_MCP_DATA_DIR": "/Users/you/.mba-mcp",
        "MBA_MCP_SCHOOL": "Wharton",
        "MBA_MCP_TRACK": "investment_banking",
        "GMAIL_OAUTH_CLIENT_SECRET": "/Users/you/.mba-mcp/gmail_client_secret.json",
        "ADZUNA_APP_ID": "",
        "ADZUNA_APP_KEY": ""
      }
    }
  }
}
```

| Variable | Default | What it does |
|---|---|---|
| `MBA_MCP_DATA_DIR` | `~/.mba-mcp` | Database, credentials, your CV |
| `MBA_MCP_TRACK` | `consulting` | Default track (`finance`, `banking`, `IB`, `MBB` all resolve) |
| `MBA_MCP_SCHOOL` | unset | Ranks alumni above strangers |
| `MBA_MCP_BASE_CV` | `{data dir}/base_cv.md` | Optional CV file. Pasting it into the chat is easier |
| `GMAIL_OAUTH_CLIENT_SECRET` | `{data dir}/gmail_client_secret.json` | Your own Google OAuth client |
| `ADZUNA_APP_ID` / `_KEY` | unset | Optional wider job search |

Anything you set in the app's settings UI wins over these; `set_profile` wins over both.
</details>

---

## Start here

Four conversation starters, in Claude's prompt menu (the `+` / slash menu):

| | |
|---|---|
| **`start_here`** | Sets you up in one conversation — school, background, what you actually want, then paste your CV. Ends by telling you where you are in the cycle and what to do this week. |
| **`catch_me_up`** | Your Monday morning. What's overdue, what closes soon, who's gone quiet, which target firms you still haven't spoken to anyone at — then the two or three things that matter, in order. |
| **`fit_check`** | Reads your CV and tells you which firms actually suit your background, which are a stretch and what would have to be true, and which to drop. |
| **`tailor_application`** | Works through one posting with you: what they're screening for, which of your experiences map onto it, where you're weak and how to handle it honestly. |

You never have to use them — plain English works. They're just the fastest way in.

## What you can say

Just talk to Claude. These are examples, not commands to memorise.

| You say | What happens |
|---|---|
| *"I'm a Wharton MBA, class of 2028, recruiting for banking"* | Saves your profile — this is what makes alumni matching work |
| *paste your CV into the chat* | Stored, and used for tailoring from then on. No files, no folders |
| *"I won the case competition last week"* | Remembered against your CV, so it shows up when you next tailor |
| *"What should I be doing this week?"* | Overdue follow-ups, closing deadlines, firms going cold |
| *"Which of these firms actually suit me?"* | Honest read of your background against the list |
| *"Set up my target list for banking"* | Adds 18 firms and resolves each one's live job board |
| *"Any new summer associate roles this week?"* | Sweeps every target's board, filtered |
| *"Where am I in the cycle?"* | Your track's timeline, projected onto today's date |
| *"Who do I know at Evercore?"* | Ranks your own connections, with the reason for each |
| *"Find me Wharton alumni at Evercore"* | Builds the LinkedIn searches for you to open |
| *"What's Priya's email likely to be?"* | Infers it from your firm's addresses you already have |
| *"Draft a note to her"* | Claude writes it from your real history with her; you paste it into your mail |

**A day in the campaign**

```
Monday    catch_me_up                → 3 follow-ups overdue, PJT closes in 6 days,
                                       nobody spoken to at 5 of your target firms
          "Draft the Priya one"      → reads your notes from the last chat, writes it
Evening   "Coffee chat with Sam went
           well, he offered a refer"  → logged, follow-up set, nothing to fill in
```

---

## The guardrails

These are the design, not settings. They're why the tool is safe to leave running.

| | |
|---|---|
| **It never submits an application** | It drafts and tracks. You submit. Always. |
| **It never scrapes LinkedIn** | Contacts come from *your own* LinkedIn data export. Alumni search hands you a link that you click — your account is never automated against. |
| **It never sends bulk email** | `send_email` sends exactly one message, only after you approve that specific text, and refuses to send the same draft twice. |
| **It has no idea who you are** | No account, no telemetry, no server. One SQLite file on your laptop. |
| **It can't read your inbox** | Gmail access is `send`-only scope, using an OAuth client *you* create. |
| **It costs nothing to run** | The server makes no model API calls — Claude does all the language work. |

---

## How it finds jobs

You paste a firm's careers page. It works out the rest.

```
"Add Evercore: https://www.evercore.com/careers/"
        │
        ├─ Is that URL already a job board?        → Greenhouse · Lever · Ashby · Workday · SmartRecruiters
        ├─ No? Read the page and find the board.   → this is how Citi, PJT, Moelis and Blackstone resolve
        └─ Still nothing? Fall back to Adzuna, or keep it as a link you track by hand.
```

There's deliberately **no registry of companies** to maintain. A firm that switches ATS keeps working; a boutique nobody has heard of works on day one.

Some firms — several MBB among them — run bespoke careers sites that no tool can read. Those are tracked as links. The campaign layer is where consulting is won anyway.

---

## LinkedIn, honestly

LinkedIn has no public jobs API and no people API, and scraping it gets *your* account restricted. So this project doesn't. What it does instead:

- **Your connections** come from LinkedIn's own export (Settings → Data privacy → Get a copy of your data → *Connections*). Takes about ten minutes to arrive. Then: *"import my connections from ~/Downloads/Connections.csv"*. Re-running it is safe.
- **Alumni you haven't met** come from searches it builds and you open — pre-filled with your school, the target firm, recent graduation years, and junior titles. You connect as yourself. Next export, they're warm paths.
- **Jobs syndicated to LinkedIn** are almost always mirrored from the company's own ATS, which is read directly at the source, fresher than LinkedIn shows it.

The export has no school column. Add one by hand (or drop in your school's alumni-database export) and alumni ranking gets much sharper.

---

## Email addresses

Most finance contacts won't have an email in your export. `suggest_email` learns each firm's convention from addresses you already have — two colleagues at `first.last@` means the third is very likely `first.last@` too — and tells you how confident it is and why.

Every suggestion is labelled **unverified**. Nothing sends without you reading the address and the body first. No enrichment service is called; nothing about your contacts leaves your machine.

---

<details>
<summary><strong>Advanced: let Claude send the email itself</strong></summary>

Off by default, and deliberately not part of setup. Claude drafting the email and you pasting it into Gmail takes five seconds and requires nothing. This exists if you'd rather skip the paste.

It's free — a Google Cloud project with the Gmail API costs nothing and needs no billing account — but it takes about ten minutes of clicking, and it only works if you can run a terminal command (the Desktop bundle can't reach it).

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project and enable the **Gmail API**.
2. OAuth consent screen → **External**, leave it in **Testing**, add your own address as a test user. Testing mode works for you personally with no Google review.
3. Create an **OAuth client ID** → **Desktop app** → download the JSON → save it to your data dir.
4. Once, from a terminal: `pip install -e '.[gmail]'` then `mba-mcp auth`

Only `gmail.send` is requested — this code cannot read your mail. Sending is one message at a time, only after you approve that specific text, and the same draft can never be sent twice.

</details>

---

## Everything it can do

<details open>
<summary><strong>23 tools, 4 prompts, 7 resources</strong></summary>

**Coaching** · `weekly_checkin` · `suggest_targets` · `save_resume` · `add_resume_note`

**You** · `set_profile`

**Targets & jobs** · `add_target_company` · `add_target_pack` · `list_target_packs` · `list_targets` · `find_jobs`

**Pipeline & timing** · `track_application` · `update_application` · `list_applications` · `get_recruiting_timeline`

**Networking** · `import_connections` · `find_warm_paths` · `find_alumni` · `log_interaction` · `get_followups`

**Outreach** · `suggest_email` · `set_contact_email` · `save_outreach_draft` · `send_email` *(optional)*

**Prompts** · `start_here` · `catch_me_up` · `fit_check` · `tailor_application`

**Resources** (state Claude reads at any time) · `resume` · `profile` · `targets` · `pipeline` · `contacts` · `timeline`
</details>

---

## Timelines are templates, not feeds

`get_recruiting_timeline` projects a curated calendar onto today's date — consulting's autumn networking-to-January-deadlines cycle, banking's spring pre-MBA programs through superdays. Firms move these dates every year, and banking moves earlier almost annually.

Confirm against your career centre, then fix it: drop your own `timelines/consulting.json` into your data dir and it overrides the bundled one. No fork needed.

---

## Contributing

Good first issues, roughly in order of usefulness:

- **Add an ATS adapter.** Oracle/Taleo and Eightfold are the big gaps — between them they cover several bulge-bracket banks. Follow [`ats.py`](src/mba_mcp/ats.py): a URL pattern, a pure `parse_*` function, a saved fixture, a test.
- **Add a track.** Tech and unstructured/off-cycle are unwritten. Copy [`timelines/investment_banking.json`](src/mba_mcp/timelines/investment_banking.json) and cite where the dates come from.
- **Add a non-US calendar.** LBS, INSEAD and HKUST run different cycles and nobody has written them down.
- **Improve warm-path ranking.** [`score_contact`](src/mba_mcp/connections.py) is deliberately simple and explains itself. Subsidiaries, rebrands and seniority signals could all be smarter.
- **Improve a starter pack.** [`presets/`](src/mba_mcp/presets/) — add firms, fix a careers URL that moved.

```bash
pip install -e '.[dev]'
pytest                              # 148 tests, fully offline
python scripts/build_mcpb.py        # build the Desktop bundle
```

Tests never touch the network: ATS adapters run against saved fixtures, and the guardrails have their own tests asserting that nothing sends without confirmation. `tests/test_server.py` fails loudly on any accidental network call. Please keep both true.

<details>
<summary>Manual checklist for the Gmail path</summary>

Automated tests can't cover a real send. Once, by hand:

- [ ] `mba-mcp auth` opens consent and writes `gmail_token.json` with `0600` permissions
- [ ] `send_email(draft_id, confirm=False)` returns the body and sends nothing
- [ ] `send_email(draft_id, confirm=True)` delivers exactly one message
- [ ] Sending the same draft twice is refused
- [ ] Revoking access in your Google account makes the next send fail cleanly
</details>

---

## Licence

MIT. Use it, fork it, run it for your whole class. See [LICENSE](LICENSE).
