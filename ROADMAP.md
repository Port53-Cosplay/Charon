# Charon v2 — Project Plan

> **Status:** Planning. Last updated 2026-04-30. Current shipped version: 0.5.0 (pre-v2 baseline).

This is the master plan for Charon v2. It is the single source of truth for scope, phases, decisions, and current status. Update it as work progresses.

---

## 0. How to Use This Document

**For DeAnna (the human):** This file is your reference. Update the **Status Tracker** section at the bottom each time a phase ships or scope changes. Don't let it go stale — a stale plan is worse than no plan.

**For Claude Code (any new session):** When you open this project:

1. Read `CLAUDE.md` (loads automatically — non-negotiable rules).
2. Read this file. Note the current phase, its status, and any open blockers.
3. Run `git log --oneline -10` to see what shipped recently.
4. **Confirm current phase with the user before starting work.** Plans drift. Verify before acting.
5. Never advance the phase tracker without the user's explicit confirmation that the previous phase is done.

**Status legend:**
- `[ ]` Not started
- `[~]` In progress
- `[X]` Shipped
- `[!]` Blocked — see notes
- `[-]` Deferred / cut from scope

---

## 1. Vision

v1 was *"don't waste time on bad jobs you found yourself."*
v2 is *"find the good jobs for me, and prep the materials so I'm one click from applying."*

Charon stops being a per-URL tool and becomes a **funnel**: bulk discovery → automatic filtering by existing values logic → per-job tailored materials → manual submit. The browser stays the user's. No autonomous form submission, ever.

---

## 2. Non-Goals (Explicit)

- **No autonomous form submission.** No Chrome profile cloning. No Playwright MCP. No `bypassPermissions`. Charon exists *because* those patterns are unsafe.
- **No LinkedIn integration.** User does not use LinkedIn. JobSpy makes it optional; leave it off.
- **No SaaS / hosted product.** Personal tool. Server is the user's. Data is the user's.
- **No multi-user / multi-tenant features.** Profile is a single user.
- **No CAPTCHA solving.** Out of scope. If a site requires CAPTCHA to view a posting, skip that posting.
- **No code copied from ApplyPilot.** AGPL-3.0 license incompatibility. See §6.

---

## 3. Current State (v1, as of 0.5.0)

### What ships today

| Module | Command(s) | Status |
|---|---|---|
| `ghostbust.py` | `charon ghostbust` | Working |
| `redflags.py` | `charon redflags` | Working |
| `dossier.py` | `charon dossier` | Working |
| `hunt.py` | `charon hunt` (two-phase: recon + dossier) | Working |
| `apply.py` | `charon apply` (add/list/update/stats) | Working |
| `inbox.py` | `charon inbox` (IMAP scanning) | Working |
| `digest.py` | `charon digest` (preview/send) | Working |
| `batch.py` | `charon toll` (hunt log) | Working |
| Watch | `charon watch` (add/list/remove) | Working |
| Profile | `charon profile` (show/edit/reset) | Working |
| Vault integration | `secrets.py` (hvac client) | Working |
| Daily ops scanner | `/opt/charon-daily/` on 192.168.13.55 | Deployed |
| DB sync (pull-only auto, push manual) | ssh+base64 transport | Working |

### Stats
- 173 tests across all phases
- Two git commits (initial squash + public release prep)
- Single contributor (DeAnna)
- License: MIT (declared in pyproject.toml; LICENSE file needs verification)

### Known v1 issues / debt
- `README.md` is severely out of date — stops at Phase 3.5, says "coming soon" for things that ship.
- `REQUIREMENTS.md` is the original phased build doc, now historical.
- No `CHANGELOG.md`.
- No git tags. Two commits cover all of v1.
- `__init__.py` and `pyproject.toml` both say `0.1.0` despite Phase 5 being complete.
- `manualList.txt` purpose unclear — needs review.

These get cleaned up as part of v2 Phase 5.5 (pre-flight).

---

## 4. v2 Goals

