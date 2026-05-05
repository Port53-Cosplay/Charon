# Charon How-To Guide

> "Getting you to the other side."

Quick reference for using Charon day-to-day. Run all commands from any terminal.

---

## Quick Start

```bash
# Make sure you're in the project directory (or charon is installed)
cd /path/to/charon

# Check your profile is set up
charon profile --show

# Run your first analysis on a job posting
charon hunt --url https://example.com/job-posting
```

---

## The Workflow

When you find a job posting you're interested in:

### 1. Run the full pipeline on the posting

```bash
charon hunt --url https://careers.crowdstrike.com/job/12345
```

This runs in two phases:

**Phase 1 (Recon):**
- **Ghostbust** - Is this even a real job, or a ghost posting?
- **Redflags** - Does the posting have toxic workplace signals?
- **Role Alignment** - How closely does this match your target roles (AI red team, pentesting, IR, etc.)?

**Phase 2 (Dossier - only if you approve):**
- **Company Dossier** - Deep research on the company against your values

After recon, you see the results and decide if it's worth running a dossier. Use `--full` to skip the confirmation and run everything automatically.

If the ghost score is above 70%, it stops early and tells you not to bother.

### 2. If it looks good, track your application

```bash
charon apply --add --company "CrowdStrike" --role "Sr Security Engineer" --url https://careers.crowdstrike.com/job/12345
```

This records the application with today's date and extracts the company's email domain from the URL (used for inbox scanning later).

You can add notes too:

```bash
charon apply --add --company "Rapid7" --role "AI Red Team" --url https://rapid7.com/careers/456 --notes "Applied via you@example.com"
```

### 3. Let the automation work

Every morning at 6am, the ops server:
- Syncs your application database
- Scans your Gmail for responses from companies you've applied to
- Auto-updates statuses (interview invite, rejection, offer, acknowledgment)
- Marks applications as ghosted after 21 days of silence
- Emails you a digest if anything happened

You don't need to do anything for this part. It just runs.

### 4. Check your application status anytime

```bash
# See all applications
charon apply --list

# Filter by status
charon apply --list --status applied
charon apply --list --status interviewing
charon apply --list --status rejected
charon apply --list --status ghosted

# See your funnel stats
charon apply --stats
```

---

## Individual Commands

### Analyze a Job Posting (Quick)

If you just want one analysis instead of the full pipeline:

```bash
# Ghost job detection only
charon ghostbust --url https://example.com/job

# Red flag scan only
charon redflags --url https://example.com/job

# Company research only
charon dossier --company "CrowdStrike"
charon dossier --company "Palo Alto Networks" --save    # saves to ~/.charon/dossiers/
```

### Paste Mode

If the job posting is behind a login wall or you have the text copied:

```bash
charon ghostbust --paste
charon redflags --paste
charon hunt --paste
```

This opens a paste prompt. Paste the job posting text, then press Ctrl+Z followed by Enter (Windows) to submit.

**Recommended: Save to a file first.** Pasting directly into PowerShell can break on
special characters (`$`, commas, parentheses). Instead, save the posting to a `.txt` file
(e.g. in Notepad) and pipe it in:

```bash
Get-Content posting.txt | charon hunt --paste
Get-Content posting.txt | charon ghostbust --paste
Get-Content posting.txt | charon redflags --paste
```

This avoids shell interpretation issues and works reliably every time.

### Update an Application Manually

```bash
# Update status (if you hear back before the scanner catches it)
charon apply --id 3 --status interviewing

# Valid statuses: applied, acknowledged, responded, interviewing, offered, rejected, ghosted
```

### Check for Ghosted Applications

```bash
charon apply --ghost-check
```

Marks any application with 21+ days of silence as ghosted. The daily scanner does this automatically, but you can run it manually too.

### Scan Your Inbox Manually

```bash
# Scan Gmail for responses (last 7 days)
charon inbox --scan

# Scan further back
charon inbox --scan --days 14

# Check IMAP connection status
charon inbox --status

# See setup instructions
charon inbox --setup
```

### Gather Jobs from ATS Boards

`charon gather` polls public ATS APIs (Greenhouse, Lever, Ashby, Workday) for
the curated employer list in `config/companies.yaml` and writes new postings
to the `discoveries` table. No LinkedIn, no aggregator scraping.

