# Charon — Requirements & Project Plan

> *"Getting you to the other side."*

Charon is a CLI tool for job seekers who are tired of ghost jobs, toxic workplaces, and corporate doublespeak. It helps you evaluate job postings and research companies against your personal values — so you stop wasting time on opportunities that were never real or never right.

Named after the ferryman of the underworld. Because job hunting is already hell.

---

## Aesthetic & Personality

- Metasploit-style ASCII CLI — structured, purposeful, no fluff
- Dark humor is welcome, but the tool is serious and useful
- Output should feel like a security tool, not a job board
- Color: use rich/click with red for bad signals, yellow for warnings, green for good signals
- Every command should feel like it belongs in a toolkit alongside nmap and metasploit

---

## Tech Stack

- **Language:** Python 3.11+
- **CLI framework:** Click or Typer
- **Output formatting:** Rich (tables, colors, progress bars)
- **AI backbone:** Anthropic Claude API (claude-sonnet-4-20250514) for all judgment-based analysis
- **HTTP/scraping:** httpx + BeautifulSoup for fetching job posting URLs
- **Email:** Python smtplib using user's own mail server
- **Config:** YAML profile file at `~/.charon/profile.yaml`
- **Storage:** SQLite at `~/.charon/charon.db` for history, watchlist, and daily digest queuing
- **Package:** pyproject.toml, installable via `pip install charon-jobs` (or similar)

---

## CLI Commands

```
charon ghostbust  --url <url> | --paste
charon redflags   --url <url> | --paste
charon dossier    --company <name>
charon hunt       --url <url> | --paste   # full pipeline: ghostbust → redflags → dossier
charon applied    --add --company <name> --role <title> [--url <url>] [--notes <text>]
charon applied    --list [--company <name>] [--status <status>]
charon applied    --update <id> --status <status>
charon applied    --stats
charon watch      --add <company> | --list | --remove <company>
charon digest     --send                  # manually trigger email digest
charon profile    --edit | --show         # manage your profile
charon history    --list | --clear        # view past runs
charon dashboard                          # launch local HTML dashboard
charon dashboard  --port 8080             # custom port
```

### `charon ghostbust`
Analyzes a job posting for ghost job signals. Accepts a URL (fetches and parses it) or `--paste` to accept stdin/multiline paste.

**Scores and reports on:**
- Posting age (if detectable)
- Vagueness of description (no team details, no manager info, no real project context)
- Salary transparency (missing = red flag)
- Whether role appears on company's own careers page (cross-reference)
- Language patterns common in ghost postings
- Whether the same or similar role is posted repeatedly

**Output:** Ghost likelihood score (0-100%), confidence level, and bullet-point breakdown of signals found.

---

### `charon redflags`
Analyzes a job posting for toxic workplace and bad-fit signals. Uses Claude with AI judgment — not keyword matching. The AI understands obfuscated language and HR euphemisms.

**Three-tier flag system:**

- 🔴 **Dealbreakers** — instant disqualifiers, pulled from user profile
- 🟡 **Yellow flags** — lower the score, flagged for user attention
- 🟢 **Green flags** — positive signals that boost score, pulled from user profile

**The AI is explicitly instructed to detect obfuscated versions of dealbreakers.** For example:
- "follow-the-sun model" = overnight shift work
- "collaborative in-person culture" = RTO incoming  
- "occasional travel to HQ" = soft relocation pressure
- "local candidates strongly preferred" = not actually remote-friendly
- "core hours 9-5 EST" = rigid schedule, not async-friendly

**Output:** Flag report grouped by tier, overall red flag score, and a plain-English summary of concerns.

---

### `charon dossier`
Researches a company and scores it against the user's weighted values profile. Uses Claude with web search to compile a dossier.

**Researches:**
- Security culture signals (CISO reporting structure, bug bounty, breach response history, open source security contributions, CVE transparency)
- People treatment (Glassdoor/Blind/Indeed review themes, layoff history and how it was handled, leadership turnover, employee tenure patterns)
- Leadership transparency (do leaders communicate openly? any "we won't have layoffs" followed by quiet exits? nepotism signals?)
- Work-life balance (review signals, on-call expectations, PTO culture)
- Compensation transparency (do they publish ranges? equity structure?)
- Remote culture (truly remote or remote-ish?)

**Weighted scoring:** Each dimension is scored and weighted according to the user's `profile.yaml` values weights. Produces a single 0-100 values-alignment score plus a per-dimension breakdown.

