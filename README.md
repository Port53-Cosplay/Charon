```
   ___ _                          
  / __\ |__   __ _ _ __ ___  _ __  
 / /  | '_ \ / _` | '__/ _ \| '_ \ 
/ /___| | | | (_| | | | (_) | | | |
\____/|_| |_|\__,_|_|  \___/|_| |_|
                                   
            Getting you to the other side.
```

> A CLI tool for job seekers who are tired of ghost jobs, toxic workplaces, and corporate doublespeak.

Named after the ferryman of the underworld. Because job hunting is already hell.

**Current version:** v0.5.0 (Phases 0–5 shipped). v2 work in progress — see [ROADMAP.md](ROADMAP.md).

---

## What it does

Charon evaluates job postings and researches companies against *your* values, not generic "good fit" heuristics. It tells you whether a posting is real, whether the workplace looks toxic, whether the role actually moves your career where you want it, and what kind of company is behind it. Then it tracks your applications and watches your inbox for replies so you don't have to.

It runs on AI judgment, not keyword matching. The AI is told what your dealbreakers are, then asked to spot them even when they're dressed up in HR euphemisms ("collaborative in-person culture" = RTO, "follow-the-sun model" = shift work, "like a family" = run).

---

## Install

```bash
git clone https://github.com/Pickle-Pixel/Charon.git
cd Charon
python -m venv .venv
source .venv/Scripts/activate   # Windows
# source .venv/bin/activate     # Linux/Mac
pip install -e ".[dev]"
```

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your-key-here
```

Set up your profile (values, dealbreakers, target roles):

```bash
charon profile --edit
charon profile --show
```

For the full setup walkthrough including IMAP, Vault, and the daily ops scanner, see [HOWTO.md](HOWTO.md).

---

## The commands

### Analysis

```bash
charon ghostbust --url <url>     # ghost job detection
charon redflags  --url <url>     # toxic workplace scanner
charon dossier   --company <name>   # company research vs. your values
charon hunt      --url <url>     # full pipeline: ghostbust + redflags + role alignment
charon hunt      --url <url> --full   # also run the dossier
```

All four accept `--paste` for postings behind login walls. Pipe from a file on Windows to avoid PowerShell quoting issues:

```bash
Get-Content posting.txt | charon hunt --paste
```

### Funnel (gather → enrich → judge → provision → render → manifest)

```bash
charon funnel                            # cheat sheet: every step with examples
charon gather --slug <employer>          # pull jobs from one ATS
charon enrich --all                      # fill in full descriptions
charon judge --all                       # score ghost + redflag + alignment + resume
charon judge --list ready                # score-sorted apply-to-these list
charon provision --id <N>                # forge + petition + auto-render for one ready job
charon render --id <N>                   # re-render an offering's .md to .html
charon contacts --id <N>                 # surface LinkedIn contacts for the role
charon manifest                          # open the dashboard in your browser
```

### Application tracking

```bash
charon apply --add --company "<name>" --role "<title>" --url <url>
charon apply --list                      # all tracked applications
charon apply --list --status interviewing
charon apply --update <id> --status rejected
charon apply --stats                     # funnel stats
charon apply --ghost-check               # mark stale apps as ghosted
```

### Inbox monitoring

```bash
charon inbox --scan                # check Gmail for replies
charon inbox --scan --days 14
charon inbox --status              # IMAP connection check
charon inbox --setup               # setup instructions
```

The scanner reads-only, classifies emails with AI (rejection / interview / acknowledgment / response), and auto-updates application status.

### Daily digest

```bash
charon digest --preview
charon digest --send
```

### Hunt log (the toll)

```bash
charon toll                # all hunts, newest first
charon toll --sort score   # ranked by combined score
charon toll --days 1       # today only
charon toll --open         # open the log file
```

### Watchlist

```bash
charon watch --add "CrowdStrike"
charon watch --list
charon watch --remove "CrowdStrike"
```

### Profile and history

```bash
charon profile --show | --edit | --reset
charon history --list
charon history --clear
```

---

## How the scoring works

Lower is better for ghost and red flag scores. Higher is better for alignment scores.

| Score | Range | Meaning |
|---|---|---|
| Ghost likelihood | 0–100% (lower better) | How likely this is a ghost posting |
| Red flags | 0–100% (lower better) | Toxic / dealbreaker signal density |
| Values alignment (dossier) | 0–100 (higher better) | Company match against your weighted values |
| Role alignment | 0–100 (higher better) | Role match against your target career direction |
| Hunt combined | 0–100 (higher better) | Weighted combined "worth applying?" score |

The role alignment scorer is **discipline-aware**. A "Security Engineer" posting that's 80% Terraform isn't the same as a pen test role, and Charon scores them differently even when keyword overlap looks identical.

---

## What's running automatically

If you've deployed the daily ops scanner (see HOWTO.md), every morning it:

- Pulls your local Charon DB to the source-of-truth server
- Scans your Gmail for new replies from companies you've applied to
- Auto-updates application statuses
- Marks applications as ghosted after 21 days of silence
- Emails you a digest if anything happened

Silent days = no email. The digest only fires when there's something worth knowing.

---

## Profile

Lives at `~/.charon/profile.yaml`. See `profile.yaml.example` for a starter. Key sections:

- **values** — weighted dimensions (security culture, people treatment, leadership transparency, work-life balance, compensation). Weights sum to 1.0.
- **dealbreakers** — instant disqualifiers. AI detects these even when obfuscated.
- **yellow_flags** / **green_flags** — concerns and positives.
- **target_roles** — what career direction you're aiming for. Drives role alignment.
- **ghostbust.disqualify_threshold** — ghost score % at which `hunt` stops early.
- **applications.ghosted_after_days** — silence threshold (default 21).
- **inbox** — IMAP accounts to scan.
- **vault** — optional HashiCorp Vault integration for secrets.
- **notifications** — SMTP for the daily digest.

---

## Security posture

The code is built with the assumption that job postings are untrusted external input.

- API keys come from env vars or Vault — never stored in config files
- URL validation with SSRF protection (no private IPs, no `file://`)
- Parameterized SQL queries throughout
- AI responses defensively parsed and validated before display
- All four AI system prompts include anti-injection directives
- No user secrets sent in AI prompts
- No autonomous browser automation (and never will be — see [ROADMAP.md §2](ROADMAP.md))

See [RESPONSIBLE_USE.md](RESPONSIBLE_USE.md) for usage guidelines.

---

## What's next

v2 is in planning. The thesis: stop being a per-URL tool, become a funnel. Bulk discovery (`gather`) → enrichment (`enrich`) → batch judgement (`judge`) → tailored materials (`forge` + `petition`) → manual submit via local dashboard (`manifest`). All AI leverage on the writing, none on the submitting.

Full plan in [ROADMAP.md](ROADMAP.md). Shipped history in [CHANGELOG.md](CHANGELOG.md).

---

*The ferryman remembers all. Every crossing, every judgment, every ghost exposed.*