```bash
# See who's configured
charon gather --list

# Poll one employer
charon gather --slug datadog
charon gather --slug vanta --dry-run     # preview without writing

# Poll one ATS
charon gather --ats greenhouse

# Poll everything
charon gather

# One-shot for an employer not in companies.yaml
# (does NOT add it to the registry; just runs that adapter once)
charon gather --add https://boards.greenhouse.io/airbnb
charon gather --add https://jobs.lever.co/sysdig --dry-run
charon gather --add https://crowdstrike.wd5.myworkdayjobs.com/en-US/crowdstrikecareers

# Slug + ATS fallback when URL doesn't auto-detect
charon gather --add datadog --ats greenhouse
```

Notes:
- Companies already in your `applications` table (active statuses only) are
  skipped automatically — no point re-discovering jobs you've applied to.
- Dedupe is by URL hash, scoped per ATS. Re-running is safe.
- Workday descriptions are intentionally left blank in this phase. Phase 7
  (`enrich`, not yet shipped) will fill in full descriptions.
- The registry tracks ~47 verified employers. To add more permanently, edit
  `config/companies.yaml` directly with `slug`, `name`, `tier`, `category`.

### Enrich Discoveries

`charon enrich` fills in `discoveries.full_description` via a three-tier cascade:

1. **JSON-LD** — parse schema.org `JobPosting` from the page's structured data. Free, generic, catches Workday and most SEO-conscious careers pages.
2. **ATS-specific CSS** — per-ATS selectors for the description region. Free, runs only if tier 1 misses.
3. **LLM** — last resort. Sends cleaned page text to a chat model and asks for the description. Default `claude-haiku-4-5`. Override via profile.

```bash
# One discovery
charon enrich --id 5

# All unenriched
charon enrich --all

# Slice by ATS (Workday is the main use case — Greenhouse/Lever/Ashby usually
# already have descriptions populated by the gather step and get marked 'skipped')
charon enrich --all --ats workday

# Re-enrich everything (e.g. after changing the model)
charon enrich --all --force

# See tier hit rates
charon enrich --stats
```

**Picking a model.** Default is `claude-haiku-4-5` via the native Anthropic SDK. To swap:

```yaml
# in ~/.charon/profile.yaml
enrich:
  model: openrouter:google/gemini-flash-2-0   # cheaper
  # model: openrouter:deepseek/deepseek-chat   # also cheap
  # model: claude-sonnet-4-5                   # higher quality, more $
  skip_threshold: 500           # skip enrich if source description >= this many chars
  rate_limit_seconds: 1.0       # politeness delay between page fetches
```

OpenRouter routing needs an API key. Either set `OPENROUTER_API_KEY` env var, or store it in Vault at `<secret_prefix>/openrouter-api` (key `api_key`).

### Judge Discoveries

After `gather` and `enrich`, `charon judge` runs the existing v1 analyzers
(ghostbust, redflags, role_alignment) on each discovery and assigns a
combined score. Discoveries above the threshold are marked `ready`;
the rest are `rejected` with a one-line reason.

```bash
# One discovery
charon judge --id 5

# All unjudged (must be enriched first)
charon judge --all

# Slice by ATS
charon judge --all --ats workday

# Tougher threshold for this run
charon judge --all --threshold 75

# Force re-judge after editing your profile (e.g. new dealbreakers)
charon judge --rejudge --id 5
charon judge --rejudge --all

# Re-judge ONLY the currently-ready ones (cheaper than --rejudge --all)
charon judge --rejudge --status ready --ats lever

# Free re-gating after tuning thresholds (no AI calls)
charon judge --reclassify

# Browse the funnel
charon judge --list ready          # everything that passed
charon judge --list rejected       # everything that failed (with reasons)
charon judge --stats               # counts by status
charon judge --by-company          # aggregates per company
```

**Cost.** Each judgement is 3-4 Claude Sonnet calls — roughly $0.02-$0.07
per discovery (4th call is the resume analyzer when configured). Charon warns
before judging more than 50 at once and shows a cost estimate.

**Tuning gates without paying.** Once a discovery has been judged once, its
component scores are stored. `charon judge --reclassify` re-applies the
ready/rejected gating with the current profile values — useful after editing
`ready_threshold`, `alignment_floor`, or `weights`. Free, instant.

