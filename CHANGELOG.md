# Changelog

All notable changes to Charon are tracked here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning follows [Semantic Versioning](https://semver.org/) (pre-1.0 conventions — see ROADMAP.md §5).

## [Unreleased]

Active work toward v2 Phase 6 (`gather`). See `ROADMAP.md` for phase plan.

## [0.5.1] — 2026-04-30

Pre-v2 cleanup (Phase 5.5). No code changes; doc and metadata only.

### Added
- `ROADMAP.md` — master v2 project plan with phases, acceptance criteria, ADRs, and risk register.
- `CHANGELOG.md` (this file).
- `LICENSE` (MIT) at repo root.
- `docs/archive/` for historical planning artifacts.

### Changed
- `README.md` rewritten to reflect actual shipped functionality (was stuck at Phase 3.5 with "coming soon" labels on shipped features).
- `CLAUDE.md` now points new sessions at `ROADMAP.md` for active plan; v1 phases marked historical.
- Version bumped from `0.1.0` (stale) to `0.5.1` in `pyproject.toml` and `charon/__init__.py`.
- `charon/hunt.py` role-alignment prompt updated to distinguish security disciplines (DFIR vs cloud sec vs DevSecOps) and cap mismatched scores at 50.

### Moved
- `REQUIREMENTS.md` → `docs/archive/REQUIREMENTS_v1.md`.

### Removed
- `manualList.txt` — stray scratch file (paste of `apply --list` output).

## [0.5.0] — 2026-04-30

Pre-v2 baseline. Tagged retroactively to mark the end of v1 development before the v2 funnel architecture begins.

### Shipped (cumulative through v1)

- **Phase 0 — Scaffolding:** Click CLI, Rich output, SQLite at `~/.charon/charon.db`, YAML profile at `~/.charon/profile.yaml`, profile validation, Vault integration via `hvac`.
- **Phase 1 — `ghostbust`:** Ghost job detection via Claude with structured JSON scoring. URL fetching with SSRF protection. Paste mode.
- **Phase 2 — `redflags`:** Toxic workplace scanner using AI judgment, not keyword matching. Three-tier output (dealbreakers / yellow / green) driven by profile.
- **Phase 3 — `dossier`:** Company research with weighted values scoring. Markdown export with `--save`.
- **Phase 3.5 — `hunt`:** Two-phase pipeline (recon: ghostbust + redflags + role alignment; dossier: deep company research). Discipline-aware role alignment that distinguishes DFIR / DevSecOps / cloud security as separate career tracks.
- **Phase 4 — `watch` and `digest`:** Company watchlist. Daily email digest via SMTP with Brevo relay through Empire12 mail flow.
- **Phase 5 — `apply` and `inbox`:** Application tracking with status lifecycle. IMAP scanning of Gmail for replies. AI-classified email responses (interview / rejection / acknowledgment / response). Auto-ghost detection after 21 days. Daily ops-server scanner.
- **Post-deployment:** `toll` (hunt log), dossier tracking, closed-posting detection, contacts finder, interactive drill-down, paste fallback, JSON repair for AI responses, prompt-injection hardening across all four AI system prompts.

### Infrastructure

- Daily scanner deployed to `/opt/charon-daily/` on Empire12 ops server (192.168.13.55).
- DB sync via base64-over-SSH (Windows OpenSSH SCP corrupts binaries).
- Vault-backed secret management with env var fallback.
- 173 tests across all phases.

### Known limitations at this baseline

- `README.md` and `REQUIREMENTS.md` describe the v1 build phase, not the shipped state. Pre-v2 cleanup (Phase 5.5) addresses this.
- No prior tags. v0.5.0 is the first.
- Single contributor.

[Unreleased]: https://github.com/Pickle-Pixel/Charon/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/Pickle-Pixel/Charon/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/Pickle-Pixel/Charon/releases/tag/v0.5.0