**Output:** Full dossier report with score, dimension breakdown, key evidence cited, and a plain-English verdict. Saveable to file with `--save`.

---

### `charon hunt`
Full pipeline. Runs `ghostbust` → `redflags` → `dossier` in sequence. If ghostbust score is above the disqualify threshold, stops early and tells you why. Otherwise proceeds through all three and gives a combined report.

Before running, checks the `applied` log. If the user has already applied to a role at the same company, warns them:
`⚠️  You applied to a role at [Company] on [date]. This may be a duplicate — continue? [y/N]`

**Output:** Combined report with all three analyses, an overall "worth applying?" verdict, and a confidence level.

---

### `charon applied`
Tracks job applications to avoid duplicates and maintain a personal pipeline log.

```
charon applied --add --company "Netflix" --role "Security Engineer" --url "https://..."
charon applied --list
charon applied --list --company "Netflix"
charon applied --list --status interviewing
charon applied --update <id> --status rejected
charon applied --stats
```

**Stored fields:** company, role, url, date_applied, notes (optional), status (default: `applied`)

**Statuses:** `applied`, `responded`, `interviewing`, `offered`, `rejected`, `ghosted`

**Duplicate detection:** When `ghostbust`, `redflags`, `hunt`, or `dossier` is run, Charon automatically checks the applied log. If the same company already has an entry, it warns the user before proceeding. Does not hard-block — just flags it clearly.

**Auto-links:** When adding an application for a URL you've already run through `ghostbust`/`redflags`, Charon links those results to the application record automatically.

**Stats output (`--stats`):** Pipeline funnel — applied → responded → interviewing → offered, plus rejection rate and ghost rate.

**Output:** Rich table with color-coded statuses. Ghosted entries dimmed. Active pipeline highlighted.

---

### `charon dashboard` *(Phase 6)*
Launches a locally-hosted interactive HTML dashboard. Opens in the default browser at `http://localhost:7777`.

```
charon dashboard            # start server, open browser
charon dashboard --port 8080
```

Press Ctrl+C to stop.

**What it shows:**
- Application pipeline — all tracked applications with status, color-coded, filterable by status/company
- Dossier library — saved company dossiers with scores and key findings
- Ghost job history — past ghostbust results with scores
- Red flag history — past redflags results
- Daily activity feed — what Charon has run recently
- Stats panel — application funnel, response rate, ghost rate, ghost job encounter rate

**Aesthetic:** Dark terminal-inspired theme. Monospace fonts. Green/amber/red status colors. Feels like a security operations dashboard — think SOC analyst's personal ops center, not a job board. Should be visually distinctive and purpose-built. Single HTML file with embedded CSS and JS.

**Implementation:** Lightweight Python HTTP server (stdlib `http.server` or FastAPI). Dashboard reads directly from `~/.charon/charon.db`. No external services, no cloud, entirely local.

**Data is read-only from the dashboard** — all writes happen through the CLI.

---

### `charon watch` *(Phase 4 — implement last)*
Maintains a watchlist of target companies. A background-compatible command (or cron-friendly) that checks for new job postings at watched companies and queues them for the daily digest.

---

### `charon digest`
Sends or previews the daily email digest. The digest covers:
1. Any `charon` commands run that day with their results summarized
2. New job postings found at watched companies (Phase 4)

**Logic:** Only sends if there is something to report. Silent days = no email. No weekly digest — the daily handles everything, and silence is fine.

---

## User Profile (`~/.charon/profile.yaml`)