```yaml
# in ~/.charon/profile.yaml
resume_path: ~/.charon/resume.md   # or a directory; first md/txt/docx/pdf wins
judge:
  ready_threshold: 60        # combined score required to mark `ready`
  alignment_floor: 50        # hard reject if alignment_score < this
  bulk_warn_at: 50           # confirmation prompt above this many at once
  weights:                   # how the four components blend
    ghost: 0.15              # invert: low=good
    redflag: 0.20            # invert: low=good
    role_alignment: 0.25     # what you want to do
    resume_match: 0.40       # what you've actually done — heaviest by default
```

**The combined score** is a weighted blend of the four components on a 0-100
scale (higher is better):

```
combined = (
    w_g * (100 - ghost_score) +
    w_r * (100 - redflag_score) +
    w_a * alignment_score +
    w_m * resume_match_score
) / sum(weights)
```

Rows judged before `resume_match` was introduced fall back to a 3-component
formula automatically. The dossier dimension is NOT part of the combined
score — dossier runs per-job in Phase 9, when you decide to actually apply.

**Resume match analyzer.** When `resume_path` is set, the 4th analyzer
compares the posting's stated requirements against your actual resume.
Different from `role_alignment`: that compares against your aspirational
`target_roles`. Resume match catches the case where a posting is at a
security company and gets a charitable role_alignment score, but the
day-to-day work doesn't match your background (classic example: a Sales
Solutions Engineer scoring 75 alignment + 25 resume match = correctly
rejected). Supports `.md`, `.txt`, `.pdf`, `.docx`.

**By-company view.** `charon judge --by-company` aggregates judged rows
per employer — total / ready / rejected counts plus average scores per
component. Useful for spotting whether a flagged company is a one-bad-
listing accident or a consistent pattern.

**Re-judge survivors.** After tuning prompts or adding the resume
analyzer, you can re-score just the currently-ready discoveries instead
of every row:

```bash
charon judge --rejudge --status ready --ats lever
```

That re-runs all analyzers on each currently-ready row and may flip some
to rejected. Cheaper than `--rejudge --all` because the rejected pile
stays rejected.

### Forge Tailored Resumes

After `judge` marks discoveries `ready`, `charon forge` produces a posting-
specific resume in markdown. The AI may reorder, regroup, and reframe your
existing experience to match the role's vocabulary, but it can't invent —
a post-generation verifier extracts every numerical claim from the output
and confirms each appears in your source resume.

```bash
# Forge one ready discovery (writes to ~/.charon/offerings/<company>-<role>-<id>/)
charon forge --id 2607

# Forge all unforged ready discoveries
charon forge --ready
charon forge --ready --ats lever      # slice by ATS

# Re-forge after editing your resume / profile / prompt
charon forge --id 2607 --force

# Override the model for one run (e.g. upgrade to Sonnet)
charon forge --id 2607 --model claude-sonnet-4-20250514

# Or via OpenRouter
charon forge --ready --model openrouter:google/gemini-flash-2-0
```

Each forge writes two files into the offerings folder:

- **`resume.md`** — the tailored resume itself
- **`prompt_used.md`** — full audit trail: model, token usage, system prompt,
  user prompt, raw output, verifier results (any unverified numerical claims
  flagged here)

**The verifier.** After generation, every number in the output (counts,
percentages, years, thousands-separator numbers like `10,000`) must appear in
the source resume under one of several normalizations (with/without commas,
with/without `%`, "30 percent" written-out form). Unverified items show in
the CLI as a yellow warning and in `prompt_used.md` as a marked section.
**The output is still written** — you read the resume yourself before
submitting anything. The verifier is for catching obvious fabrication
(`reduced incidents by 99%` when nothing in your resume mentions 99 or
99%), not for blocking edge cases.

**Cost.** Forge is a single API call per discovery. On Claude Haiku 4.5
(the default), expect ~$0.005-$0.02 per discovery. Charon warns and asks
before running on more than 20 at once with a cost estimate.

**Configure forge.** In `~/.charon/profile.yaml`:

```yaml
resume_path: ~/.charon/resume.md   # or a directory; first md/txt/docx/pdf wins
forge:
  model: claude-haiku-4-5          # default. claude-sonnet-* for higher quality.
                                   # openrouter:vendor/model also supported.
  max_tokens: 4096
  offerings_dir: ~/.charon/offerings
```

### Petition (Cover Letters)

`charon petition` writes a tailored cover letter per ready discovery. The
letter and the forged resume share the same offerings folder, so the two
materials always travel together. The system prompt is voice-tuned to avoid
sounding AI-generated — conversational over corporate, specific over
abstract, varied sentence length, banned phrases include the obvious
("passionate about," "I am writing to express my interest," "looking
forward to hearing from you," "team player," "leverage" as a verb) and
some less-obvious ones ("transferable skills," "proven track record").

```bash
# One ready discovery
charon petition --id 2607

# All unpetitioned ready discoveries
charon petition --ready

# Slice / cap / model override (same flags as forge)
charon petition --ready --ats lever
charon petition --id 2607 --force
charon petition --id 2607 --model claude-sonnet-4-20250514
```

The output:
- **`cover_letter.md`** — the letter
- **`petition_audit.md`** — model, tokens, prompts, raw output, verifier
  results

The same numerical verifier from `forge` runs on the cover letter — any
metric in the letter must trace back to your resume. **Geographic claims
are also banned** in the prompt itself: the letter cannot claim you're
located in or relocating to a city/country not on your resume. (This rule
exists because an early petition fabricated "I'm in the UK" when the
posting required UK residency. The corrected version honestly opened with
the location mismatch instead.)

If the verifier flags something, it logs the warning and writes the letter
anyway — you read it before submitting. **Read every cover letter before
sending it.** AI-written letters are obvious if you look. The voice-tuning
gets you 80% of the way there; the last 20% is editing for cadence and
specifics that only you know.

**Configure petition.** Petition shares forge's profile section (same model,
same tokens budget, same offerings dir):

```yaml
forge:
  model: claude-haiku-4-5    # used by both forge and petition
  max_tokens: 4096
  offerings_dir: ~/.charon/offerings
```

### Provision (Both Materials at Once)

`charon provision` is the convenience wrapper — it runs forge + petition
for a discovery in sequence, so you get both the resume and the cover
letter in one command.

```bash
# One ready discovery — produces resume.md AND cover_letter.md
charon provision --id 2607

# All ready discoveries that are missing materials (forge OR petition)
charon provision --ready

# Slice / cap / model override
charon provision --ready --ats lever
charon provision --ready --force          # regenerate everything
charon provision --id 2607 --model claude-sonnet-4-20250514
```

The two stages are independent — petition still runs even if forge
errors. The bulk-warn fires above 20 discoveries with a cost estimate
that reflects 2 calls per discovery (~$0.04-$0.10 each on Haiku).

### Browse Offerings

`charon offerings` lets you see and open the materials you've generated.

```bash
# Default: list everything you have
charon offerings

# One discovery's folder
charon offerings --id 2607

# Open the folder in your file manager
charon offerings --id 2607 --open
```

The `F` and `P` markers in the list view tell you whether each discovery
has been forged, petitioned, or both.

### Company Watchlist

```bash
# Add companies you're interested in
charon watch --add "CrowdStrike"
charon watch --add "Rapid7"

# See your watchlist
charon watch --list

# Remove one
charon watch --remove "Rapid7"
```

### Email Digest

```bash
# Preview what the digest would say
charon digest --preview

# Send it now
charon digest --send
```

### View the Hunt Log (The Toll)

```bash
# See all hunts (newest first)
charon toll

# Sort by score (best matches first)
charon toll --sort score

# Only today's hunts
charon toll --days 1

# Today's hunts, ranked by score
charon toll --days 1 --sort score

# Open the log file in your text editor
charon toll --open
```

### View History

```bash
# See past analyses
charon history --list
charon history --list --limit 50

# Clear history
charon history --clear
```

### Manage Your Profile

```bash
# View your profile (values, dealbreakers, flags, etc.)
charon profile --show

# Edit it in notepad
charon profile --edit

# Reset to defaults
charon profile --reset
```

---

## Typical Day-to-Day

