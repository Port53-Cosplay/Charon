# Changelog

All notable changes to Charon are tracked here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning follows [Semantic Versioning](https://semver.org/) (pre-1.0 conventions — see ROADMAP.md §5).

## [Unreleased]

Next: Phase 9 (`forge` + `petition`). See `ROADMAP.md` for plan.

## [0.8.5] — 2026-05-05

Phase 8.5 ships. Adds a fourth analyzer (resume match), tunable weights, the
alignment floor, the by-company aggregation view, the no-AI reclassify path,
and a Ctrl+C bug fix. Together these turn the funnel from "things that look
plausible" into "things you could actually credibly apply for."

### Added

- **Resume match analyzer.** New module `charon/resume_match.py`. Scores how
  closely a posting matches the candidate's *actual* resume (what they've
  done) rather than aspirational `target_roles` (what they want to do).
  Returns score 0-100, match type (direct/adjacent/stretch/mismatch),
  cited overlap and gaps. Prompt is hardened against injection in both the
  resume and the posting.
- **Resume format support.** `.md` / `.txt` read directly; `.pdf` via
  `pypdf>=4.0`; `.docx` via `python-docx>=1.0`. Both new deps. Configured
  via `profile.resume_path` (file or directory; if directory, picks newest
  by extension preference: md > txt > docx > pdf). Empty path disables the
  analyzer cleanly.
- **Weighted combined score.** `profile.judge.weights` controls how the four
  components blend. Default skews toward resume_match (0.40) so evidence-
  based fit dominates aspirational alignment. Falls back to equal averaging
  if weights unset, and to 3-component formula for rows judged before
  resume_match existed.
- **`charon judge --by-company`** aggregation view. Shows per-company:
  total / ready / rejected counts plus avg combined / ghost / redflag /
  alignment / resume scores. Surfaces patterns like "every Apollo
  posting flagged" vs "one bad Coalfire listing" at a glance. Pure SQL,
  no AI.
- **`--status ready/rejected` filter** on judge batches. Combine with
  `--rejudge` to re-score only the survivors after tuning prompts /
  thresholds / adding the resume analyzer. Cheaper than re-judging
  everything.
- **`charon judge --reclassify`.** Re-applies the gating logic
  (alignment_floor, ready_threshold, weights) to stored scores. **No AI
  calls.** Free, instant. Use after tuning thresholds without paying to
  re-run analyzers.
- **`judge.alignment_floor`** (default 50). Hard reject when
  `alignment_score < floor` regardless of combined score. Prevents the
  "sales role greenlit because ghost+redflag are clean" failure mode.
- **`update_discovery_classification`** DB helper that updates only the
  gating outcome (status / combined / reason) without touching the full
  analyzer detail JSON. Used by reclassify.
- **`get_company_judgement_summary`** SQL aggregator backing `--by-company`.

### Fixed

- **Ctrl+C now actually cancels batch loops.** `ai.py` was catching
  `KeyboardInterrupt` and converting it into an `AIError`, which the batch
  loops were treating as a per-row failure and continuing. Removed the
  conversion in both `query_claude` and `query_claude_web_search` so the
  signal propagates to the CLI's interrupt handler. Two regression tests
  pin the behavior.
- **Lakera Ashby slug returns 404.** Commented out in `companies.yaml` and
  added to the manual-investigation TODO. The slug appears to have changed
  or moved off Ashby; the public careers page hides the new ATS endpoint
  behind JS rendering.

### Verified live (2026-05-05)

- 92 Lever discoveries gathered, 92 enriched (all `skipped` — Lever
  populates descriptions at gather time), 92 judged at 3 components ($3-5).
- 21 ready under old 3-component formula → 14 ready after applying
  alignment_floor=50 via `--reclassify` (free) → **6 ready** after
  `--rejudge --status ready` ran resume_match across the 14 survivors
  (~$1.50). Resume analyzer specifically caught the "Sales Solutions
  Engineer at a security company" case as a clear mismatch (cited
  missing GRC framework experience, missing cloud infrastructure
  expertise, no customer-facing technical sales background).
- 33 new tests (359 → 392 total). All four analyzers' integration paths
  covered, plus the formula, floor, reclassify, status filter, by-company
  aggregation, and the Ctrl+C regression.

### Documentation

- HOWTO.md gains sections for the resume analyzer, weights, by-company,
  the alignment floor, and reclassify.
- ROADMAP.md gets a Phase 8.5 entry and Status Tracker update.

## [0.8.0] — 2026-05-04

Phase 8 ships. Discoveries can now be auto-scored by the existing v1
analyzers in batch mode. The Three Judges of the Underworld decide who crosses.

