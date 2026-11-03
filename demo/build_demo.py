"""Build the public demo: the real dashboard page running on fake data.

    python demo/build_demo.py                 # writes demo/dist/charon-demo.html
    python demo/build_demo.py --out some.html

The page is charon/templates/manifest.html, unchanged except for a scrub of
personal details, with demo/shim.js answering every /api call in the browser.
The shim's data comes from the real dashboard functions: this script seeds a
throwaway database from demo/fixtures.py, calls _ready_discoveries(),
_stats() and friends, and embeds what they return. When a payload changes
shape, the demo picks it up on the next build.

Nothing here touches ~/.charon. The database, offerings folders and résumé
all live in a temp directory that's deleted afterwards.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEMO_DIR = Path(__file__).resolve().parent
REPO = DEMO_DIR.parent
MANIFEST = REPO / "charon" / "templates" / "manifest.html"
ASSETS = REPO / "charon" / "templates" / "assets"
SHIM = DEMO_DIR / "shim.js"
DEFAULT_OUT = DEMO_DIR / "dist" / "charon-demo.html"

# Anything personal that must never reach the public page. The build fails
# if one survives the scrub.
FORBIDDEN = ("deanna", "shanks", "lurka", "empire12", "port53", "192.168.")

# Exact replacements in the page source; each must match at least once, so a
# renamed string fails the build instead of slipping through.
SCRUBS = (
    ("DeAnna's funnel · ferryman view", "Sample funnel · ferryman view"),
    ("DeAnna Shanks", "Sample Applicant"),
    (
        'Live job-hunt data lives at <a href="https://charon.empire12.net" '
        'target="_blank" rel="noopener">charon.empire12.net</a>. ',
        "",
    ),
)

# Longest edge, in px, for each inlined image: the avatar and empty-state art
# show at sidebar width, the tab icons at icon size. 2x for sharp screens.
IMAGE_MAX_PX = {"charon.png": 560, "charon-boat.png": 640, "charon_hourglass.png": 160}
ICON_MAX_PX = 96


# ── time ────────────────────────────────────────────────────────────────


def _iso(now: datetime, *, days: float = 0, hours: float = 0) -> str:
    return (now - timedelta(days=days, hours=hours)).isoformat()


# ── seeding ─────────────────────────────────────────────────────────────


def _make_resume(path: Path) -> Path:
    """A fake résumé: letterhead first, then all-caps bold sections."""
    from docx import Document
    from docx.shared import Pt

    from fixtures import CANDIDATE

    doc = Document()
    doc.core_properties.author = CANDIDATE["name"]
    doc.core_properties.last_modified_by = CANDIDATE["name"]
    name = doc.add_paragraph().add_run(CANDIDATE["name"])
    name.bold = True
    name.font.size = Pt(26)
    doc.add_paragraph(CANDIDATE["headline"])
    doc.add_paragraph(CANDIDATE["contact"])
    doc.add_paragraph()
    doc.add_paragraph().add_run("PROFESSIONAL SUMMARY").bold = True
    doc.add_paragraph(CANDIDATE["summary"])
    doc.save(str(path))
    return path


def _insert_discovery(conn: sqlite3.Connection, now: datetime, row: dict[str, Any],
                      *, status: str, n: int) -> int:
    from fixtures import desc

    judged = row.get("judged_days_ago")
    scores = row.get("scores") or {}
    detail = row.get("detail")
    enrich = row.get("enrichment_tier", "jsonld")
    description = (
        desc(row["role"], row["company"], row.get("extra", "")) if enrich else None
    )
    discovered = (
        _iso(now, hours=row["hours_ago"]) if "hours_ago" in row
        else _iso(now, days=(judged or 0) + 1)
    )
    slug = re.sub(r"[^a-z0-9]+", "", row["company"].lower())
    cur = conn.execute(
        "INSERT INTO discoveries (ats, slug, company, role, location, url, description, "
        "posted_at, discovered_at, dedupe_hash, tier, category, screened_status, "
        "full_description, enrichment_tier, enriched_at, culled_at, "
        "ghost_score, redflag_score, alignment_score, combined_score, resume_match_score, "
        "monoculture_score, judgement_reason, judgement_detail, judged_at, expired_at, "
        "last_seen_at, seen_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            row.get("ats") or "greenhouse", slug, row["company"], row["role"],
            row.get("location", "Remote (US)"),
            f"https://jobs.example.com/{slug}/{n}",
            None, None, discovered, f"demo-{n}",
            row.get("tier"), row.get("category"), status,
            description, enrich, discovered if enrich else None,
            discovered if enrich or judged is not None else None,
            scores.get("ghost"), scores.get("redflag"), scores.get("alignment"),
            row.get("combined", scores.get("combined")),
            scores.get("resume_match"), scores.get("monoculture"),
            row.get("reason"),
            json.dumps(detail) if detail else None,
            _iso(now, days=judged) if judged is not None else None,
            _iso(now, days=judged - 1) if status == "expired" else None,
            discovered, 1,
        ),
    )
    return cur.lastrowid


def _save_research(kind: str, company: str, result: dict[str, Any], *,
                   now: datetime, age_days: float) -> int:
    from charon.db import get_connection, save_history

    score = (
        result.get("weighted_score") if kind == "dossier"
        else float(len(result.get("contacts") or []))
    )
    history_id = save_history(kind, "company", company, score, result, company=company)
    conn = get_connection()
    try:
        conn.execute("UPDATE history SET timestamp = ? WHERE id = ?",
                     (_iso(now, days=age_days), history_id))
        conn.commit()
    finally:
        conn.close()
    return history_id


def _write_salary(discovery: dict[str, Any], base: Path, s: dict[str, Any], now: datetime) -> None:
    from charon.db import get_connection
    from charon.salary import SALARY_FILENAME
    from charon.tailor import offerings_folder

    from fixtures import salary_md

    folder = offerings_folder(discovery, base_dir=str(base))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / SALARY_FILENAME).write_text(
        salary_md(discovery["company"], discovery["role"], s), encoding="utf-8"
    )
    cached = dict(s, fetched_at=_iso(now, days=2))
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE discoveries SET salary_data = ?, offerings_path = ? WHERE id = ?",
            (json.dumps(cached), str(folder), discovery["id"]),
        )
        conn.commit()
    finally:
        conn.close()


def _prep(discovery_id: int, profile: dict[str, Any]) -> dict[str, Any]:
    """Run the real Prep on a row; returns its summary."""
    from charon.db import get_discovery
    from charon.prep import prep_discovery

    summary = prep_discovery(get_discovery(discovery_id), profile)
    if summary.get("errors") or not summary.get("letter_path"):
        raise RuntimeError(f"demo prep failed for #{discovery_id}: {summary}")
    return summary


# ── snapshots (the real payload builders) ───────────────────────────────


def _detail(discovery_id: int) -> dict[str, Any]:
    from charon.dashboard import _summarize_discovery
    from charon.db import get_discovery

    row = get_discovery(discovery_id)
    return {
        "id": discovery_id,
        "full_description": row.get("full_description") or "",
        "judgement_digest": _summarize_discovery(row)["judgement_digest"],
    }


def _ready_by_id() -> dict[int, dict[str, Any]]:
    from charon.dashboard import _ready_discoveries

    return {d["id"]: d for d in _ready_discoveries()}


def _company_key(name: str) -> str:
    return " ".join((name or "").split()).casefold()


def _docx_title(discovery: dict[str, Any]) -> str:
    from fixtures import CANDIDATE

    safe = re.sub(r'[\\/:*?"<>|]+', "-", f"{CANDIDATE['name']} - {discovery['company']} - "
                  f"{discovery['role']} - Cover Letter")
    return f"{safe}.docx"


# ── page assembly ───────────────────────────────────────────────────────


def _image_data_uri(path: Path, *, resize: bool) -> str:
    raw = path.read_bytes()
    if resize:
        try:
            from PIL import Image
        except ImportError:
            resize = False
    if resize:
        limit = IMAGE_MAX_PX.get(path.name, ICON_MAX_PX)
        img = Image.open(io.BytesIO(raw))
        img.thumbnail((limit, limit))
        out = io.BytesIO()
        img.save(out, format="WEBP", quality=86, method=6)
        return "data:image/webp;base64," + base64.b64encode(out.getvalue()).decode("ascii")
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _script_json(data: Any) -> str:
    """JSON that's safe inside a <script> element."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return (
        text.replace("</", "<\\/")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def _assemble(data: dict[str, Any], *, resize_images: bool) -> str:
    html = MANIFEST.read_text(encoding="utf-8")

    for old, new in SCRUBS:
        if old not in html:
            raise RuntimeError(f"scrub target not found in manifest.html: {old[:60]!r}")
        html = html.replace(old, new)

    def inline(m: re.Match[str]) -> str:
        path = ASSETS / m.group(1)
        if not path.is_file():
            raise RuntimeError(f"missing asset: {path.name}")
        return _image_data_uri(path, resize=resize_images)

    html = re.sub(r"/static/([A-Za-z0-9_.-]+\.png)", inline, html)

    html = html.replace(
        "<title>Charon · The Crossing</title>",
        "<title>Charon · The Crossing (demo)</title>",
        1,
    )
    head_extra = (
        '<meta name="description" content="A walkthrough of Charon, a job-hunt tool for '
        'security work, running on sample data.">\n'
    )
    html = html.replace("</head>", head_extra + "</head>", 1)

    shim = SHIM.read_text(encoding="utf-8")
    payload = (
        f"<script>window.__CHARON_DEMO__ = {_script_json(data)};</script>\n"
        f"<script>\n{shim}\n</script>\n"
    )
    first_script = html.find("<script")
    if first_script < 0:
        raise RuntimeError("manifest.html has no <script>; the shim has nowhere to go")
    html = html[:first_script] + payload + html[first_script:]

    lowered = html.lower()
    leaks = [t for t in FORBIDDEN if t in lowered]
    if leaks:
        raise RuntimeError(f"personal details survived the scrub: {leaks}")
    return html


