<h1 align="center">mba-mcp</h1>

<p align="center">
  <strong>Run your recruiting campaign from inside Claude.</strong><br>
  Target firms, live job boards, cycle deadlines, warm intros, and cold emails you approve before they send.
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
| `MBA_MCP_BASE_CV` | `{data dir}/base_cv.md` | Your master CV, exposed to Claude for tailoring |
| `GMAIL_OAUTH_CLIENT_SECRET` | `{data dir}/gmail_client_secret.json` | Your own Google OAuth client |
| `ADZUNA_APP_ID` / `_KEY` | unset | Optional wider job search |

Anything you set in the app's settings UI wins over these; `set_profile` wins over both.
</details>

---

## What you can say

Just talk to Claude. These are examples, not commands to memorise.

| You say | What happens |
|---|---|
| *"I'm a Wharton MBA, class of 2028, recruiting for banking"* | Saves your profile — this is what makes alumni matching work |
| *"Set up my target list for banking"* | Adds 18 firms and resolves each one's live job board |
| *"Any new summer associate roles this week?"* | Sweeps every target's board, filtered |
| *"Where am I in the cycle?"* | Your track's timeline, projected onto today's date |
| *"Who do I know at Evercore?"* | Ranks your own connections, with the reason for each |
| *"Find me Wharton alumni at Evercore"* | Builds the LinkedIn searches for you to open |
| *"What's Priya's email likely to be?"* | Infers it from your firm's addresses you already have |
| *"Draft a note to her, then send it"* | Claude writes it, shows you, sends one message after you say yes |
| *"What's due this week?"* | Overdue follow-ups and approaching deadlines |

**A day in the campaign**

```
Morning   "What's due?"              → 3 follow-ups overdue, Bain deadline in 9 days
          "Draft the Priya one"      → Claude reads your last chat notes, writes it
          "Send"                     → shows you the text → one email, from your Gmail
Evening   "Add today's coffee chat"  → logged, next follow-up set for the 14th
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

## Sending email (optional)

Only needed if you want Claude to actually send. Skip it and drafts still work.

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project and enable the **Gmail API**.
2. OAuth consent screen → **External**, leave it in **Testing**, add your own address as a test user. Testing mode works for you personally with no Google review.
3. Create an **OAuth client ID** → **Desktop app** → download the JSON → save it to your data dir.
4. Once, from a terminal: `mba-mcp auth`

Only `gmail.send` is requested. This code cannot read your mail.

---

## Everything it can do

<details open>
<summary><strong>19 tools</strong></summary>

**You** · `set_profile`

**Targets & jobs** · `add_target_company` · `add_target_pack` · `list_target_packs` · `list_targets` · `find_jobs`

**Pipeline & timing** · `track_application` · `update_application` · `list_applications` · `get_recruiting_timeline`

**Networking** · `import_connections` · `find_warm_paths` · `find_alumni` · `log_interaction` · `get_followups`

**Outreach** · `suggest_email` · `set_contact_email` · `save_outreach_draft` · `send_email`

**Resources** (state Claude can read at any time) · `profile` · `targets` · `pipeline` · `contacts` · `timeline` · `base_cv`
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
pytest                              # 140 tests, fully offline
python scripts/build_mcpb.py        # build the Desktop bundle
```

Tests never touch the network: ATS adapters run against saved fixtures, and the guardrails have their own tests asserting that nothing sends without confirmation. Please keep both true.

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
