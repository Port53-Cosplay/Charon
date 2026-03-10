# Charon How-To Guide

> "Getting you to the other side."

Quick reference for using Charon day-to-day. Run all commands from any terminal.

---

## Quick Start

```bash
# Make sure you're in the project directory (or charon is installed)
cd C:\Users\lurka\Projects\Charon

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
charon apply --add --company "Rapid7" --role "AI Red Team" --url https://rapid7.com/careers/456 --notes "Applied via dshanks@duck.com"
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
charon hunt --paste < posting.txt
charon ghostbust --paste < posting.txt
charon redflags --paste < posting.txt
```

This avoids shell interpretation issues and works reliably every time.

### Update an Application Manually

```bash
# Update status (if you hear back before the scanner catches it)
charon apply --id 3 --status interviewing

# Valid statuses: applied, responded, interviewing, offered, rejected, ghosted
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
| `responded` | Company acknowledged receipt | Auto: inbox scanner detects acknowledgment email |
| `interviewing` | Interview scheduled/in progress | Auto: inbox scanner detects interview invite |
| `offered` | You received an offer | Auto: inbox scanner detects offer email |
| `rejected` | Application was declined | Auto: inbox scanner detects rejection email |
| `ghosted` | No response after 21 days | Auto: daily ghost check |

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

Your profile lives at `C:\Users\lurka\.charon\profile.yaml`. Key sections:

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
- **Use dshanks@duck.com when applying.** Replies forward to your Gmail, where the scanner picks them up.
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