1. **Bulk discovery** — Charon finds jobs across boards + Workday + direct career sites without the user typing URLs.
2. **Discipline-aware filtering at scale** — existing role-alignment / ghostbust / redflags pipeline runs on every discovered job, so the funnel narrows automatically.
3. **AI-prepped materials per surviving job** — tailored resume + cover letter generated only for jobs that pass the filter. No tokens wasted on duds.
4. **Click-to-apply ready dashboard** — sortable list of survivors with materials attached. User picks what to submit.
5. **Honest token economics.** Discovery scales; tailoring is gated behind quality thresholds and routed to cheaper models where appropriate.

---

## 5. Versioning & Release Strategy

### Semver (pre-1.0)

- `0.x.y` — pre-stable, personal use only
- Bump **minor** (`0.5 → 0.6`) on phase completion or new command
- Bump **patch** (`0.5.0 → 0.5.1`) on bugfix
- `1.0.0` — only when willing to publish for strangers (not a current goal)

### Release process per phase

1. All acceptance criteria met for the phase
2. Tests pass: `pytest`
3. `CHANGELOG.md` updated under new version heading
4. Bump version in `pyproject.toml` and `charon/__init__.py` (must match)
5. Update Status Tracker in this file
6. Commit: `Release vX.Y.Z — <phase name>`
7. Tag: `git tag vX.Y.Z && git push origin vX.Y.Z`

### Pre-v2 baseline

- [ ] Tag current state as `v0.5.0` before any v2 work begins
- [ ] First v2 phase ships as `v0.6.0`

---

## 6. License & IP Boundaries

Charon is MIT. ApplyPilot (the inspiration for some v2 features) is AGPL-3.0. **These licenses are incompatible** if Charon copies AGPL code.

### Rules

- **Never copy code from ApplyPilot.** Read it for ideas only.
- **Reimplement using shared upstream libraries.** Both projects use `python-jobspy` (MIT) — fine.
- **Rebuild any "registry" data from scratch** (Workday tenants, direct career sites). Curated lists may have selection-arrangement protection. Building your own list is a few hours of work and removes any ambiguity.
- **Write all prompts originally.** Charon's prompt-injection hardening is already better than ApplyPilot's anyway.

If an upstream library is AGPL, do not add it as a dependency.

---

## 7. Architecture Decisions (ADRs)

Record decisions here as they're made. Format: short, dated, with rationale.

### ADR-001 — Funnel architecture, not browser automation
**Date:** 2026-04-30
**Decision:** Charon v2 will not include autonomous browser-driven form submission.
**Rationale:** ApplyPilot's `apply` stage clones the user's Chrome profile and runs Playwright with `--permission-mode bypassPermissions`. Open security issue #40 in that repo (unaddressed) demonstrates that prompt injection via untrusted job text can pivot into authenticated browser sessions. Charon's whole identity is being the safer alternative. Outputting tailored materials for manual submit preserves the value (AI leverage on writing) without the risk.

### ADR-002 — License-clean reimplementation
**Date:** 2026-04-30
**Decision:** v2 features inspired by ApplyPilot will be reimplemented from scratch using only MIT-compatible upstream libraries.
**Rationale:** Charon is MIT. ApplyPilot is AGPL-3.0. Code copying contaminates the license. JobSpy itself is MIT and can be depended on directly.

### ADR-003 — Token routing per stage
**Date:** 2026-04-30
**Decision:** Judgment-heavy stages (ghostbust, redflags, role_align) stay on Claude Sonnet. Mechanical stages (tailor, letter) route to a cheaper model selectable in profile (Claude Haiku or Gemini Flash).
**Rationale:** Tailoring 200 jobs/week on Sonnet is cost-prohibitive. Resume rewriting is more mechanical than nuanced judgment. Profile flag preserves user control.

### ADR-004 — Gathering feeds a queue, not a pipeline
**Date:** 2026-04-30
**Decision:** `gather` populates a `discoveries` SQLite table. `judge`, `forge`, and `petition` are separate commands that read from and update that table.
**Rationale:** Decouples stages. Lets the user gather cheaply (no LLM cost on raw discovery) and gate the expensive stages behind explicit confirmation. Also makes the daily ops scanner sustainable — it can gather + enrich + judge, but never forge.

