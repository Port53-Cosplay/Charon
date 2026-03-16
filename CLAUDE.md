# Charon — Project Instructions for Claude Code

## Working Style — MANDATORY

- **Before implementing anything non-trivial:** Assess the situation, offer 2+ solutions, present a plan, and ASK the user before executing. Do not just go do it.
- **Data operations are sacred.** Never overwrite, sync, push, or delete user data without explicit confirmation. Show what will change first.
- **When unsure, ask.** A question costs nothing. A wrong action costs trust.

## Project Overview

Charon is a security-forward CLI tool for job seekers. Metasploit-style aesthetic, dark ferryman theme. Python 3.11+, Click/Typer, Rich, Claude API.

## Build Phases

Build sequentially. Each phase must be functional and testable before proceeding.

- **Phase 0**: Scaffolding (repo structure, profile, DB, output helpers)
- **Phase 1**: `ghostbust` (ghost job detection)
- **Phase 2**: `redflags` (toxic workplace signals)
- **Phase 3**: `dossier` (company research + scoring)
- **Phase 3.5**: `hunt` (pipeline orchestration)
- **Phase 4**: `watch` + `digest` (watchlist, crawler, email)

## Security Requirements

### Code Security (Non-Negotiable)

- **No secrets in code.** API keys, SMTP credentials, and all sensitive values come from environment variables or `~/.charon/profile.yaml` (which is gitignored). Never hardcode, log, or echo secrets.
- **Input validation on all user-supplied data.** URLs, company names, paste input — validate and sanitize before use. Reject obviously malicious input (path traversal, shell injection payloads).
- **URL validation.** Only fetch HTTP/HTTPS URLs. No `file://`, `ftp://`, or other schemes. Validate domain resolution before fetching. Set timeouts and max response sizes on all HTTP requests.
- **SQL injection prevention.** Use parameterized queries exclusively for all SQLite operations. Never interpolate user input into SQL strings.
- **No arbitrary code execution.** Never pass user input to `eval()`, `exec()`, `subprocess` with `shell=True`, or `os.system()`.
- **Dependency pinning.** Pin all dependencies in `pyproject.toml` with minimum versions. Prefer well-maintained packages with security track records.
- **File path safety.** When writing dossiers or any output files, validate paths and prevent directory traversal. Use `pathlib.Path.resolve()` and confirm paths stay within expected directories.
- **Rate limiting awareness.** Respect API rate limits for Claude and any scraped sources. Implement backoff, not retry spam.
- **Error messages.** Never leak stack traces, file paths, API keys, or internal state to the user in production output. Log verbosely to debug log; show clean messages to user.

### Claude API Security

- All AI calls use `claude-sonnet-4-20250514` model
- Low temperature (0.2-0.3) for scoring consistency
- Request structured JSON output — parse and validate before display
- Never send user credentials or secrets as part of AI prompts
- Validate AI response structure before trusting it (defensive parsing)

### Profile Security

- `~/.charon/profile.yaml` may contain SMTP credentials — never log or display mail_pass
- Profile validation should reject unexpected keys/types (defense against YAML injection if profile is ever shared)
- Default profile template should have empty credential fields with clear comments

## Coding Conventions

- **Style:** Follow PEP 8. Use type hints on all function signatures.
- **Imports:** stdlib first, third-party second, local third. One import per line for local modules.
- **Error handling:** Catch specific exceptions. Use `click.echo` or Rich console for user-facing errors. Never bare `except:`.
- **CLI output:** All user-facing output goes through Rich. Use the output helpers in `output.py`. Red for bad, yellow for warnings, green for good.
- **Naming:** snake_case for functions/variables, PascalCase for classes, UPPER_SNAKE for constants.
- **Tests:** pytest. Each module gets a corresponding test file. Test the security boundaries (malicious URLs, SQL injection attempts, path traversal).
- **Docstrings:** Only on public functions and classes. Keep them brief — one line if possible.

## Aesthetic Guidelines

- CLI output should feel like a security toolkit (nmap, metasploit style)
- ASCII art banner on startup (ferryman/underworld themed)
- Dark humor in help text and error messages — but the tool is serious and useful
- Score displays use Rich progress bars and color-coded tables
- Consistent formatting across all commands

## File Layout

```
charon/
├── charon/
│   ├── __init__.py
│   ├── cli.py          # Click entry point
│   ├── profile.py      # Profile loading/validation
│   ├── db.py           # SQLite (parameterized queries only)
│   ├── fetcher.py      # URL fetching (validated, sandboxed)
│   ├── ai.py           # Claude API calls
│   ├── ghostbust.py    # Ghost job analysis
│   ├── redflags.py     # Red flag analysis
│   ├── dossier.py      # Company dossier
│   ├── hunt.py         # Pipeline orchestration
│   ├── watch.py        # Watchlist/crawler (Phase 4)
│   ├── digest.py       # Email digest (Phase 4)
│   └── output.py       # Rich formatting helpers
├── tests/
├── pyproject.toml
├── REQUIREMENTS.md
├── RESPONSIBLE_USE.md
└── .gitignore
```

## Key Reminders

- AI judgment is intentional — never replace with keyword/regex matching
- Profile is the user's most important config — keep it intuitive
- Every command should feel like it belongs alongside nmap and metasploit
- Users are stressed job seekers — prioritize clarity in output
- Run `/security-review` after completing each phase

## Technical Notes

- **Stack:** Python 3.11+, Click, Rich, Claude API (claude-sonnet-4-20250514), httpx, BeautifulSoup, SQLite
- **Build backend:** Hatchling — requires `[tool.hatch.build.targets.wheel] packages = ["charon"]` since project name != package dir
- **Windows cp1252:** Do NOT use unicode symbols in Click help strings or Rich output. Use ASCII: `[X]` `[!]` `[+]` `[>]` `---`. The `output.py` module forces UTF-8 on Windows stdout/stderr.
- **pytest + output.py:** UTF-8 stdout wrapping breaks pytest capture. Gated with `sys.stdout.isatty()`.
- **Em-dash in tables:** Don't use `---` in Rich tables on Windows. Use `-`.
- **DB schema columns:** `applied_at`, `updated_at`, `ghosted_notified` (NOT applied_date/updated_date).
- **DB location:** `~/.charon/charon.db` — initializes on import of `charon.db`.
- **Profile path:** `~/.charon/profile.yaml` — SMTP password from `CHARON_MAIL_PASS` env var.
- **Test isolation:** `conftest.py` autouse fixture redirects DB to temp path.
- **JSON repair:** `_repair_json_strings()` in ai.py handles unescaped quotes, unclosed strings from AI responses.
- **Prompt injection hardening:** All four AI system prompts include anti-injection directives.