```yaml
# Charon User Profile
# Values weights must sum to 1.0

values:
  security_culture: 0.30        # Does the company actually take security seriously?
  people_treatment: 0.25        # Are employees treated like humans, not fuel?
  leadership_transparency: 0.20 # Does leadership communicate honestly?
  work_life_balance: 0.15       # Is sustainable work pace supported?
  compensation: 0.10            # Is comp fair and transparent?

dealbreakers:
  - "requires or strongly implies on-site work or relocation"
  - "shift work, overnight hours, or on-call rotation required"
  - "no salary or compensation range provided anywhere in posting"
  - "remote work not available, not mentioned, or clearly not genuine"
  - "rigid core hours inconsistent with async/flexible work"

yellow_flags:
  - "heavy synchronous meeting culture or real-time availability expectations"
  - "fast-paced, high-pressure, or hustle language"
  - "strong preference for local candidates"
  - "unlimited PTO without supporting context"
  - "like a family culture language"

green_flags:
  - "async-first or results-oriented work culture"
  - "explicitly flexible or self-directed schedule"
  - "transparent salary range included in posting"
  - "security team has organizational authority"
  - "genuine remote-first culture with documented practices"

target_roles:
  - "AI red team"
  - "LLM security"
  - "AI security researcher"
  - "application security"
  - "penetration tester"
  - "offensive security"

notifications:
  enabled: true
  mail_server: "smtp.yourmailserver.com"
  mail_port: 587
  mail_from: "charon@yourdomain.com"
  mail_to: "you@yourdomain.com"
  mail_user: ""       # fill in if auth required
  mail_pass: ""       # fill in if auth required

ghostbust:
  disqualify_threshold: 70    # ghost likelihood % above which hunt pipeline stops

dossier:
  save_path: "~/.charon/dossiers/"

applications:
  ghosted_after_days: 21      # days of silence before flagging as ghosted

dashboard:
  port: 7777
  auto_open_browser: true
```

---

## Build Order (Phases)

### Phase 0 — Scaffolding
- Repo structure, pyproject.toml, CLI entry point
- Profile loading/validation
- SQLite history, watchlist, and applications database schema
- `charon profile --show` and `--edit` working
- Rich output helpers (colors, tables, score bars)

### Phase 1 — `charon ghostbust`
- URL fetching and text extraction
- `--paste` mode
- Claude-powered ghost job analysis
- Score output with breakdown
- Save result to history

### Phase 2 — `charon redflags`
- Reuse fetched text from ghostbust where possible
- Claude-powered red flag analysis using profile dealbreakers/yellow/green
- AI judgment mode — no keyword matching, intent-based detection
- Three-tier flag output
- Save result to history

### Phase 2.5 — `charon applied`
- SQLite `applications` table
- `--add`, `--list`, `--update`, `--stats` subcommands
- Duplicate detection hook (warns when ghostbust/redflags/hunt/dossier targets a company already in log)
- Auto-link to existing ghostbust/redflags results by URL
- Rich table output with color-coded statuses

### Phase 3 — `charon dossier`
- Company name input
- Claude with web search for research
- Weighted scoring against profile values including DEI resilience sub-dimension under `people_treatment`
- Full dossier output with evidence cited per dimension
- `--save` to markdown file
- Save result to history

### Phase 3.5 — `charon hunt`
- Pipeline orchestration of ghostbust → redflags → dossier
- Early exit logic on high ghost score
- Applied log duplicate check before running
- Combined report output

### Phase 4 — `charon watch` + `charon digest`
- Watchlist CRUD
- Job posting crawler (per-company careers pages or LinkedIn)
- Daily digest email generation
- `charon digest --send` and `--preview`

### Phase 5 — `charon inbox`
- Application tracker auto-status updates via IMAP inbox monitoring
- AI-powered email classification (rejection, interview, follow-up, auto-ack)
- Auto-ghost detection after configurable timeout (default: 21 days)
- Digest integration: responses highlighted at top of daily digest

### Phase 6 — `charon dashboard`
- Local HTML dashboard served via Python HTTP server
- Dark SOC-style aesthetic — terminal-inspired, monospace, purpose-built
- Application pipeline view with color-coded statuses, filterable
- Dossier library with scores and key findings
- History views for ghostbust and redflags runs
- Stats panel: funnel, response rate, ghost rate
- Read-only — all data writes happen through CLI
- Single HTML file with embedded CSS/JS

---

## CLI Commands — Phase 5

### `charon apply`
Tracks job applications through their full lifecycle.

```
charon apply --add --company <name> --role <title> [--url <posting_url>]
charon apply --list [--status <status>]
charon apply --update <id> --status <status>
charon apply --stats
```

**Statuses:** `applied`, `responded`, `interviewing`, `offered`, `rejected`, `ghosted`

**Features:**
- Auto-links to existing ghostbust/redflags/dossier results if you ran them for the same posting
- Stores application date, company, role, posting URL, status, and notes
- `--stats` shows pipeline funnel (applied -> responded -> interviewing -> offered, plus rejection/ghost rates)

### `charon inbox`
Monitors Gmail for responses to tracked applications.

```
charon inbox --scan              # scan inbox now
charon inbox --setup             # IMAP setup instructions
charon inbox --status            # show connection status
```