### ADR-005 — Themed CLI commands
**Date:** 2026-04-30
**Decision:** v2 CLI commands use ferryman-themed names (`gather`, `judge`, `forge`, `petition`, `provision`, `manifest`) where the metaphor is intuitive. `enrich` stays plain. Internal module names stay descriptive (`discover.py`, `screen.py`, `tailor.py`, `letter.py`, `dashboard.py`).
**Rationale:** Consistent with existing themed commands like `toll`. Theming the UX layer keeps the user-facing experience cohesive without making the codebase confusing for navigation. Phase names and internal table names stay descriptive.

### ADR-006 — ATS-first discovery, no aggregator scraping
**Date:** 2026-04-30
**Decision:** v2 discovery uses public ATS APIs (Greenhouse, Lever, Ashby, Workday) as the primary mechanism, polling a curated employer list in `config/companies.yaml`. JobSpy and aggregator-board scraping are out of scope for v2.0.
**Rationale:** Smoke tests of `python-jobspy` against the four planned boards showed 3/4 broken at probe time (ZipRecruiter 403, Glassdoor API error, Google Jobs returns 0). Indeed worked but with poor relevance for niche security queries — "AI red team" returned generic threat-intelligence jobs. RSS-feed alternatives proved equally dead: Dice, BuiltIn, isecjobs, NinjaJobs all have URLs that *look* like RSS endpoints but actually serve HTML, not feeds. By contrast, the four major employer ATSs all expose clean public JSON APIs designed for embedding company job boards on their own sites. No anti-bot defenses, no scraping middleware, structured data with full descriptions. Probing 140+ candidate employers confirmed strong coverage (47 verified) across the target categories (security product, GRC, audit, AI safety, offensive). The tradeoff: ATS-first requires a curated employer list and misses companies you haven't added. For a personal pivot into security/audit/compliance, that's the right tradeoff — known good employers beat random aggregator noise.
**Implications:**
- No JobSpy dependency.
- No LinkedIn (out per ADR-001 anyway; LinkedIn ATS scraping is ToS-hot regardless).
- No aggregator boards in v2.0; reconsider only if a real RSS feed materializes.
- Adapter quality is per-ATS, not per-employer (one Greenhouse adapter handles all 29 Greenhouse employers). Maintenance burden scales with ATS platforms, not employer count.
- Rippling ATS support deferred — two known employers (BARR, BlackKite) are commented out in companies.yaml awaiting an adapter.
- iCIMS skipped — federal/cleared roles dominate iCIMS surface, out of scope per user preference.

---

## 8. Phase Plan

Phases are sequential. Each must meet its acceptance criteria before the next begins.

---

### Phase 5.5 — Pre-flight cleanup `[ ]`
**Target version:** v0.5.1
**Complexity:** S
**Goal:** Get the repo into a state where v2 work has a clean foundation.

**Scope:**
- Tag current state as `v0.5.0`
- Archive `REQUIREMENTS.md` → `docs/archive/REQUIREMENTS_v1.md`
- Rewrite `README.md` to reflect actual current functionality
- Create `CHANGELOG.md` with single `0.5.0 — pre-v2 baseline` entry
- Verify `LICENSE` file exists at repo root (MIT)
- Investigate `manualList.txt` — keep, document, or delete
- Update `CLAUDE.md` to point to this `ROADMAP.md` as the current plan
- Bump version to 0.5.1 in `pyproject.toml` and `__init__.py`

**Acceptance criteria:**
- [ ] `git tag` shows `v0.5.0` and `v0.5.1`
- [ ] `README.md` accurately describes every shipped command (no "coming soon" for things that ship)
- [ ] `docs/archive/REQUIREMENTS_v1.md` exists; root `REQUIREMENTS.md` removed or stub-pointed
- [ ] `CHANGELOG.md` exists with proper Keep-a-Changelog format
- [ ] `CLAUDE.md` includes a "v2 plan: see ROADMAP.md" pointer
- [ ] `LICENSE` file present and matches `pyproject.toml`
- [ ] All 173 existing tests still pass

**Dependencies:** None
**Risks:** Low. Doc work, no code changes.

---

### Phase 6 — `gather` (the funnel input) `[X]`
**Shipped:** v0.6.0 (2026-05-02)
**Target version:** v0.6.0
**Complexity:** L
**Goal:** Charon gathers jobs from a curated employer list via public ATS APIs. Souls at the riverbank.