### Added
- `charon judge` command. `--id N` for one, `--all` for unjudged batch,
  `--ats <name>` slice, `--rejudge` to re-run, `--limit`, `--threshold`,
  `--list ready/rejected`, `--stats` for status counts. Bulk-run guardrail
  prompts before judging more than `judge.bulk_warn_at` discoveries (default
  50) with a cost estimate.
- New module `charon/screen.py` with `judge_discovery`, `judge_one_id`,
  `judge_batch`, `compute_combined`, `list_by_status`. Reuses the existing
  `analyze_ghostbust`, `analyze_redflags`, and `analyze_role_alignment`
  functions — no new prompts.
- `discoveries` table gains `ghost_score`, `redflag_score`, `alignment_score`,
  `combined_score`, `judgement_reason`, `judgement_detail` (full analyzer
  JSON), `judged_at`. Migrations are additive; existing rows simply have
  `judged_at IS NULL` until judge runs.
- Combined score formula: `((100-ghost) + (100-redflag) + alignment) / 3`.
  Mirrors v1 hunt's averaging minus the dossier dimension (dossier is
  expensive and runs per-job in Phase 9).
- `judge` profile section with `ready_threshold` (default 60) and
  `bulk_warn_at` (default 50). Validated.
- HOWTO.md gains a `judge` workflow section.

### Verified live
- Schellman #1 ("Senior Associate, ISO"): ghost 15, redflag 45,
  alignment 85, combined 75.0 → ready. Single judge call, ~$0.05 spent.
  Full analyzer detail (signals, dealbreakers, yellow/green flags,
  role-alignment overlap) preserved in `judgement_detail` JSON.

### Tests
- 25 new tests (334 → 359 total) covering combined-score formula,
  threshold gating, full_description preference over description,
  no-target-roles fallback, AI-error handling, DB writes, force flag,
  ATS filtering, list_by_status filters, stats counts.

## [0.7.0] — 2026-05-03

Phase 7 ships. Discoveries can now be cheaply enriched with full descriptions
via a three-tier cascade — most jobs cost $0 because tier 1 catches them.

### Added
- `charon enrich` command. `--id N` for one, `--all` for unenriched batch,
  `--ats <name>` slice, `--force` re-enrich, `--limit`, `--rate-limit`,
  `--stats` for tier-hit-rate dashboard.
- Three-tier extraction in `charon/enrich/`:
  - `jsonld.py` — schema.org JobPosting from `<script type="application/ld+json">`.
    Generic, free, catches Workday and most SEO-conscious careers pages.
  - `ats_css.py` — per-ATS selector library (Greenhouse, Lever, Ashby, Workday).
  - `llm.py` — pluggable model routing. Bare names use the native Anthropic SDK;
    the `openrouter:vendor/model` prefix routes through OpenRouter's
    OpenAI-compatible API via httpx. No new SDK dependency. Default model is
    `claude-haiku-4-5` per ADR-003 (mechanical stages route to cheaper models).
- `discoveries.full_description`, `enrichment_tier`, `enriched_at` columns
  via migrations. Tiers: `skipped | jsonld | ats_css | ai_fallback | failed`.
  `skipped` means the gather adapter already populated `description` with
  >= 500 chars (Greenhouse / Lever / Ashby), so no fetch is needed.
- `enrich` profile section with `model`, `skip_threshold`,
  `rate_limit_seconds`. Validated.
- HOWTO.md gains an `enrich` workflow section.

### Changed
- `charon/fetcher.py` refactored: `fetch_html(url)` returns raw HTML;
  `fetch_url(url)` is now `extract_text(fetch_html(url))`. All existing
  callers behave identically.
- 41 new tests (293 → 334 total) covering each tier with captured fixtures
  and the cascade orchestrator end-to-end with mocked `fetch_html`.
  OpenRouter HTTP path tested via `httpx.MockTransport`.

### Verified live
- Schellman (Workday): all 12 jobs enriched via tier 1 (JSON-LD).
  Zero LLM calls, zero failures, zero token cost. Average extracted
  description: ~8000 chars.

### Deferred to later phases
- iCIMS CSS selectors — skipped per ROADMAP "no federal" preference.
- Tier-hit-rate metrics emitted to digest — could land in the daily
  scanner work in Phase 11.

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

[Unreleased]: https://github.com/Pickle-Pixel/Charon/compare/v0.8.5...HEAD
[0.8.5]: https://github.com/Pickle-Pixel/Charon/compare/v0.8.0...v0.8.5
[0.8.0]: https://github.com/Pickle-Pixel/Charon/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/Pickle-Pixel/Charon/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/Pickle-Pixel/Charon/compare/v0.5.3...v0.6.0
[0.5.3]: https://github.com/Pickle-Pixel/Charon/compare/v0.5.2...v0.5.3
[0.5.2]: https://github.com/Pickle-Pixel/Charon/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/Pickle-Pixel/Charon/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/Pickle-Pixel/Charon/releases/tag/v0.5.0