**How it works:**
1. Connects to configured IMAP accounts (read-only)
2. Searches for emails from/about companies with active applications
3. Uses Claude to classify emails: rejection, interview invite, follow-up, auto-acknowledgment
4. Auto-updates application status based on classification (interview->interviewing, rejection->rejected, offer->offered, acknowledgment->responded)
5. Queues notable responses for the daily digest

**Email domain matching:**
- Extracts domain from job posting URL when available
- Searches Gmail by company name (`from:companyname` or `subject:companyname`)
- User can optionally specify email domain when adding an application
- No external API dependency (no hunter.io account needed)

**Auto-ghost detection:**
- Configurable timeout in profile: `ghosted_after_days: 21`
- If no response detected after threshold, auto-marks application as `ghosted`
- Ghosted applications reported in daily digest

### Digest Integration (Phase 5 additions)
Company responses are **highlighted at the top** of the daily digest, above all other items. Format:

```
=== RESPONSES RECEIVED ===
[!] CrowdStrike replied RE: Sr Security Engineer - INTERVIEW INVITE
[!] Acme Corp replied RE: Pen Tester - REJECTION

=== Today's Activity ===
(regular digest items below)
```

Responses are emphasized but not over the top -- clear, prominent, factual.

---

## User Profile — Phase 5 additions

```yaml
applications:
  ghosted_after_days: 21        # days of silence before marking as ghosted

inbox:
  accounts:
    - name: gmail
      imap_server: imap.gmail.com
      imap_user: you@gmail.com
      # Password from Vault (charon/imap-gmail) or CHARON_IMAP_PASS_GMAIL env var

vault:
  url: "https://vault-address:8200"
  role_id: ""                   # AppRole auth (preferred)
  secret_id: ""
  ca_cert: "~/.charon/vault-ca.crt"
  mount: "secret"
  secret_prefix: "charon"
```

---

## Project Structure

```
charon/
├── charon/
│   ├── __init__.py
│   ├── cli.py              # Click/Typer entry point, all commands
│   ├── profile.py          # Profile loading, validation, defaults
│   ├── db.py               # SQLite history, watchlist, and applications
│   ├── fetcher.py          # URL fetching and text extraction
│   ├── ai.py               # All Claude API calls
│   ├── ghostbust.py        # Ghost job analysis logic
│   ├── redflags.py         # Red flag analysis logic
│   ├── dossier.py          # Company dossier logic (includes DEI dimension)
│   ├── hunt.py             # Pipeline orchestration
│   ├── applied.py          # Application tracking (Phase 2.5)
│   ├── watch.py            # Watchlist and crawler (Phase 4)
│   ├── digest.py           # Email digest (Phase 4)
│   ├── inbox.py            # IMAP inbox monitoring (Phase 5)
│   ├── dashboard.py        # Local HTML dashboard server (Phase 6)
│   └── output.py           # Rich formatting helpers
├── charon/templates/
│   └── dashboard.html      # Dashboard single-file HTML/CSS/JS
├── tests/
├── docs/
├── REQUIREMENTS.md         # This file
├── RESPONSIBLE_USE.md
├── README.md
├── pyproject.toml
└── .gitignore
```

---

## AI Prompt Design Notes

All Claude API calls should:
- Use `claude-sonnet-4-20250514`
- Include the user's profile values and dealbreakers as context
- Request structured JSON output for scoring (parse into Rich display)
- Include explicit instructions to detect obfuscated/euphemistic language
- For `redflags`: instruct the model to explain *why* each flag was triggered, not just that it was
- For `dossier`: instruct the model to cite specific evidence for each dimension score
- Temperature: low (0.2-0.3) for consistency in scoring

---

## Notes for Claude Code

- Build phases sequentially — Phase 0 first, get it working before moving on
- Each phase should be functional and testable before proceeding
- Prioritize a good user experience in the CLI output — this tool will be used while actively stressed about job hunting, so clarity matters
- The AI judgment approach for dealbreakers is intentional and important — do not replace with keyword/regex matching
- The profile file is the user's most important configuration — make it easy to understand and edit
- Keep the dark ferryman aesthetic consistent in any user-facing copy, help text, and error messages
- The dashboard (Phase 6) should feel like a SOC operations dashboard — dark, terminal-inspired, purpose-built. Think security professional's personal ops center, not a job board. Single HTML file with embedded CSS/JS. No Bootstrap, no generic UI kit aesthetics.
- RESPONSIBLE_USE.md should note this tool is for personal job searching only