**Architecture:** ATS-first. See ADR-006 for the rationale (replaced the original JobSpy-based plan after smoke testing).

**Scope:**
- New package: `charon/gather/` with one adapter per ATS:
  - `gather/greenhouse.py` — `boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=true`
  - `gather/lever.py` — `api.lever.co/v0/postings/<slug>?mode=json`
  - `gather/ashby.py` — `api.ashbyhq.com/posting-api/job-board/<slug>`
  - `gather/workday.py` — POST to `<tenant>.<wd>.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs`
- Single registry: `config/companies.yaml` (already exists, 47 verified entries)
- New SQLite table: `discoveries` (id, ats, slug, company, role, location, url, description, posted_at, discovered_at, dedupe_hash, tier, category, screened_status)
- Auto-detect ATS + slug from any URL pasted via `--add` (Greenhouse/Lever/Ashby/Workday URL patterns are all distinctive)
- Dedupe by URL + by company+role+location fuzzy match
- Skip companies in `applied` table (already in pipeline)
- Skip companies in `blocked` profile list
- New profile section: `gather:` (rate limits per ATS, blocked companies, optional category filter)

**CLI:**
```
charon gather                          # poll all configured employers
charon gather --ats greenhouse         # one platform
charon gather --slug datadog           # one employer
charon gather --add <url>              # auto-detect ATS + slug from any careers/job URL
charon gather --add datadog --ats greenhouse   # explicit fallback when auto-detect fails
charon gather --list                   # show configured employers grouped by ATS
charon gather --dry-run                # preview, don't write to DB
```

**Acceptance criteria:**
- [X] `charon gather --slug datadog` writes Datadog's open jobs to the `discoveries` table
- [X] All four ATS adapters tested against captured-fixture responses (no live network in tests)
- [X] `--add <url>` correctly auto-detects ATS + slug for boards.greenhouse.io, jobs.lever.co, jobs.ashbyhq.com, and *.myworkdayjobs.com URLs
- [X] LinkedIn never queried (no LinkedIn code paths exist)
- [X] Dedupe prevents the same URL appearing twice across runs
- [X] Companies already in `applied` table excluded from results
- [X] Live verification on one slug per ATS — Datadog (426), Sysdig (23), Vanta (147), Schellman (12)
- [X] Inter-employer rate limit honored (default: 1 req/sec, `--rate-limit` flag); Workday adapter additionally paces 1s between paginated calls
- [X] HOWTO.md updated with `gather` workflow
- [X] CHANGELOG entry under v0.6.0

**Dependencies:** Phase 5.5 complete (done at v0.5.1)

**Risks:**
- ATS slugs change (e.g. greynoise → greynoiseintelligence). Mitigation: version-control companies.yaml; fail loud on 404 with the offending slug logged so the user can edit and re-run.
- Workday tenant URLs change. Mitigation: same — fail loud, surface the bad config row in error output.
- Rate-limited if running too aggressively across 47 employers (~6000 jobs total possible per run). Mitigation: per-ATS rate-limit defaults; profile override.
- Companies move ATS (e.g. acquisition or replatforming). Mitigation: log unexpected 404s; user updates companies.yaml when they notice.

**Deferred to later phases:**
- Rippling adapter (BARR Advisory + Black Kite already documented in commented-out section of companies.yaml). Push to v0.6.x patch when DeAnna decides she wants those employers active.
- iCIMS adapter — skipped per user preference (federal-only roles at Coalfire, mostly enterprise/clearance work).
- Aggregator boards (Dice, isecjobs, BuiltIn, NinjaJobs) — they have URLs that look like RSS endpoints but actually serve HTML. Defer indefinitely; revisit if a real feed surfaces.
- 6 employers in TODO block of companies.yaml require manual ATS investigation before they can move into an active section: Snyk, Anchore, Pangea, AuditBoard, Prescient Assurance, Palisade Research.

---

### Phase 7 — Enrichment cascade `[X]`
**Shipped:** v0.7.0 (2026-05-03)
**Target version:** v0.7.0
**Complexity:** M
**Goal:** Better job descriptions for downstream LLM stages, without burning tokens on extraction.

