# Changelog

All notable changes to Charon are tracked here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning follows [Semantic Versioning](https://semver.org/) (pre-1.0 conventions — see ROADMAP.md §5).

## [Unreleased]

Phase 10 is mid-build. The dashboard ships in its first usable form
alongside the supporting deterministic-render layer and a small
LinkedIn-contacts surfacing helper.

### Added

- **`charon manifest`** — local HTTP dashboard. Default port 7777,
  auto-opens browser, binds to loopback only. Single "Ready" tab in
  this cut: score-sorted cards with score badges, sub-score pips,
  ATS/tier/materials badges, and per-card actions:
  - **Mark applied** — bridge that writes the application row AND flips
    the discovery's `screened_status` to `applied` atomically. Applied
    jobs drop off the ready list immediately.
  - **Not for me** — soft rejection with an optional "why?" textarea.
    Reason persists to `judgement_reason` for future filtering.
  - **Prep materials** (on cards without offerings) — runs forge +
    petition + render server-side, ~30s, card refreshes when done.
  - **Open folder** (on cards with offerings) — opens the offering's
    folder via `click.launch`.
  - **Find contacts** (on cards with offerings) — runs the LinkedIn
    contact search, saves to `linkedin_contacts.md`, adds a "contacts"
    badge to the card.
- **`charon render`** — deterministic markdown → styled HTML for an
  offering's `resume.md` and `cover_letter.md`. Pure Python via
  `markdown-it-py` token walk + section dispatch — no AI calls. CSS is
  inlined so each `.html` is a self-contained file ready for browser
  print-to-PDF. The shared stylesheet lives at
  `charon/templates/charon-document-style.css` (deep-purple accent,
  IBM Plex Sans, US Letter @page rules). Cover letter falls back to
  sibling `resume.md` for identity (tagline + contact rows) when the
  petition output is identity-light. 31 new tests.
- **`charon contacts --id <N>`** — surfaces recruiters / hiring
  managers / team members at the company for a specific offering
  and saves a categorized markdown list to its folder. Wraps the
  existing `dossier.find_contacts` web-search helper; opt-in so the
  per-call web-search cost (~$0.10-$0.20) is only paid for roles
  you actually want to outreach for.

### Changed

- **`charon provision` auto-renders**. After forge + petition succeed,
  provision automatically calls `render_offering(id)` so `.html`
  files land alongside the `.md` files in one step. Render is
  best-effort: failures surface as warnings, they don't roll back
  forge or petition.
- **`charon judge --list ready/rejected`** now sorts by `combined_score
  DESC` (was `discovered_at DESC`) and prints the posting URL beneath
  each row. The ready list is now genuinely an "apply to these, in
  this order" view.

### Docs / planning

- **Sirens** specced into Phase 10 in ROADMAP §10 — voice-true
  LinkedIn post writer embedded as a 5th tab in `manifest`, with
  voice prompt migrating to `profile.yaml` (canonical source for both
  Sirens and petition).
- **ROADMAP §11.5 (Known Workflow Gaps)** picked up two entries:
  - No `--tier` filter on `judge` (can't say "judge tier_1 first").
  - No discovery <-> application bridge in the CLI: `apply --add` still
    requires manual `--company`/`--role`/`--url` (the dashboard's
    Mark Applied button is the only place this is closed today).
- `charon funnel` cheat sheet grew steps 6 (render) and 7 (manifest).
- HOWTO.md adds sections for render, contacts, and the manifest
  dashboard.

### Dependencies

- Added `markdown-it-py >= 3.0` (used by `charon render`). Already a
  common transitive dep; small, pure-Python, no native build.

Next: more tabs on the dashboard (Gathered / Judged / Provisioned /
Crossed) and the Sirens tab.

## [0.9.6] — 2026-05-05

Phase 9.3 closes Phase 9. Two convenience commands ride on top of the
existing forge + petition plumbing.

### Added

- **`charon provision`** — runs forge then petition for a discovery (or
  for the whole ready pile via `--ready`). Petition runs even if forge
  errors — the failures are independent. Same flag surface as forge:
  `--id N | --ready | --ats | --force | --model | --limit | --yes`.
  Bulk-warn at >20 with cost estimate (forge + petition = 2 calls per
  discovery, so the warning threshold and estimate reflect that).
- **`charon offerings`** — shows or opens the materials folder.
  - `charon offerings` (default) lists every discovery with an
    offerings folder, sorted by combined score, with F/P markers
    showing forged + petitioned status.
  - `charon offerings --id N` shows the folder path and lists the
    files inside (with sizes).
  - `charon offerings --id N --open` launches your file manager to
    that folder via `click.launch`.

### Tests

- 11 new tests (426 → 438 total) covering provision orchestration
  (single, batch, skip-when-complete, --force) and offerings
  (--list default, --list after provision, --id detail, missing
  offerings, unknown id). AI calls mocked at the `tailor._generate`
  seam — no live network in suite.

### Phase 9 complete

The funnel now ends at clickable materials. Each ready discovery can
become a folder with `resume.md`, `cover_letter.md`, and the audit
files for both. Phase 10 (`manifest` dashboard) is next; that's the
one where everything renders in a browser instead of a CLI.

## [0.9.5] — 2026-05-05

Phase 9.2 ships. The funnel produces both materials per ready discovery:
the tailored resume from forge plus a voice-tuned cover letter from
petition. Materials live side-by-side in the same offerings folder.

### Added

- **`charon petition` command.** `--id N` for one, `--ready` for all
  unpetitioned ready discoveries, `--ats <name>` to slice, `--force` to
  overwrite, `--model` to override the configured model, `--limit` to cap,
  `--yes` to skip the >20-discovery confirmation prompt. Same surface as
  `forge`.
- **`charon/letter.py`** with `petition_discovery`. Reuses `tailor.py`'s
  offerings folder convention, model routing (`openrouter:` prefix), audit
  trail format, and verifier. Cover letter saves to `cover_letter.md`
  alongside the existing `resume.md`. Audit lands at `petition_audit.md`.
- **Voice-tuned system prompt.** Bakes in CLAUDE.md's DeAnna's Voice
  traits: conversational over corporate, specific over abstract, varied
  sentence length, contractions where natural, one associative aside is
  fine but two is too many, light mythology only if it lands. Explicitly
  bans corporate filler ("I am writing to express my interest,"
  "passionate about," "team player," "Looking forward to hearing from
  you," "leverage" as a verb, "spearheaded," "proven track record" etc.).
  Structure is loose: opening with a real reason, middle with concrete
  overlap and honest gap acknowledgment, close with a specific element to
  discuss instead of generic gratitude.
- **`petition_at` column** with `update_discovery_petitioned` helper.
  `get_ready_discoveries` gains `unpetitioned_only` flag for batch
  processing.
- **Judgement-aware prompting.** The petition prompt receives the
  resume_match analyzer's `overlap` (strengths to lead with), `gaps`
  (to address honestly), role_alignment overlap, and any green flags
  found by redflags — so the letter has concrete signal to lean on
  instead of re-deriving everything from the resume + posting.

### Fixed

- **Geographic fabrication closed.** First live petition run fabricated
  "I'm in the UK" when the Coalfire posting required UK residency. The
  numerical verifier doesn't catch geographic claims, so the rule lives
  in the prompt directly: do NOT claim the candidate is located in,
  moving to, or based in any city/state/country not on the resume.
  Regression test in `test_letter.py` pins the prompt rule. Re-running
  the petition produced an honest letter that opened with the geographic
  mismatch and offered a constructive alternative (US-based / remote).

### Changed (small breaking)

- **Audit filename standardized.** Forge's `prompt_used.md` renamed to
  `forge_audit.md` for symmetry with petition's `petition_audit.md`.
  Existing `prompt_used.md` files in offerings folders need a manual
  rename (one-line `mv` per folder); only one folder existed at the time
  of this release and it was renamed in place.

### Verified live (2026-05-05)

- Petitioned Coalfire "Associate, SOC Assessment" #2607. 4,010 input /
  497 output tokens (~$0.005 on Haiku). First run flagged the geographic
  fabrication; prompt was hardened mid-session; re-run produced an
  honest letter that surfaced the UK requirement directly. Letter
  voice landed: specific Citi metrics, real verbs, no corporate filler.

### Tests

- 9 new petition tests + the geographic-fabrication regression test
  (417 → 426 total). Mocked AI, prompt construction (voice traits and
  bans present in prompt, judgement hints flow through), file output
  (cover_letter.md, petition_audit.md), force overwrite (touches
  letter, leaves resume.md alone), non-ready rejection, missing
  judgement_detail, verifier integration.

## [0.9.0] — 2026-05-05

Phase 9.1 ships. The funnel finally has a content-generation stage:
`charon forge` produces a tailored resume per ready discovery, with a
post-generation verifier that flags numerical claims not present in the
source resume.

### Added

- **`charon forge` command.** `--id N` for one, `--ready` for all unforged
  ready discoveries, `--ats <name>` to slice, `--force` to overwrite,
  `--model` to override the configured model for a run, `--limit` to cap
  batch size, `--yes` to skip the >20-discovery confirmation prompt.
- **`charon/tailor.py`** with `forge_discovery`, `offerings_folder`,
  `slugify`, `verify_against_source`. Reuses `load_resume_text` from
  resume_match (md/txt/pdf/docx). Model routing mirrors enrich: bare
  names use the native Anthropic SDK, `openrouter:vendor/model` prefix
  routes through OpenRouter.
- **Per-discovery offerings folder** at
  `<offerings_dir>/<company-slug>-<role-slug>-<id>/` containing
  `resume.md` (the tailored output) and `prompt_used.md` (full audit
  trail: model, token usage, system prompt, user prompt, raw output,
  verifier results).
- **Forge prompt** explicitly forbids fabrication: every concrete fact
  in the output (companies, dates, role titles, metrics, certifications,
  technologies) must trace back to the source resume. The AI may reorder,
  reframe, and emphasize, but not invent. Style guidance also bans
  AI-slop ("leveraged," "spearheaded," uniform bullet length, etc.).
- **Post-generation verifier.** Extracts every numerical claim from the
  generated resume (counts, percentages, years, thousands-separator
  numbers) and confirms each appears in the source under multiple
  normalizations (with/without commas, with/without %, "30 percent"
  variant). Unverified claims surface in the CLI as warnings and in
  prompt_used.md as a marked section. Output is still written — the
  user reviews before submitting.
- **`forge` profile section** (`model`, `max_tokens`, `offerings_dir`)
  with validation. Default model is `claude-haiku-4-5` per ADR-003.
- **Judgement hints** flow into the forge prompt: the resume_match
  analyzer's `overlap` list and role_alignment's `overlap` are surfaced
  as "experience to emphasize," giving the AI explicit guidance about
  which existing achievements to lead with.
- **DB columns** `forged_at`, `offerings_path` and helper
  `update_discovery_forged`. New helper `get_ready_discoveries` with
  `unforged_only` flag for batch processing.
- **HOWTO.md** gains a forge workflow section.

### Verified live (2026-05-05)

- Forged Coalfire "Associate, SOC Assessment" (#2607). 3,433 input /
  1,325 output tokens (~$0.005 on Haiku). Verifier clean. Output
  correctly framed Citi fraud-detection work as audit/assessment
  experience, surfaced relevant certs in priority order (CISA
  highlighted for SOC assessment), and avoided AI-slop language.

### Tests

- 25 new tests (392 → 417 total). Slugification edge cases, offerings
  folder layout, verifier across normalization variants (commas,
  percent, "30 percent" wording, year detection), forge_discovery
  behavior (writes files, surfaces unverified claims, skips when
  folder exists, `--force` overwrites, rejects non-ready discoveries,
  rejects discoveries without descriptions, judgement hints in
  prompt), and model routing (`openrouter:` vs bare).

### Deferred to later phase 9 sub-releases

- `charon petition` (cover letter) — Phase 9.2, ships as v0.9.5.
  Will reuse the offerings folder convention and model routing
  built here. DeAnna's voice traits from CLAUDE.md will inform the
  cover-letter prompt specifically.
- `charon provision` (forge + petition wrapper) and `charon offerings`
  (show / open the materials folder) — Phase 9.3.

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

[Unreleased]: https://github.com/Pickle-Pixel/Charon/compare/v0.9.6...HEAD
[0.9.6]: https://github.com/Pickle-Pixel/Charon/compare/v0.9.5...v0.9.6
[0.9.5]: https://github.com/Pickle-Pixel/Charon/compare/v0.9.0...v0.9.5
[0.9.0]: https://github.com/Pickle-Pixel/Charon/compare/v0.8.5...v0.9.0
[0.8.5]: https://github.com/Pickle-Pixel/Charon/compare/v0.8.0...v0.8.5
[0.8.0]: https://github.com/Pickle-Pixel/Charon/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/Pickle-Pixel/Charon/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/Pickle-Pixel/Charon/compare/v0.5.3...v0.6.0
[0.5.3]: https://github.com/Pickle-Pixel/Charon/compare/v0.5.2...v0.5.3
[0.5.2]: https://github.com/Pickle-Pixel/Charon/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/Pickle-Pixel/Charon/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/Pickle-Pixel/Charon/releases/tag/v0.5.0