def _scrub_paths(value: Any, root: str) -> Any:
    """Rewrite temp-dir paths (which carry the builder's username) to /demo/..."""
    if isinstance(value, dict):
        return {k: _scrub_paths(v, root) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_paths(v, root) for v in value]
    if isinstance(value, str) and root in value:
        tail = value.split(root, 1)[1].replace("\\", "/")
        return "/demo" + tail
    return value


# ── the build ───────────────────────────────────────────────────────────


def collect(work: Path) -> dict[str, Any]:
    """Seed a database under `work` and return everything the shim serves."""
    import charon.db as db
    from charon import dashboard as dash

    import fixtures as fx

    now = datetime.now(timezone.utc).replace(microsecond=0)
    original_db = db.DB_PATH
    db.DB_PATH = work / "demo.db"
    db.init_db()
    try:
        resume = _make_resume(work / "Sample_Applicant_Resume.docx")
        offerings = work / "offerings"
        profile = {
            "resumes": {"ir": str(resume), "grc": str(resume)},
            "forge": {"offerings_dir": str(offerings)},
        }

        # Research on file before the demo starts.
        for company, result in fx.DOSSIERS.items():
            age = 200 if company == "NorthBeacon Labs" else 12
            _save_research("dossier", company, result, now=now, age_days=age)
        for company, result in fx.CONTACTS.items():
            _save_research("contacts", company, result, now=now, age_days=10)

        n = 0
        conn = db.get_connection()
        try:
            ready_ids: dict[str, int] = {}
            for row in fx.READY:
                n += 1
                ready_ids[row["key"]] = _insert_discovery(conn, now, row, status="ready", n=n)
            for row in fx.GATHERED:
                n += 1
                _insert_discovery(conn, now, row, status="new", n=n)
            for row in fx.REFUSED:
                n += 1
                _insert_discovery(conn, now, dict(row, enrichment_tier="jsonld"), status="rejected", n=n)
            for row in fx.EXPIRED:
                n += 1
                _insert_discovery(conn, now, dict(row, reason="Judged ready; archived as stale.",
                                                  scores={"combined": 63.0}),
                                  status="expired", n=n)
            applied_ids: dict[str, int] = {}
            template = fx.READY[0]["detail"]
            for app in fx.APPLICATIONS:
                link = app.get("from_ready")
                if link:
                    n += 1
                    applied_ids[app["company"]] = _insert_discovery(conn, now, {
                        "company": app["company"], "role": app["role"],
                        "ats": link["ats"], "tier": link["tier"], "category": link["category"],
                        "judged_days_ago": app["applied_days_ago"] + 1,
                        "scores": {"combined": 79.0, "alignment": 80, "ghost": 12, "redflag": 18,
                                   "resume_match": 78, "monoculture": 26},
                        "reason": "Judged ready, then applied.", "detail": template,
                    }, status="applied", n=n)
                conn.execute(
                    "INSERT INTO applications (company, role, url, status, applied_at, "
                    "updated_at, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (app["company"], app["role"],
                     f"https://jobs.example.com/{re.sub(r'[^a-z0-9]+', '', app['company'].lower())}",
                     app["status"], _iso(now, days=app["applied_days_ago"]),
                     _iso(now, days=app["updated_days_ago"]), app.get("notes")),
                )
            conn.commit()
        finally:
            conn.close()

        from charon.db import get_discovery

        # Salary intel and letters already made before the demo starts.
        for row in fx.READY:
            if row["state"]["salary"]:
                _write_salary(get_discovery(ready_ids[row["key"]]), offerings,
                              fx.SALARIES[row["key"]], now)
        for app in fx.APPLICATIONS:
            key = f"app:{app['company']}"
            if key in fx.SALARIES:
                _write_salary(get_discovery(applied_ids[app["company"]]), offerings,
                              fx.SALARIES[key], now)

        letters: dict[str, dict[str, str]] = {}

        def keep_letter(discovery_id: int, summary: dict[str, Any]) -> None:
            discovery = get_discovery(discovery_id)
            letters[str(discovery_id)] = {
                "filename": _docx_title(discovery),
                "b64": base64.b64encode(Path(summary["letter_path"]).read_bytes()).decode("ascii"),
            }

        for row in fx.READY:
            if row["state"]["prepped"]:
                keep_letter(ready_ids[row["key"]], _prep(ready_ids[row["key"]], profile))
        for app in fx.APPLICATIONS:
            if (app.get("from_ready") or {}).get("prepped"):
                keep_letter(applied_ids[app["company"]], _prep(applied_ids[app["company"]], profile))

        # ── the opening state ──
        apps, archived_hidden = dash._applications()
        apps_all, _ = dash._applications(include_archived=True)
        stats = dash._stats(include_charts=True)
        unknown = set(fx.STATS_OVERRIDES) - set(stats)
        if unknown:
            raise RuntimeError(f"STATS_OVERRIDES names keys /api/stats no longer has: {unknown}")
        stats.update(fx.STATS_OVERRIDES)
        for stage in stats.get("funnel") or []:
            if stage["key"] == "gathered":
                stage["count"] = fx.STATS_OVERRIDES["gathered"]
            elif stage["key"] == "judged":
                stage["count"] = fx.STATS_OVERRIDES["judged_sonnet"]

        refused = {}
        for days in (30, 90, None):
            refused["all" if days is None else str(days)] = {
                "refused": dash._refused_discoveries(days=days),
                "total": fx.REFUSED_TOTALS[days],
                "total_all": fx.REFUSED_TOTALS[None],
                "days": days,
            }

        research: dict[str, dict[str, Any]] = {"dossier": {}, "contacts": {}}
        conn = db.get_connection()
        try:
            history = conn.execute("SELECT id, command FROM history").fetchall()
        finally:
            conn.close()
        for history_id, command in history:
            payload = (dash._dossier_payload(history_id) if command == "dossier"
                       else dash._contacts_payload(history_id))
            research[command][str(history_id)] = payload

        all_ids = [r[0] for r in _all_discovery_ids(db)]
        details = {str(i): _detail(i) for i in all_ids}

        salary_md: dict[str, str] = {}
        from charon.salary import SALARY_FILENAME
        for discovery_id in all_ids:
            folder = (get_discovery(discovery_id) or {}).get("offerings_path")
            if folder and (Path(folder) / SALARY_FILENAME).is_file():
                salary_md[str(discovery_id)] = (Path(folder) / SALARY_FILENAME).read_text(encoding="utf-8")

        opening = {
            "ready": list(_ready_by_id().values()),
            "gathered": dash._gathered_discoveries(),
            "gathered_total": fx.GATHERED_TOTAL,
            "refused": refused,
            "applications": apps,
            "applications_all": apps_all,
            "archived_hidden": archived_hidden,
            "stats": stats,
        }

        # ── what the demo's actions reveal ──
        # Rows the demo judge "finds".
        conn = db.get_connection()
        try:
            reserve_ids = []
            for row in fx.RESERVE_READY:
                n += 1
                reserve_ids.append(_insert_discovery(conn, now, row, status="ready", n=n))
            conn.commit()
        finally:
            conn.close()
        ready_now = _ready_by_id()
        reserve = [ready_now[i] for i in reserve_ids]
        for i in reserve_ids:
            details[str(i)] = _detail(i)

        # Research the demo's buttons "run".
        pending: dict[str, dict[str, Any]] = {"dossier": {}, "contacts": {}}
        for kind, source in (("dossier", fx.PENDING_DOSSIERS), ("contacts", fx.PENDING_CONTACTS)):
            for company, result in source.items():
                history_id = _save_research(kind, company, result, now=now, age_days=0)
                index = dash._research_index(kind)[_company_key(company)]
                payload = (dash._dossier_payload(history_id) if kind == "dossier"
                           else dash._contacts_payload(history_id))
                pending[kind][_company_key(company)] = {"index": index, "payload": payload}

        # Prep on every card that doesn't have a letter yet, with the research
        # above in place, so each greeting is the one the demo search implies.
        prep_results: dict[str, dict[str, Any]] = {}
        for discovery_id in [ready_ids[r["key"]] for r in fx.READY if not r["state"]["prepped"]] + reserve_ids:
            summary = _prep(discovery_id, profile)
            keep_letter(discovery_id, summary)
            card = _ready_by_id()[discovery_id]
            prep_results[str(discovery_id)] = {
                "greeting": summary["greeting"],
                "card": {k: card[k] for k in (
                    "offerings_path", "petition_at", "has_letter", "letter_file",
                    "letter_flags", "letter_flag_items", "has_resume", "resume_file",
                )},
            }

        pending_salary_md = {
            str(d["id"]): fx.salary_md(d["company"], d["role"], fx.PENDING_SALARY)
            for d in list(opening["ready"]) + reserve
            if str(d["id"]) not in salary_md
        }

        data = {
            "built_at": now.isoformat(),
            "env": {"deployment": "demo", "is_local": False, "db_path": "sample data, not real"},
            "opening": opening,
            "details": details,
            "research": research,
            "salary_md": salary_md,
            "letters": letters,
            "reveal": {
                "judged_ready": reserve,
                "research": pending,
                "prep": prep_results,
                "salary": fx.PENDING_SALARY,
                "salary_md": pending_salary_md,
            },
            "ferry": {
                "employers": fx.FERRY_EMPLOYERS,
                "estimates": dash._ferry_judge_estimates(fx.STATS_OVERRIDES["judgeable"]),
                "fresh": dash._fresh_ferry_state(),
            },
        }
        return _scrub_paths(data, str(work))
    finally:
        db.DB_PATH = original_db