**Scope:**
- Extend `charon/fetcher.py` with three-tier description extraction
- Tier 1: JSON-LD structured data (`<script type="application/ld+json">` with `JobPosting` schema)
- Tier 2: CSS selector library for known ATS (Greenhouse, Lever, Ashby, Workday, iCIMS)
- Tier 3: existing AI extraction (fallback)
- Cache extracted descriptions in `discoveries.full_description`
- New CLI: `charon enrich [--id N | --all]`

**Acceptance criteria:**
- [X] JSON-LD path extracts description from JobPosting markup (verified live on Schellman/Workday: 12/12 jobs caught at tier 1)
- [X] CSS selector library handles Greenhouse, Lever, Ashby, Workday
- [X] AI fallback only triggers when both prior tiers fail
- [X] Extraction tier logged per discovery (`charon enrich --stats` surfaces hit rates)
- [X] Tests with fixtures for each tier
- [X] CHANGELOG entry under v0.7.0

**Dependencies:** Phase 6 complete (needs `discoveries` table populated)
**Risks:** ATS HTML changes. Mitigation: tier 3 fallback always available; track tier-3 rate as a health metric.

---

### Phase 8 — `judge` (batch filtering) `[X]`
**Shipped:** v0.8.0 (2026-05-04)
**Target version:** v0.8.0
**Complexity:** M
**Goal:** Run existing pipeline (ghostbust → redflags → role_align) on enriched discoveries automatically. The Three Judges of the Underworld decide who crosses.

**Scope:**
- New module: `charon/screen.py` (CLI command name: `judge`; orchestrates existing analyzers in batch mode)
- Update `discoveries` table: add `ghost_score`, `redflag_score`, `alignment_score`, `combined_score`, `judgement_reason`, `judged_at`
- Reuses existing `ghostbust.analyze_ghostbust`, `redflags.analyze_redflags`, `hunt.analyze_role_alignment`
- Threshold gating from profile: `gather.judge_thresholds`

**CLI:**
```
charon judge                          # judge all enriched-but-unjudged discoveries
charon judge --min-score 70           # only mark as ready above threshold
charon judge --id N                   # one specific discovery
charon judge --rejudge --id N         # force re-judge (e.g. after profile change)
charon judge --list ready             # list jobs that passed
charon judge --list rejected          # list jobs that failed (with reasons)
```

**Acceptance criteria:**
- [X] Each discovery scored with all three analyses (the three judges)
- [X] Combined score formula documented and matches `hunt`'s logic (minus dossier)
- [X] Failure reason logged on rejection
- [X] Discoveries above combined threshold marked `screened_status='ready'`
- [X] Below threshold marked `screened_status='rejected'`
- [X] Tests cover: threshold gating, rejudge flag, failure reason logging, AI-error handling
- [X] Bulk-run guardrail with cost estimate prompts before >50 judgements
- [X] CHANGELOG entry under v0.8.0

**Dependencies:** Phase 7 complete
**Risks:** Token cost on batch runs. Mitigation: warn before judging >50 jobs at once (`judge.bulk_warn_at`); daily ops scanner caps at N per day (Phase 11).

---

### Phase 8.5 — Resume match + tuning [X]
**Shipped:** v0.8.5 (2026-05-05)
**Complexity:** M
**Goal:** Sharpen the funnel before Phase 9 spends real money on per-job
materials. Add evidence-based fit scoring, give the user knobs to tune the
gate, and fix two failure modes observed in Lever's first live run.

**Scope:**
- Fourth analyzer: `resume_match` reads a configured resume (md/txt/pdf/docx)
  and scores postings on what the candidate has *actually done* vs what the
  posting requires. Catches charitable role_alignment scores on
  industry-adjacent but skill-mismatched roles (e.g. Sales Solutions
  Engineer at a security company).
- Weighted combined-score formula in `profile.judge.weights` with sensible
  defaults skewed toward resume_match.
- `judge.alignment_floor` hard-reject gate. Prevents combined score from
  saving postings whose alignment is near zero.
- `charon judge --reclassify` for free re-gating of stored scores. Tune
  thresholds without paying for analyzer calls.