**Hunt a batch of postings:**
```bash
charon hunt --url <url1>
charon hunt --url <url2>
charon hunt --url <url3>
# Skip dossiers — just recon. Review scores after.
```

**Review your results, best first:**
```bash
charon toll --sort score
```

**Apply to the best matches:**
```bash
charon apply --add --url <url> --company "<name>" --role "<title>"
```

**Run dossiers on the ones worth investigating:**
```bash
charon dossier --company "<name>"
```

**Check your pipeline:**
```bash
charon apply --list    # D column shows which have dossiers
charon apply --stats
```

**Everything else is automatic.** The morning scan handles inbox monitoring, ghost detection, and digest emails.

---

## Statuses Explained

| Status | Meaning | How it gets set |
|--------|---------|-----------------|
| `applied` | You submitted an application | You run `charon apply --add` |
| `acknowledged` | Receipt confirmed (auto-email from employer or job board) | Auto: inbox scanner detects "thanks for applying", "application sent", etc. |
| `responded` | Actual human reply from employer | Auto: inbox scanner detects non-automated response |
| `interviewing` | Interview scheduled/in progress | Auto: inbox scanner detects interview invite |
| `offered` | You received an offer | Auto: inbox scanner detects offer email |
| `rejected` | Application was declined | Auto: inbox scanner detects rejection email |
| `ghosted` | No response after 21 days | Auto: daily ghost check |

**Note:** `acknowledged` and `responded` are different. `acknowledged` means a machine
confirmed your application was received (job board auto-emails, employer ATS confirmations).
`responded` means an actual person replied. This distinction matters so you don't confuse
an auto-receipt with a real response.

You can always override any status manually with `charon apply --id <num> --status <status>`.

---

## Score Interpretation

### Ghost Score (lower is better)
- **0-25%** - Likely a real posting
- **26-50%** - Some concerns, probably real
- **51-75%** - Suspicious, multiple ghost indicators
- **76-100%** - Almost certainly a ghost job

### Red Flag Score (lower is better)
- **0-25%** - Clean, no major issues
- **26-50%** - Some yellow flags, investigate further
- **51-75%** - Significant concerns
- **76-100%** - Major red flags, dealbreakers found

### Dossier / Values Alignment (higher is better)
- **76-100** - Strong alignment with your values
- **51-75** - Decent, but check the weak areas
- **26-50** - Below average, significant concerns
- **0-25** - Poor alignment, probably not worth it

### Role Alignment Score (higher is better)
- **76-100** - Strong match to your target roles
- **51-75** - Partial match, could be a stepping stone
- **26-50** - Weak match, may not move you toward your goals
- **0-25** - Poor match, won't build the skills you want

### Hunt Combined Score (higher is better)
Averages all analyses into a single "worth applying?" score.

---

## Your Profile (what it controls)

Your profile lives at `~/.charon/profile.yaml`. Key sections:

- **values** - How much you care about each dimension (weights must sum to 1.0)
- **dealbreakers** - Instant disqualifiers (AI detects these even when obfuscated)
- **yellow_flags** - Concerning signals that lower the score
- **green_flags** - Positive signals that boost the score
- **target_roles** - The roles you want (used for role alignment scoring)
- **ghostbust.disqualify_threshold** - Ghost score % that stops the hunt pipeline (default: 70)
- **applications.ghosted_after_days** - Days before marking as ghosted (default: 21)

---

## Tips

- **Use `hunt` for most things.** It runs all three analyses and gives you a combined verdict. Only use individual commands when you want a deep dive on one aspect.
- **Always include `--url` when tracking applications.** Charon extracts the company's email domain from the posting URL, which helps the inbox scanner match responses.
- **Use a dedicated forwarding email when applying.** Replies forward to your monitored inbox, where the scanner picks them up.
- **Check `--stats` regularly.** It shows your application funnel — how many applied vs responded vs ghosted. Good for staying motivated (or adjusting strategy).
- **The dossier `--save` flag is useful.** Saves a markdown file you can reference later during interviews.

---

## Troubleshooting

```bash
# Check if charon is installed and working
charon --version

# Check your profile for errors
charon profile --show

# Test inbox connection
charon inbox --status

# If commands fail with import errors
pip install -e ".[dev]"
```

---

*The ferryman remembers all. Every crossing, every judgment, every ghost exposed.*