def _all_discovery_ids(db: Any) -> list[tuple[int]]:
    conn = db.get_connection()
    try:
        return conn.execute("SELECT id FROM discoveries ORDER BY id").fetchall()
    finally:
        conn.close()


def build(out: Path = DEFAULT_OUT, *, resize_images: bool = True) -> dict[str, Any]:
    """Write the demo page to `out`. Returns a small summary for the caller."""
    sys.path.insert(0, str(DEMO_DIR))
    with tempfile.TemporaryDirectory(prefix="charon-demo-") as tmp:
        data = collect(Path(tmp))
    html = _assemble(data, resize_images=resize_images)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8", newline="\n")
    return {
        "out": str(out),
        "bytes": len(html.encode("utf-8")),
        "ready": len(data["opening"]["ready"]),
        "applications": len(data["opening"]["applications"]),
        "letters": len(data["letters"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--no-resize", action="store_true",
                        help="inline the images at full size (no Pillow needed)")
    args = parser.parse_args()
    # Point the import-time database at a scratch file so building never
    # creates or migrates the real ~/.charon/charon.db.
    scratch = Path(tempfile.mkdtemp(prefix="charon-demo-import-"))
    os.environ["CHARON_DB_PATH"] = str(scratch / "import.db")
    sys.path.insert(0, str(REPO))
    summary = build(args.out, resize_images=not args.no_resize)
    kb = summary["bytes"] / 1024
    print(f"wrote {summary['out']} ({kb:,.0f} KB): {summary['ready']} ready, "
          f"{summary['applications']} applications, {summary['letters']} letters")


if __name__ == "__main__":
    main()