- `charon judge --status ready/rejected` filter on rejudge — re-score
  just the survivors after tuning instead of re-running everything.
- `charon judge --by-company` aggregation view for spotting patterns
  across multiple postings from the same employer.
- Ctrl+C bug fix: `ai.py` was swallowing the signal as an AIError; now
  propagates so batch loops actually stop.

**Acceptance criteria:**
- [X] Resume analyzer reads .md/.txt/.pdf/.docx
- [X] Configurable via `profile.resume_path`; analyzer skipped cleanly when unset
- [X] Weighted combined formula with profile-driven weights; falls back gracefully for legacy rows
- [X] alignment_floor blocks low-alignment postings regardless of combined
- [X] --reclassify is free and idempotent; preserves judgement_detail
- [X] --status filter on rejudge picks only matching rows
- [X] --by-company aggregates across judged rows; pure SQL
- [X] Ctrl+C aborts batch loops; regression tests pin the behavior
- [X] Live verification: Lever 92 → 14 ready (after floor) → 6 ready (after resume_match)
- [X] CHANGELOG entry under v0.8.5
- [X] HOWTO sections for new flags

**Dependencies:** Phase 8 complete
**Risks:** Resume analyzer prompt may be too strict on edge cases (career
pivots, transferable skills underweighted). Mitigation: match_type categories
(direct/adjacent/stretch/mismatch) make scoring transparent so prompt can be
tuned with --reclassify on existing scores.

---

### Phase 9 — `forge` and `petition` `[X]`
**Sub-phase status:**
- 9.1 (forge) — **shipped v0.9.0 (2026-05-05)**
- 9.2 (petition) — **shipped v0.9.5 (2026-05-05)**
- 9.3 (provision + offerings) — **shipped v0.9.6 (2026-05-05)**
**Target version:** v0.9.0 → v0.9.5 → v0.9.6
**Complexity:** L
**Goal:** Per-job tailored resume (`forge`) and cover letter (`petition`) for jobs that passed `judge`. Provisions for the crossing.

**Scope:**
- New module: `charon/tailor.py` (CLI command name: `forge`) — resume rewriting with `resume_facts` preservation
- New module: `charon/letter.py` (CLI command name: `petition`) — cover letter generation
- New profile sections: `resume_facts` (factual experience model can reorder but not invent), `forge` (model choice, token budget, base resume path)
- Output: per-job markdown files in `~/.charon/offerings/<company>-<role>-<discoveryid>/`
- Files: `resume.md`, `cover_letter.md`, `prompt_used.md` (audit trail)
- Gating: only runs on `screened_status='ready'` discoveries
- Routing: respects `forge.model` profile setting (claude-haiku, claude-sonnet, gemini-flash)

**CLI:**
```
charon forge --id N                    # forge one discovery's resume
charon forge --ready                   # forge all ready discoveries (with confirmation)
charon petition --id N                 # cover letter only
charon provision --id N                # forge + petition together
charon offerings --id N                # show paths to materials for a discovery
charon offerings --open --id N         # open offerings folder
```

**Acceptance criteria:**
- [X] Resume forging preserves facts — verifier extracts numerical claims and confirms each appears in the source resume; surfaces unverified claims as warnings
- [X] Forging prompt includes prompt-injection hardening directives
- [X] Petition references company name and role title from discovery
- [X] Offerings folder created — resume.md + forge_audit.md (9.1), cover_letter.md + petition_audit.md (9.2)
- [X] `charon provision --ready` requires explicit confirmation before bulk run
- [X] Token usage logged per call (in prompt_used.md and CLI summary)
- [X] Model routing works: profile.forge.model determines API target; openrouter: prefix supported
- [X] Tests cover: fact preservation (verifier), prompt construction, model routing, force overwrite
- [X] CHANGELOG entry under v0.9.0

**Dependencies:** Phase 8 complete
**Risks:**
- AI fabrication despite preservation guard. Mitigation: post-generation verifier checks every fact appears verbatim.
- Cost overruns on bulk runs. Mitigation: per-run cost estimate shown before confirmation; hard cap on bulk size.

---

### Phase 10 — `manifest` `[ ]`
**Target version:** v0.10.0
**Complexity:** L
**Goal:** Local HTML dashboard showing the funnel end-to-end. The ferryman's passenger manifest.

