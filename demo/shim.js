/* Charon demo shim: the real dashboard page with no backend.
 *
 * window.fetch is replaced so every /api call is answered here, from the
 * snapshot build_demo.py embedded as window.__CHARON_DEMO__ (payloads made by
 * the real dashboard code against a fake database). Actions change that
 * in-memory state, so the page behaves like the app for one visit. Nothing
 * leaves the browser; a reload starts over.
 *
 * Every route the page calls must appear in ROUTES below. tests/test_demo.py
 * checks that against manifest.html, so a new endpoint fails the build until
 * the demo knows how to answer it.
 */
(function () {
  "use strict";

  const D = window.__CHARON_DEMO__;
  if (!D) return;

  // ── keep the sample data current ────────────────────────────────────
  // Every timestamp moves forward by however many whole weeks have passed
  // since the build, so "harvested 3h ago" stays true-ish and weekly chart
  // buckets still start on a Monday.
  const WEEK_MS = 7 * 24 * 3600 * 1000;
  const SHIFT = Math.max(0, Math.floor((Date.now() - Date.parse(D.built_at)) / WEEK_MS)) * WEEK_MS;
  const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
  const ISO_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?$/;

  function shifted(value) {
    if (Array.isArray(value)) return value.map(shifted);
    if (value && typeof value === "object") {
      const out = {};
      for (const k of Object.keys(value)) out[k] = (k === "b64") ? value[k] : shifted(value[k]);
      return out;
    }
    if (SHIFT && typeof value === "string") {
      if (ISO_TIME.test(value)) return new Date(Date.parse(value) + SHIFT).toISOString();
      if (ISO_DATE.test(value)) return new Date(Date.parse(value + "T00:00:00Z") + SHIFT).toISOString().slice(0, 10);
    }
    return value;
  }

  const clone = (v) => JSON.parse(JSON.stringify(v));
  const nowIso = () => new Date().toISOString();
  const key = (name) => String(name || "").split(/\s+/).filter(Boolean).join(" ").toLowerCase();
  const daysSince = (iso) => Math.floor((Date.now() - Date.parse(iso)) / (24 * 3600 * 1000));

  const O = shifted(D.opening);
  const REVEAL = shifted(D.reveal);
  const DETAILS = shifted(D.details);
  const LETTERS = D.letters;

  const S = {
    ready: O.ready,
    gathered: O.gathered,
    gatheredTotal: O.gathered_total,
    refused: O.refused,            // keyed by window: "30", "90", "all"
    apps: O.applications_all,      // every application; is_archived marks the hidden ones
    stats: O.stats,
    research: shifted(D.research), // dossier/contacts payloads by history id
    salaryMd: Object.assign({}, D.salary_md),
    jobs: { dossier: {}, contacts: {} },
    prepJobs: {},
    ferry: clone(D.ferry.fresh),
    ferryNextStep: 0,
    judgeRevealed: false,
    nextAppId: Math.max(0, ...O.applications_all.map((a) => a.id)) + 1,
    nextHistoryId: 9001,
  };

  // Demo stand-ins for work that takes minutes in the real app.
  const RESEARCH_MS = 8000;
  const SALARY_MS = 2500;
  const FERRY_STEP_MS = 2000;

  // ── responses ───────────────────────────────────────────────────────
  const json = (obj, status) => new Response(JSON.stringify(obj), {
    status: status || 200,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
  const fail = (msg, status) => json({ error: msg }, status || 400);
  const text = (body, status) => new Response(body, {
    status: status || 200,
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
  const later = (ms, fn) => new Promise((resolve) => setTimeout(() => resolve(fn()), ms));

  // ── research jobs (dossiers + contacts) ─────────────────────────────
  const KIND_FIELD = { dossier: "dossier", contacts: "company_contacts" };

  function jobRunning(kind, company) {
    const job = S.jobs[kind][key(company)];
    return !!(job && job.running);
  }

  function eachCardFor(company, fn) {
    const k = key(company);
    S.ready.forEach((d) => { if (key(d.company) === k) fn(d); });
    S.apps.forEach((a) => { if (key(a.company) === k) fn(a); });
  }

  function latestIndex(kind, company) {
    let found = null;
    eachCardFor(company, (d) => { if (d[KIND_FIELD[kind]]) found = d[KIND_FIELD[kind]]; });
    return found;
  }

  // What a finished search "found": the build's pre-made result if there is
  // one, otherwise the company's existing record, re-dated.
  function researchResult(kind, company) {
    const pending = REVEAL.research[kind][key(company)];
    if (pending) {
      delete REVEAL.research[kind][key(company)];
      return clone(pending);
    }
    const id = S.nextHistoryId++;
    const prev = latestIndex(kind, company);
    const base = prev && S.research[kind][prev.id]
      ? clone(S.research[kind][prev.id])
      : (kind === "dossier"
        ? { company, weighted_score: 70, overall_score: 68, summary: "Sample dossier.", verdict: "Sample verdict.", dimensions: {}, stock: null }
        : { company, contacts: [], search_notes: "Sample data. Nobody turned up outside LinkedIn." });
    const when = nowIso();
    const score = kind === "dossier" ? base.weighted_score : (base.contacts || []).length;
    Object.assign(base, { id, built_at: when, age_days: 0, stale: false, is_latest: true });
    return { index: { id, built_at: when, score, age_days: 0, stale: false }, payload: base };
  }

  function finishResearch(kind, company) {
    const job = S.jobs[kind][key(company)];
    const found = researchResult(kind, company);
    // Payload ids come from the build's database; keep them so links match.
    const prev = latestIndex(kind, company);
    if (prev && S.research[kind][prev.id]) S.research[kind][prev.id].is_latest = false;
    S.research[kind][found.index.id] = found.payload;
    eachCardFor(company, (d) => { d[KIND_FIELD[kind]] = found.index; });
    Object.assign(job, { running: false, finished_at: nowIso(), error: null, history_id: found.index.id });
  }

  function startResearch(kind, discoveryId) {
    const card = S.ready.find((d) => d.id === discoveryId) || S.apps.find((a) => a.discovery_id === discoveryId);
    if (!card) return fail(`No discovery with id ${discoveryId}.`);
    const company = card.company;
    if (jobRunning(kind, company)) {
      return fail(`${kind === "dossier" ? "A dossier" : "A contacts search"} on ${company} is already being built.`);
    }
    S.jobs[kind][key(company)] = {
      running: true, company, started_at: nowIso(), finished_at: null,
      error: null, history_id: null, due: Date.now() + RESEARCH_MS,
    };
    return json({ ok: true, job: researchSnapshot(kind, company) });
  }

  function researchSnapshot(kind, company) {
    const job = Object.assign({}, S.jobs[kind][key(company)] || {});
    delete job.due;
    job[kind] = latestIndex(kind, company);
    if (job.running == null) job.running = false;
    return job;
  }

  // ── prep (the blank letter) ─────────────────────────────────────────
  function applyPrep(id) {
    const card = S.ready.find((d) => d.id === id);
    const made = REVEAL.prep[String(id)];
    Object.assign(card, made.card);
    return { id, errors: [], offerings_path: made.card.offerings_path, letter_path: made.card.offerings_path + "/cover_letter.docx", greeting: made.greeting, ok: true };
  }

  function startPrep(id) {
    const card = S.ready.find((d) => d.id === id);
    if (!card) return fail(`No discovery with id ${id}.`);
    if ((S.prepJobs[id] || {}).running) return fail(`#${id} is already being prepped.`);
    if (!REVEAL.prep[String(id)]) {
      return fail("The demo only has sample letters for the postings it started with.");
    }
    if (card.company_contacts) {
      return json({ ok: true, summary: applyPrep(id), ready: readyPayload() });
    }
    if (!jobRunning("contacts", card.company)) {
      S.jobs.contacts[key(card.company)] = {
        running: true, company: card.company, started_at: nowIso(), finished_at: null,
        error: null, history_id: null, due: Date.now() + RESEARCH_MS,
      };
    }
    S.prepJobs[id] = { running: true, company: card.company, started_at: nowIso(), finished_at: null, error: null, summary: null };
    return json({ ok: true, pending: true, job: Object.assign({}, S.prepJobs[id]) });
  }

  // ── the ferry ───────────────────────────────────────────────────────
  const PER_ROW = (() => {
    const e = D.ferry.estimates;
    const n = e.judgeable_count || 1;
    return { costLow: e.cost_low / n, costHigh: e.cost_high / n, secsLow: e.secs_per_row_low, secsHigh: e.secs_per_row_high, basis: e.time_basis };
  })();

  function estimates(n) {
    return {
      judgeable_count: n,
      cost_low: Math.round(n * PER_ROW.costLow * 100) / 100,
      cost_high: Math.round(n * PER_ROW.costHigh * 100) / 100,
      secs_per_row_low: PER_ROW.secsLow,
      secs_per_row_high: PER_ROW.secsHigh,
      time_basis: PER_ROW.basis,
      est_minutes_low: n ? Math.max(1, Math.round(n * PER_ROW.secsLow / 60)) : 0,
      est_minutes_high: n ? Math.max(1, Math.round(n * PER_ROW.secsHigh / 60)) : 0,
    };
  }

  function parkAtGate() {
    const f = S.ferry;
    const n = S.stats.judgeable || 0;
    Object.assign(f, estimates(n));
    f.phase = n > 0 ? "awaiting_judge" : "done";
    f.running = false;
    f.finished_at = nowIso();
  }

  // One step of whichever stage is running. Each stage takes a few steps so
  // the progress bar has something to show.
  function stepFerry() {
    const f = S.ferry;
    const st = S.stats;
    if (f.phase === "gather") {
      const g = f.gather;
      g.total_employers = D.ferry.employers;
      g.completed_employers = Math.min(g.total_employers, g.completed_employers + Math.ceil(g.total_employers / 3));
      g.total_new = Math.round(74 * g.completed_employers / g.total_employers);
      g.total_dupes = Math.round(4210 * g.completed_employers / g.total_employers);
      g.total_errors = g.completed_employers >= g.total_employers ? 3 : 0;
      if (g.completed_employers >= g.total_employers) {
        st.gathered += g.total_new;
        st.unjudged += g.total_new;
        st.cullable += g.total_new;
        S.gatheredTotal += g.total_new;
        st.last_gather = nowIso();
        f.phase = "cull";
        f.cull.limit = st.cullable;
      }
    } else if (f.phase === "cull") {
      const c = f.cull;
      c.processed = Math.min(c.limit, c.processed + Math.ceil(c.limit / 2));
      c.passed = Math.round(c.processed * 0.32);
      c.refused = c.processed - c.passed;
      if (c.processed >= c.limit) {
        st.culled += c.refused;
        st.judged += c.refused;
        st.refused += c.refused;
        st.unjudged -= c.refused;
        st.cullable = 0;
        S.gatheredTotal -= c.refused;
        f.phase = "enrich";
        f.enrich.limit = c.passed + (st.awaiting_enrich || 0);
      }
    } else if (f.phase === "enrich") {
      const en = f.enrich;
      en.processed = Math.min(en.limit, en.processed + Math.ceil(en.limit / 2));
      // Every description fetches in the demo: a failure would surface as
      // "N stuck" on the action strip.
      en.closed = Math.round(en.processed * 0.04);
      en.failed = 0;
      en.paid = Math.round(en.processed * 0.08);
      en.recovered = en.processed - en.closed;
      if (en.processed >= en.limit) {
        st.judgeable += en.recovered;
        st.awaiting_enrich = 0;
        parkAtGate();
      }
    } else if (f.phase === "judge") {
      const j = f.judge;
      j.processed = Math.min(j.limit, j.processed + Math.ceil(j.limit / 3));
      const found = S.judgeRevealed ? 0 : Math.min(REVEAL.judged_ready.length, j.limit);
      j.ready_added = Math.min(found, j.processed);
      j.refused_added = j.processed - j.ready_added;
      if (j.processed >= j.limit) {
        if (found) {
          S.judgeRevealed = true;
          REVEAL.judged_ready.slice(0, found).forEach((d) => S.ready.push(d));
          S.ready.sort((a, b) => (b.combined_score || 0) - (a.combined_score || 0));
        }
        st.judged += j.limit;
        st.judged_sonnet += j.limit;
        st.refused += j.refused_added;
        st.judgeable = Math.max(0, st.judgeable - j.limit);
        st.unjudged = Math.max(0, st.unjudged - j.limit);
        S.gatheredTotal = Math.max(S.gathered.length, S.gatheredTotal - j.limit);
        parkAtGate();
      }
    }
  }

  function ferryStatus() {
    if (S.ferry.running && Date.now() >= S.ferryNextStep) {
      stepFerry();
      S.ferryNextStep = Date.now() + FERRY_STEP_MS;
    }
    return clone(S.ferry);
  }

  function startFerry(body) {
    if (S.ferry.running) return fail("The ferry is already crossing.");
    if (body && body.stage === "judge") {
      if (S.ferry.phase !== "awaiting_judge") return fail("The ferry isn't waiting at the judge gate.");
      const n = S.stats.judgeable || 0;
      const batch = body.limit ? Math.min(Number(body.limit), n) : n;
      if (batch < 1) return fail("Judge batch size must be at least 1.");
      Object.assign(S.ferry, {
        judge: { limit: batch, processed: 0, ready_added: 0, refused_added: 0, skipped: 0 },
        running: true, phase: "judge", error: null, finished_at: null,
      });
    } else {
      const from = (body && body.from) || "gather";
      if (!["gather", "cull", "enrich", "judge"].includes(from)) return fail(`Unknown ferry stage: '${from}'`);
      S.ferry = clone(D.ferry.fresh);
      Object.assign(S.ferry, { running: true, phase: from, started_at: nowIso() });
      if (from === "cull") S.ferry.cull.limit = S.stats.cullable || 0;
      if (from === "enrich") S.ferry.enrich.limit = S.stats.awaiting_enrich || 0;
      if (from === "judge") parkAtGate();
    }
    S.ferryNextStep = Date.now() + FERRY_STEP_MS;
    return json({ ok: true, status: clone(S.ferry) });
  }

  // ── list payloads ───────────────────────────────────────────────────
  // Building flags are live, like the server's, so a reload mid-search
  // still shows "Searching…".
  function withFlags(d, discoveryId) {
    return Object.assign({}, d, {
      dossier_building: jobRunning("dossier", d.company),
      company_contacts_building: jobRunning("contacts", d.company),
      prep_building: discoveryId != null && !!(S.prepJobs[discoveryId] || {}).running,
    });
  }

  const readyPayload = () => S.ready.map((d) => withFlags(d, d.id));

  function appsPayload(includeArchived) {
    const shown = S.apps.filter((a) => includeArchived || !a.is_archived);
    return shown.map((a) => withFlags(Object.assign({}, a, { days_since: daysSince(a.applied_at) }), null));
  }

  function refreshAppStats() {
    const st = S.stats;
    const count = {};
    S.apps.forEach((a) => { count[a.status] = (count[a.status] || 0) + 1; });
    const total = S.apps.length;
    st.applied_total = total;
    st.stranded = count.ghosted || 0;
    st.pending = count.applied || 0;
    st.engaged = total - st.stranded - st.pending;
    st.reply_rate = total ? Math.round(st.engaged / total * 1000) / 10 : null;
    if (st.breakdown) st.breakdown.forEach((b) => { b.count = count[b.status] || 0; });
    if (st.funnel) {
      st.funnel.forEach((f) => {
        if (f.key === "applied") f.count = total;
        if (f.key === "engaged") f.count = st.engaged;
        if (f.key === "offered") f.count = count.offered || 0;
      });
    }
  }

  function statsPayload(withCharts) {
    const s = clone(S.stats);
    s.ready = S.ready.length;
    if (s.funnel) {
      s.funnel.forEach((f) => {
        if (f.key === "gathered") f.count = s.gathered;
        if (f.key === "judged") f.count = s.judged_sonnet;
        if (f.key === "ready") f.count = s.ready;
      });
    }
    if (!withCharts) { delete s.breakdown; delete s.funnel; delete s.weekly; }
    return s;
  }

  function refusedWindow(raw) {
    const w = (raw === "all" || raw === "0") ? "all" : (raw === "90" ? "90" : "30");
    return S.refused[w];
  }

  function addRefused(card, reason) {
    const row = Object.assign({}, card, {
      judgement_reason: reason || card.judgement_reason,
      judgement_digest: null,
      digest_deferred: true,
    });
    Object.values(S.refused).forEach((w) => {
      w.refused.unshift(Object.assign({}, row));
      w.total += 1;
      w.total_all += 1;
    });
    S.stats.refused += 1;
  }

  // ── the router ──────────────────────────────────────────────────────
  // "METHOD /path/:param" → handler(params, query, body)
  const ROUTES = [
    ["GET /api/env", () => json({ env: D.env })],
    ["GET /api/ready", () => json({ ready: readyPayload() })],
    ["GET /api/gathered", () => json({ gathered: S.gathered.slice(), total: S.gatheredTotal })],
    ["GET /api/refused", (p, q) => {
      const w = refusedWindow(q.get("days") || "30");
      return json({ refused: w.refused.slice(), total: w.total, total_all: w.total_all, days: w.days });
    }],
    ["GET /api/applications", (p, q) => {
      const all = ["1", "true", "yes"].includes(q.get("archived") || "");
      return json({ applications: appsPayload(all), archived_hidden: all ? 0 : S.apps.filter((a) => a.is_archived).length });
    }],
    ["GET /api/stats", (p, q) => json({ stats: statsPayload(["1", "true", "yes"].includes(q.get("charts") || "")) })],
    ["GET /api/detail/:id", (p) => detail(p.id)],
    ["GET /api/description/:id", (p) => detail(p.id)],
    ["GET /api/dossier/status", (p, q) => json({ job: researchSnapshot("dossier", q.get("company") || "") })],
    ["GET /api/company-contacts/status", (p, q) => json({ job: researchSnapshot("contacts", q.get("company") || "") })],
    ["GET /api/dossier/:id", (p) => {
      const ds = S.research.dossier[p.id];
      return ds ? json({ dossier: ds }) : fail(`No dossier with id ${p.id}.`, 404);
    }],
    ["GET /api/company-contacts/:id", (p) => {
      const cs = S.research.contacts[p.id];
      return cs ? json({ contacts: cs }) : fail(`No contacts search with id ${p.id}.`, 404);
    }],
    ["GET /api/prep/status", (p, q) => {
      const job = Object.assign({ running: false }, S.prepJobs[Number(q.get("discovery_id"))] || {});
      return json({ job });
    }],
    ["GET /api/offerings/:id/:file", (p) => {
      if (p.file === "salary_intel.md" && S.salaryMd[p.id]) return text(S.salaryMd[p.id]);
      return text(`${p.file} not generated for #${p.id}.`, 404);
    }],
    ["GET /api/ferry/status", () => json({ status: ferryStatus() })],
    ["GET /api/judge/status", () => json({ status: { running: false } })],
    ["GET /api/cull/status", () => json({ status: { running: false } })],
    ["GET /api/enrich/status", () => json({ status: { running: false } })],
    ["GET /api/gather/status", () => json({ status: { running: false } })],
    ["GET /api/sirens/question", () => json({ question: "If this posting were honest about the role, what would its first line say?" })],
    ["GET /api/sirens/drafts", () => json({ drafts: [] })],

    ["POST /api/ferry", (p, q, body) => startFerry(body || {})],
    ["POST /api/dossier/build", (p, q, body) => startResearch("dossier", Number((body || {}).discovery_id))],
    ["POST /api/company-contacts/build", (p, q, body) => startResearch("contacts", Number((body || {}).discovery_id))],
    ["POST /api/provision/:id", (p) => startPrep(Number(p.id))],
    ["POST /api/salary/:id", (p) => {
      const id = Number(p.id);
      const card = S.ready.find((d) => d.id === id) || S.apps.find((a) => a.discovery_id === id);
      if (!card) return fail(`No discovery with id ${id}.`);
      const md = REVEAL.salary_md[String(id)] || S.salaryMd[String(id)];
      if (!md) return fail("The demo only has salary intel for the postings it started with.");
      return later(SALARY_MS, () => {
        const salary = Object.assign({}, REVEAL.salary, { fetched_at: nowIso() });
        S.salaryMd[String(id)] = md;
        eachCardFor(card.company, (d) => {
          if ((d.discovery_id != null ? d.discovery_id : d.id) === id) {
            d.has_salary = true;
            d.salary_data = salary;
          }
        });
        return json({ ok: true, salary, ready: readyPayload() });
      });
    }],
    ["POST /api/apply/:id", (p, q, body) => {
      const id = Number(p.id);
      const d = S.ready.find((r) => r.id === id);
      if (!d) return fail(`No discovery with id ${id}.`);
      S.ready = S.ready.filter((r) => r.id !== id);
      const when = nowIso();
      const app = Object.assign({}, d, {
        id: S.nextAppId++, status: "applied", applied_at: when, updated_at: when,
        notes: (body && body.notes) || null, days_since: 0, discovery_id: id,
        has_offerings: !!d.offerings_path, is_archived: false,
      });
      S.apps.unshift(app);
      refreshAppStats();
      return json({ ok: true, application: { id: app.id, company: app.company, role: app.role, status: "applied" }, ready: readyPayload() });
    }],
    ["POST /api/reject/:id", (p, q, body) => {
      const id = Number(p.id);
      const reason = ((body && body.reason) || "").trim() || null;
      const d = S.ready.find((r) => r.id === id);
      if (d) {
        S.ready = S.ready.filter((r) => r.id !== id);
        addRefused(d, reason);
      } else if (S.gathered.some((g) => g.id === id)) {
        S.gathered = S.gathered.filter((g) => g.id !== id);
        S.gatheredTotal = Math.max(0, S.gatheredTotal - 1);
      } else {
        return fail(`No discovery with id ${id}.`);
      }
      return json({ ok: true, rejection: { id, reason }, ready: readyPayload() });
    }],
    ["POST /api/unreject/:id", (p) => {
      const id = Number(p.id);
      let row = null;
      Object.values(S.refused).forEach((w) => {
        const hit = w.refused.find((r) => r.id === id);
        if (hit) {
          row = row || hit;
          w.refused = w.refused.filter((r) => r.id !== id);
          w.total = Math.max(0, w.total - 1);
          w.total_all = Math.max(0, w.total_all - 1);
        }
      });
      if (!row) return fail(`Discovery #${id} isn't refused or expired.`);
      S.stats.refused = Math.max(0, S.stats.refused - 1);
      S.ready.push(Object.assign({}, row, {
        dossier: latestIndex("dossier", row.company),
        company_contacts: latestIndex("contacts", row.company),
      }));
      S.ready.sort((a, b) => (b.combined_score || 0) - (a.combined_score || 0));
      return json({ ok: true, unrejected: { id, new_status: "ready" }, ready: readyPayload(), refused: S.refused["30"].refused.slice() });
    }],
    ["POST /api/expire", (p, q, body) => {
      const days = Number((body || {}).days || 30);
      if (!(days >= 1 && days <= 3650)) return fail("days must be between 1 and 3650.");
      if (S.ferry.running) return fail("A ferry job is already running — wait for it.");
      const stale = S.ready.filter((d) => d.judged_at && daysSince(d.judged_at) > days);
      S.ready = S.ready.filter((d) => !stale.includes(d));
      S.stats.expired = (S.stats.expired || 0) + stale.length;
      return json({ ok: true, result: { expired: stale.length, days }, ready: readyPayload() });
    }],
    ["POST /api/ghost-check", () => {
      const days = 21;
      const hit = S.apps.filter((a) => a.status === "applied" && daysSince(a.applied_at) >= days);
      hit.forEach((a) => { a.status = "ghosted"; a.updated_at = nowIso(); });
      refreshAppStats();
      return json({
        ok: true,
        summary: { days, ghosted: hit.map((a) => ({ id: a.id, company: a.company, role: a.role })), count: hit.length },
        applications: appsPayload(false),
      });
    }],
    ["POST /api/applications/:id/status", (p, q, body) => {
      const id = Number(p.id);
      const status = body && body.status;
      const valid = ["applied", "acknowledged", "responded", "interviewing", "offered", "rejected", "ghosted"];
      if (!valid.includes(status)) return fail(`Invalid status '${status}'.`);
      const a = S.apps.find((x) => x.id === id);
      if (!a) return fail(`No application with id ${id}.`);
      a.status = status;
      a.updated_at = nowIso();
      refreshAppStats();
      return json({ ok: true, updated: { id, status }, applications: appsPayload(false) });
    }],
    ["POST /api/judge/prompt", (p, q, body) => {
      const limit = Math.min(25, Math.max(1, Number((body || {}).limit) || 5));
      const ids = S.gathered.filter((g) => g.enrichment_tier).slice(0, limit).map((g) => g.id);
      return json({
        ok: true, batch_id: "demo0000", batch_size: ids.length, discovery_ids: ids,
        prompt: "# Charon paste-judge (demo)\n\nIn the real app this is a self-contained prompt: the analyzer " +
          "instructions, the profile, a résumé excerpt and the postings below, for Claude Code to judge " +
          "without spending API credit. The demo leaves the contents out.\n\nPostings: " + ids.join(", ") + "\n",
      });
    }],
    ["POST /api/sirens/polish", (p, q, body) => {
      const post = ((body && body.brain_dump) || "").trim() || "Sample post.";
      return json({ ok: true, result: { post, char_count: post.length, over_limit: post.length > 3000, notes: "Demo: no AI was called.", voice_warnings: [] } });
    }],
  ].map(([spec, handler]) => {
    const [method, path] = spec.split(" ");
    const names = [];
    const re = new RegExp("^" + path.replace(/:([a-z]+)/g, (m, name) => { names.push(name); return "([^/]+)"; }) + "$");
    return { method, re, names, handler };
  });

  function detail(id) {
    const d = DETAILS[String(id)];
    return d ? json(d) : fail(`No discovery with id ${id}.`, 404);
  }

  // Finish whatever demo jobs have come due. Called on every request, so the
  // state the page reads is always current.
  function settle() {
    const now = Date.now();
    ["dossier", "contacts"].forEach((kind) => {
      Object.values(S.jobs[kind]).forEach((job) => {
        if (job.running && now >= job.due) finishResearch(kind, job.company);
      });
    });
    Object.keys(S.prepJobs).forEach((id) => {
      const job = S.prepJobs[id];
      if (job.running && !jobRunning("contacts", job.company)) {
        job.summary = applyPrep(Number(id));
        job.running = false;
        job.finished_at = nowIso();
      }
    });
  }

  function route(method, url, body) {
    settle();
    const u = new URL(url, "https://demo.invalid");
    const path = decodeURIComponent(u.pathname);
    for (const r of ROUTES) {
      if (r.method !== method) continue;
      const m = path.match(r.re);
      if (!m) continue;
      const params = {};
      r.names.forEach((n, i) => { params[n] = m[i + 1]; });
      return r.handler(params, u.searchParams, body);
    }
    return fail("That isn't part of the demo.", 404);
  }

  // ── install ─────────────────────────────────────────────────────────
  const realFetch = window.fetch ? window.fetch.bind(window) : null;
  window.fetch = function (input, init) {
    const url = typeof input === "string" ? input : (input && input.url) || "";
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    if (path.indexOf("/api/") === 0) {
      const method = ((init && init.method) || (input && input.method) || "GET").toUpperCase();
      let body = null;
      if (init && typeof init.body === "string") {
        try { body = JSON.parse(init.body); } catch (e) { body = null; }
      }
      try {
        return Promise.resolve(route(method, path, body));
      } catch (e) {
        return Promise.resolve(fail("Demo error: " + e.message, 500));
      }
    }
    return realFetch ? realFetch(input, init) : Promise.reject(new Error("offline demo"));
  };

  // Offering files open with window.open. The letter is a real .docx made by
  // Charon's Prep code for the sample applicant, so hand it over as a download.
  const realOpen = window.open ? window.open.bind(window) : null;
  window.open = function (url, name, features) {
    const m = typeof url === "string" && url.match(/^\/api\/offerings\/(\d+)\/([^/?#]+)$/);
    if (m) {
      const letter = LETTERS[m[1]];
      if (/\.docx$/.test(m[2]) && letter) {
        const bytes = Uint8Array.from(atob(letter.b64), (c) => c.charCodeAt(0));
        const blob = new Blob([bytes], { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" });
        const href = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = href;
        a.download = letter.filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(href), 10000);
      }
      return null;
    }
    return realOpen ? realOpen(url, name, features) : null;
  };

  function paintBanner() {
    const b = document.getElementById("dev-banner");
    if (!b) return;
    b.innerHTML =
      "<strong>Demo</strong> · Charon, a job-hunt tool for security work, running on made-up data. " +
      "The buttons work, but nothing leaves your browser: no searches run and nothing is spent. " +
      "Reload to start over.";
    b.hidden = false;
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", paintBanner);
  else paintBanner();
})();
