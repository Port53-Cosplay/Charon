# Charon

> *Getting you to the other side.*

A CLI tool for job seekers who are tired of ghost jobs, toxic workplaces, and corporate doublespeak.

Named after the ferryman of the underworld. Because job hunting is already hell.

## Install

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows
# source .venv/bin/activate     # Linux/Mac
pip install -e ".[dev]"
```

## Configuration

Set your API key:
```bash
export ANTHROPIC_API_KEY=your-key-here
```

Set up your profile (values, dealbreakers, green flags):
```bash
charon profile --edit
charon profile --show
```

## Commands

### ghostbust - Detect ghost jobs
Analyzes a job posting for signs it's not a real hiring effort.

```bash
charon ghostbust --url https://example.com/jobs/123
charon ghostbust --paste          # paste text from stdin
```

Scores 0-100% ghost likelihood based on vagueness, missing salary, boilerplate language, and other indicators.

### redflags - Toxic workplace scanner
Scans a posting for red flags using AI judgment -- not keyword matching. Detects obfuscated language like "follow-the-sun model" (shift work) and "collaborative in-person culture" (RTO).

```bash
charon redflags --url https://example.com/jobs/123
charon redflags --paste
```

Three-tier output:
- **Dealbreakers** -- instant disqualifiers from your profile
- **Yellow flags** -- concerns worth investigating
- **Green flags** -- positive signals

### dossier - Company research (coming soon)
### hunt - Full pipeline (coming soon)
### watch - Company watchlist (coming soon)
### digest - Daily email digest (coming soon)

### Utility commands
```bash
charon profile --show             # view your values profile
charon profile --edit             # open profile in $EDITOR
charon profile --reset            # reset to defaults
charon history                    # view past analyses
charon history --clear            # clear history
```

## Profile

Your profile lives at `~/.charon/profile.yaml` and controls:
- **Values weights** -- what dimensions matter most (security culture, people treatment, etc.)
- **Dealbreakers** -- instant disqualifiers (RTO, no salary, shift work, etc.)
- **Yellow/green flags** -- signals to watch for
- **Target roles** -- what you're looking for
- **Notifications** -- email digest settings

## Security

- API key from environment variable only (never stored in config)
- SMTP password via `CHARON_MAIL_PASS` env var
- URL validation with SSRF protection (no private IPs, no file:// scheme)
- Parameterized SQL queries throughout
- AI responses defensively validated before display
- No user secrets sent in AI prompts

See [RESPONSIBLE_USE.md](RESPONSIBLE_USE.md) for usage guidelines.