**Scope:**
- New module: `charon/dashboard.py` (CLI command name: `manifest`; Python `http.server` based)
- Single HTML template: `charon/templates/manifest.html` with embedded CSS/JS
- Dark SOC theme (already specified in v1 REQUIREMENTS — port over)
- Tabs: **Gathered** (raw discoveries) → **Judged** (screened, both passed and rejected) → **Provisioned** (ready with offerings) → **Crossed** (applications submitted)
- Per-job detail view: scores, evidence, links to offerings folder, "Mark Crossed" button (records via `apply --add`)
- Stats panel: gather rate, judge-pass rate, cross rate, response rate, ghost rate
- Read-only — all writes happen through CLI

**CLI:**
```
charon manifest                        # start server, open browser
charon manifest --port 8080            # custom port
charon manifest --no-open              # don't auto-open browser
```

**Acceptance criteria:**
- [ ] Manifest runs on `localhost:7777` by default
- [ ] All four tabs render with current data (Gathered, Judged, Provisioned, Crossed)
- [ ] Detail view links to offerings folder (file:// links)
- [ ] Stats panel matches `charon apply --stats` numbers
- [ ] Server is read-only (no write endpoints)
- [ ] Single-file HTML (no external CDN dependencies — works offline)
- [ ] Ctrl+C shuts down cleanly
- [ ] Tests cover: route handlers, data binding
- [ ] CHANGELOG entry under v0.10.0

**Dependencies:** Phase 9 complete
**Risks:** Scope creep on UI features. Mitigation: ship minimum viable, iterate.

---

### Phase 11 — Daily integration `[ ]`
**Target version:** v0.11.0
**Complexity:** M
**Goal:** Ops server runs gather + enrich + judge on cron; user manually triggers forge/petition when ready to apply.

**Scope:**
- Extend `/opt/charon-daily/run-daily.py` to:
  - Run `charon gather` against profile searches
  - Run `charon enrich` on new discoveries
  - Run `charon judge` on enriched discoveries
  - Add new ready jobs to digest
- Cap per-day gather and judge volume (token budget)
- Digest format addition: "New high-fit jobs found: N. Top 5: ..."
- `forge`/`petition` intentionally NOT in cron — too token-heavy and user wants control

**Acceptance criteria:**
- [ ] Daily scanner runs gather → enrich → judge end-to-end
- [ ] Per-day caps enforced (configurable in profile)
- [ ] Digest includes new ready jobs section
- [ ] Existing daily-scanner CRITICAL rules still hold (no auto-push, etc. — see CLAUDE.local.md)
- [ ] CHANGELOG entry under v0.11.0

**Dependencies:** Phase 8 complete (8 is the minimum; could ship before 9/10)
**Risks:** Token cost runaway. Mitigation: hard daily cap.

---

## 9. Risk Register

| # | Risk | Probability | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Token costs on bulk forging exceed budget | High | Medium | Gating thresholds + cheaper model routing per ADR-003 |
| R2 | JobSpy upstream breaks / sites add anti-scraping | Medium | High | Per-source error handling; multiple sources so one breaking isn't fatal |
| R3 | ATS sites change CSS, breaking enrichment tier 2 | High | Low | Tier 3 AI fallback always available |
| R4 | Workday tenant list goes stale | Medium | Medium | Quarterly review; YAML is easy to update |
| R5 | Prompt injection in job text manipulates tailoring | Medium | Medium | Hardened prompts + post-gen fact verifier (Phase 9) |
| R6 | AI fabrication in resume despite guards | Medium | High | Post-generation verifier compares output against `resume_facts` literally |
| R7 | DB sync corruption from new `discoveries` table | Low | High | Schema migration script + dry-run + backup before first deploy |
| R8 | License contamination from copying ApplyPilot code | Low | High | ADR-002 — never copy, always reimplement |
| R9 | Scope creep into auto-apply territory | Medium | High | Non-goals (§2) are explicit and enforced — refer back when tempted |
| R10 | Dashboard becomes a project of its own | Medium | Low | Ship minimum viable in Phase 10, iterate later |

---

## 10. Success Metrics

How do we know v2 worked?

**Quantitative:**
- Funnel volume: ≥50 gathered/week after Phase 6 ships
- Judgement efficiency: ≥10% pass rate (the rest correctly rejected as ghost/toxic/misaligned)
- Time-to-apply: <5 minutes from "open manifest" to "submitted in browser" for a ready job
- Token cost: <$10/week steady-state on Claude Sonnet (judgment stages only)

**Qualitative:**
- DeAnna applies to more jobs that match her actual targets, fewer that don't.
- The morning digest tells her something useful most days.
- She trusts every application that goes out — none are AI-fabricated, none have errors.

**Anti-metrics (alarms if these happen):**
- Bulk forging run that fabricates a fact in resume_facts → halt Phase 9, fix verifier
- A LinkedIn API call appearing in any log → halt, audit codepath
- An autonomous browser action of any kind → halt, audit codepath

---

## 11. Out-of-Scope Ideas (Parked, Not Cut)

Things that came up but aren't in v2. Revisit after v2 ships.

- **Networking integration** (LinkedIn-free contact discovery). Would help with the actual job market but is its own project.
- **Salary inference** when posting omits range. Useful but lower priority than the funnel.
- **Multi-profile support** (e.g. one for security, one for ML). YAGNI for now.
- **Public PyPI release.** Not a goal until v1.0.
- **Web app version.** Stays CLI-first.

---

## 12. Status Tracker

Update this after every phase ships. Last entry on top.

| Date | Version | Phase | Status | Notes |
|---|---|---|---|---|
| 2026-05-05 | 0.9.6 | 9.3 | shipped | `charon provision` (forge + petition wrapper) and `charon offerings` (browse materials). Phase 9 complete. 438 tests. |
| 2026-05-05 | 0.9.5 | 9.2 | shipped | `charon petition` writes voice-tuned cover letters. Geographic-fabrication rule added after first live run hallucinated "I'm in the UK." 426 tests. Live: re-petitioned Coalfire honestly, surfaced UK-only requirement. |
| 2026-05-05 | 0.9.0 | 9.1 | shipped | `charon forge` tailors resumes per ready discovery. Post-gen verifier flags fabricated numerical claims. 417 tests. Live: forged Coalfire SOC role at $0.005, verifier clean. |
| 2026-05-05 | 0.8.5 | 8.5 | shipped | Resume match analyzer + weights + alignment_floor + reclassify + by-company + Ctrl+C fix. 392 tests. Live: Lever 92 → 14 (floor) → 6 ready (resume_match). |
| 2026-05-04 | 0.8.0 | 8 | shipped | `charon judge` runs the three v1 analyzers in batch on enriched discoveries. 359 tests. Bulk-run guardrail. Live: Schellman #1 judged at combined 75.0 (READY). |
| 2026-05-03 | 0.7.0 | 7 | shipped | Three-tier enrichment cascade (JSON-LD → ATS CSS → LLM with pluggable model routing). 334 tests. Live test: 12/12 Schellman jobs enriched at tier 1, $0 token spend. |
| 2026-05-02 | 0.6.0 | 6 | shipped | All four ATS adapters live (Greenhouse, Lever, Ashby, Workday) + `--add <url>` auto-detect. 293 tests, 47 employers verified. Funnel input is online. |
| 2026-04-30 | 0.5.3 | 6 (scoping) | architecture finalized | ATS-first per ADR-006. companies.yaml seeded with 47 verified employers. Ready to begin Phase 6 implementation in next session. |
| 2026-04-30 | 0.5.2 | 5.5 cleanup | shipped | Three pre-existing test failures fixed. Suite green at 187/187. |
| 2026-04-30 | 0.5.1 | 5.5 | shipped | Pre-v2 cleanup: ROADMAP, CHANGELOG, LICENSE, README rewrite, REQUIREMENTS archived. |
| 2026-04-30 | 0.5.0 | (baseline) | tagged | Pre-v2 baseline. All v1 phases shipped. |
| 2026-04-30 | — | Plan | drafted | This document created |

---

## 13. Document History

- **2026-04-30** — Initial v2 plan drafted (DeAnna + Claude Code session). Replaces v1's `REQUIREMENTS.md` as the active planning doc.
