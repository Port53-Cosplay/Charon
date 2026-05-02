# Changelog

All notable changes to Charon are tracked here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning follows [Semantic Versioning](https://semver.org/) (pre-1.0 conventions — see ROADMAP.md §5).

## [Unreleased]

Next: Phase 7 (`enrich`). See `ROADMAP.md` for plan.

## [0.6.0] — 2026-05-02

Phase 6 ships. Charon now discovers jobs across the curated employer
registry without the user pasting URLs one at a time.

### Added
- `charon gather` command — polls public ATS APIs for the 47 verified
  employers in `config/companies.yaml` and writes new postings to a
  new `discoveries` table.
- Four ATS adapters in `charon/gather/`:
  - `greenhouse.py` — `boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=true`
  - `lever.py` — `api.lever.co/v0/postings/<slug>?mode=json`
  - `ashby.py` — `api.ashbyhq.com/posting-api/job-board/<slug>`
  - `workday.py` — POST to `<tenant>.<wd>.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs`,
    paginated 20/page with a 1s default page delay
- `charon gather --add <url>` one-shot mode that auto-detects the ATS and
  slug from any careers URL (Greenhouse, Lever, Ashby, Workday). Falls
  back to `--add <slug> --ats <name>` for non-URL inputs. Does NOT mutate
  `companies.yaml` — the curated list stays curated.
- `discoveries` SQLite table with dedupe by URL hash (scoped per ATS) and
  CRUD helpers in `db.py`.
- Applied-companies skip set: gather automatically excludes employers
  already in the user's active `applications` so the funnel doesn't
  re-discover jobs you've already applied to.
- HOWTO.md gains a `gather` workflow section.

### Changed
- 86 new tests (273 → 293 total). All four adapters tested against
  captured fixtures via `httpx.MockTransport` — no live network in
  the suite.

### Verified live (dry-run)
- Datadog (Greenhouse): 426 jobs
- Sysdig (Lever): 23 jobs
- Vanta (Ashby): 147 jobs
- Schellman (Workday): 12 jobs
- Airbnb via `--add` URL detection (Greenhouse, not in registry): 235 jobs

### Deferred to later phases
- Rippling adapter (BARR Advisory + Black Kite kept commented out in
  companies.yaml). Will land as a v0.6.x patch when activated.
- iCIMS adapter — skipped per ROADMAP (federal/cleared roles, out of scope).
- Six employers in the TODO block of companies.yaml (Snyk, Anchore, Pangea,
  AuditBoard, Prescient Assurance, Palisade Research) — need manual ATS
  investigation before they can be added.

## [0.5.3] — 2026-04-30

Phase 6 design iteration. No runtime code changes — config and planning only. Sets up the foundation for Phase 6 implementation in the next session.

### Added
- `config/companies.yaml` — curated employer registry for Phase 6 (`gather`). 47 active entries: Greenhouse (29), Lever (6), Ashby (8), Workday (4). Every slug verified against the public ATS API. Each entry has `tier` (priority_tier metadata) and `category` (role-type) fields for downstream scoring/tailoring. Includes a Rippling section commented out (BARR Advisory + Black Kite, awaiting adapter) and a TODO block of 6 employers requiring manual ATS investigation (Snyk, Anchore, Pangea, AuditBoard, Prescient Assurance, Palisade Research).
- ROADMAP.md ADR-006 documents the architectural pivot to ATS-first discovery, replacing the originally planned JobSpy-based design.

### Changed
- ROADMAP.md Phase 6 rewritten around per-ATS adapters (Greenhouse, Lever, Ashby, Workday). New `charon/gather/` package layout with one module per ATS. Single config file replaces the previously planned `workday.yaml` + `sites.yaml` split.
- ROADMAP.md Status Tracker now reflects shipped 0.5.1 / 0.5.2 / 0.5.3 milestones.

### Investigated and rejected
- `python-jobspy` for aggregator-board scraping. Smoke test: ZipRecruiter 403 (Cloudflare), Glassdoor API error, Google Jobs returns 0; only Indeed worked, with poor relevance for niche security queries. Removed from Phase 6 scope.
- RSS feeds for Dice, BuiltIn, isecjobs.com, NinjaJobs. URLs that look like RSS endpoints (`/rss`, `/feed`) actually serve HTML, not feeds. Deferred indefinitely.
- First2Apply-style headless-browser scraping. Architecture is technically sound but reintroduces the autonomous-browser concerns rejected in ADR-001. Out of scope.

## [0.5.2] — 2026-04-30

Patch release. Three pre-existing test failures cleaned up before v2 work begins. Full suite now green: 187/187 passing.

### Fixed
- `_build_imap_search` now early-returns `[]` when no useful search criteria can be extracted from tracked applications (no domains, no companies, no roles). Previously it appended 8 generic confirmation-pattern queries regardless, which would match unrelated mail when there were no actual applications to attribute matches to.
- `test_acknowledgment_maps_to_responded` was asserting against pre-distinction behavior. Renamed to `test_acknowledgment_maps_to_acknowledged` and updated assertion to match the documented (and correct) mapping. HOWTO.md treats `acknowledged` (machine auto-receipt) and `responded` (human reply) as distinct statuses.

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

[Unreleased]: https://github.com/Pickle-Pixel/Charon/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/Pickle-Pixel/Charon/compare/v0.5.3...v0.6.0
[0.5.3]: https://github.com/Pickle-Pixel/Charon/compare/v0.5.2...v0.5.3
[0.5.2]: https://github.com/Pickle-Pixel/Charon/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/Pickle-Pixel/Charon/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/Pickle-Pixel/Charon/releases/tag/v0.5.0
