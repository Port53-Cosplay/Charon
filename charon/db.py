"""SQLite history and watchlist database."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from charon.profile import ensure_charon_dir


DB_PATH = ensure_charon_dir() / "charon.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    command TEXT NOT NULL,
    input_type TEXT NOT NULL,
    input_value TEXT NOT NULL,
    score REAL,
    result_json TEXT NOT NULL,
    company TEXT
);

CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL UNIQUE,
    added_at TEXT NOT NULL,
    last_checked TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS digest_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    queued_at TEXT NOT NULL,
    entry_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    detail_json TEXT,
    sent INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_history_timestamp ON history(timestamp);
CREATE INDEX IF NOT EXISTS idx_history_command ON history(command);
CREATE INDEX IF NOT EXISTS idx_watchlist_company ON watchlist(company);
CREATE INDEX IF NOT EXISTS idx_digest_sent ON digest_queue(sent);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    url TEXT,
    email_domain TEXT,
    status TEXT NOT NULL DEFAULT 'applied',
    applied_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    ghosted_notified INTEGER NOT NULL DEFAULT 0,
    dossier_at TEXT,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
CREATE INDEX IF NOT EXISTS idx_applications_company ON applications(company);

CREATE TABLE IF NOT EXISTS discoveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ats TEXT NOT NULL,
    slug TEXT NOT NULL,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    location TEXT,
    url TEXT NOT NULL,
    description TEXT,
    posted_at TEXT,
    discovered_at TEXT NOT NULL,
    dedupe_hash TEXT NOT NULL UNIQUE,
    tier TEXT,
    category TEXT,
    screened_status TEXT NOT NULL DEFAULT 'new'
);

CREATE INDEX IF NOT EXISTS idx_discoveries_ats ON discoveries(ats);
CREATE INDEX IF NOT EXISTS idx_discoveries_slug ON discoveries(slug);
CREATE INDEX IF NOT EXISTS idx_discoveries_company ON discoveries(company);
CREATE INDEX IF NOT EXISTS idx_discoveries_screened ON discoveries(screened_status);
"""


MIGRATIONS = [
    "ALTER TABLE applications ADD COLUMN dossier_at TEXT",
    "ALTER TABLE discoveries ADD COLUMN full_description TEXT",
    "ALTER TABLE discoveries ADD COLUMN enrichment_tier TEXT",
    "ALTER TABLE discoveries ADD COLUMN enriched_at TEXT",
    "ALTER TABLE discoveries ADD COLUMN ghost_score REAL",
    "ALTER TABLE discoveries ADD COLUMN redflag_score REAL",
    "ALTER TABLE discoveries ADD COLUMN alignment_score REAL",
    "ALTER TABLE discoveries ADD COLUMN combined_score REAL",
    "ALTER TABLE discoveries ADD COLUMN judgement_reason TEXT",
    "ALTER TABLE discoveries ADD COLUMN judgement_detail TEXT",
    "ALTER TABLE discoveries ADD COLUMN judged_at TEXT",
    "ALTER TABLE discoveries ADD COLUMN resume_match_score REAL",
    "ALTER TABLE discoveries ADD COLUMN forged_at TEXT",
    "ALTER TABLE discoveries ADD COLUMN offerings_path TEXT",
    "ALTER TABLE discoveries ADD COLUMN petition_at TEXT",
]


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Apply schema migrations for existing databases."""
    for migration in MIGRATIONS:
        try:
            conn.execute(migration)
        except sqlite3.OperationalError:
            pass  # Column already exists


def get_connection() -> sqlite3.Connection:
    """Get a database connection with WAL mode and foreign keys."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Initialize the database schema and run migrations."""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        _run_migrations(conn)
        conn.commit()
    finally:
        conn.close()


def save_history(
    command: str,
    input_type: str,
    input_value: str,
    score: float | None,
    result: dict[str, Any],
    company: str | None = None,
) -> int:
    """Save a command result to history. Returns the row ID."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO history (timestamp, command, input_type, input_value, score, result_json, company) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                command,
                input_type,
                input_value,
                score,
                json.dumps(result),
                company,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_history(limit: int = 20) -> list[dict[str, Any]]:
    """Retrieve recent history entries."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, timestamp, command, input_type, input_value, score, company "
            "FROM history ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def clear_history() -> int:
    """Delete all history entries. Returns the number of rows deleted."""
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM history")
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def add_watch(company: str, notes: str | None = None) -> None:
    """Add a company to the watchlist."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (company, added_at, notes) VALUES (?, ?, ?)",
            (company, datetime.now(timezone.utc).isoformat(), notes),
        )
        conn.commit()
    finally:
        conn.close()


def remove_watch(company: str) -> bool:
    """Remove a company from the watchlist. Returns True if removed."""
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM watchlist WHERE company = ?", (company,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_watchlist() -> list[dict[str, Any]]:
    """Retrieve all watched companies."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, company, added_at, last_checked, notes "
            "FROM watchlist ORDER BY company"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def queue_digest(entry_type: str, summary: str, detail: dict[str, Any] | None = None) -> None:
    """Add an entry to the digest queue."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO digest_queue (queued_at, entry_type, summary, detail_json) VALUES (?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                entry_type,
                summary,
                json.dumps(detail) if detail else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_unsent_digest() -> list[dict[str, Any]]:
    """Retrieve unsent digest entries."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, queued_at, entry_type, summary, detail_json "
            "FROM digest_queue WHERE sent = 0 ORDER BY queued_at"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def mark_digest_sent(entry_ids: list[int]) -> None:
    """Mark digest entries as sent."""
    if not entry_ids:
        return
    conn = get_connection()
    try:
        placeholders = ",".join("?" for _ in entry_ids)
        conn.execute(
            f"UPDATE digest_queue SET sent = 1 WHERE id IN ({placeholders})",
            entry_ids,
        )
        conn.commit()
    finally:
        conn.close()


VALID_STATUSES = {"applied", "acknowledged", "responded", "interviewing", "offered", "rejected", "ghosted"}


def add_application(
    company: str,
    role: str,
    url: str | None = None,
    email_domain: str | None = None,
    notes: str | None = None,
) -> int:
    """Add a job application. Returns the row ID."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO applications (company, role, url, email_domain, status, applied_at, updated_at, notes) "
            "VALUES (?, ?, ?, ?, 'applied', ?, ?, ?)",
            (company, role, url, email_domain, now, now, notes),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def delete_application(app_id: int) -> bool:
    """Delete an application by ID. Returns True if deleted."""
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def update_application_status(app_id: int, status: str) -> bool:
    """Update an application's status. Returns True if updated."""
    if status not in VALID_STATUSES:
        return False
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE applications SET status = ?, updated_at = ? WHERE id = ?",
            (status, datetime.now(timezone.utc).isoformat(), app_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_applications(status: str | None = None) -> list[dict[str, Any]]:
    """Retrieve applications, optionally filtered by status."""
    conn = get_connection()
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM applications WHERE status = ? ORDER BY applied_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM applications ORDER BY applied_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_application(app_id: int) -> dict[str, Any] | None:
    """Retrieve a single application by ID."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM applications WHERE id = ?", (app_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


PASSIVE_STATUSES = ("applied", "acknowledged", "responded")
ACTIVE_STATUSES = ("interviewing",)


def get_stale_applications(days: int) -> list[dict[str, Any]]:
    """Get applications that haven't really moved in N days.

    Two date anchors so the rule matches what "silence" actually means:

      - **Passive statuses** (applied / acknowledged / responded) — anchor
        to `applied_at`. An automated "we got your application" email is
        not real engagement, so it shouldn't restart the silence clock.
        If you applied 60 days ago and they auto-acked at day 1, the
        clock still says ~60 days of company silence.

      - **Active statuses** (interviewing) — anchor to `updated_at`. A
        recent interview round IS real engagement; the clock starts from
        the last move.

    Excludes:
      - 'offered'  — positive terminal state, don't auto-strand
      - 'rejected' — already terminal
      - 'ghosted'  — already terminal (legacy DB value for stranded)
    """
    passive_p = ",".join("?" for _ in PASSIVE_STATUSES)
    active_p = ",".join("?" for _ in ACTIVE_STATUSES)
    conn = get_connection()
    try:
        # Compare calendar days (date()-truncated), not raw julianday — a
        # timestamp at 21:30 UTC vs now at 18:00 UTC was producing 20.95
        # for what intuitively should be "21 days ago today."
        rows = conn.execute(
            f"SELECT * FROM applications "
            f"WHERE ghosted_notified = 0 AND ("
            f"  (status IN ({passive_p}) "
            f"   AND julianday(date('now')) - julianday(date(applied_at)) >= ?) "
            f"  OR "
            f"  (status IN ({active_p}) "
            f"   AND julianday(date('now')) - julianday(date(updated_at)) >= ?) "
            f") "
            f"ORDER BY applied_at",
            (*PASSIVE_STATUSES, days, *ACTIVE_STATUSES, days),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def mark_ghosted(app_ids: list[int]) -> None:
    """Mark applications as ghosted."""
    if not app_ids:
        return
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        placeholders = ",".join("?" for _ in app_ids)
        conn.execute(
            f"UPDATE applications SET status = 'ghosted', ghosted_notified = 1, updated_at = ? "
            f"WHERE id IN ({placeholders})",
            [now] + app_ids,
        )
        conn.commit()
    finally:
        conn.close()


def update_application_dossier(app_id: int) -> bool:
    """Mark that a dossier was run for an application. Returns True if updated."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE applications SET dossier_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), app_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def find_application_by_company(company: str) -> dict[str, Any] | None:
    """Find the most recent active application for a company (case-insensitive)."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM applications WHERE LOWER(company) = LOWER(?) "
            "AND status NOT IN ('rejected', 'ghosted') "
            "ORDER BY applied_at DESC LIMIT 1",
            (company,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_application_stats() -> dict[str, int]:
    """Get application count by status."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) as count FROM applications GROUP BY status"
        ).fetchall()
        return {row["status"]: row["count"] for row in rows}
    finally:
        conn.close()


VALID_DISCOVERY_STATUSES = {"new", "enriched", "ready", "rejected", "applied"}


def add_discovery(
    ats: str,
    slug: str,
    company: str,
    role: str,
    url: str,
    dedupe_hash: str,
    location: str | None = None,
    description: str | None = None,
    posted_at: str | None = None,
    tier: str | None = None,
    category: str | None = None,
) -> int | None:
    """Insert a discovery. Returns the row ID, or None if dedupe_hash already exists."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO discoveries "
            "(ats, slug, company, role, location, url, description, posted_at, "
            "discovered_at, dedupe_hash, tier, category, screened_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')",
            (
                ats,
                slug,
                company,
                role,
                location,
                url,
                description,
                posted_at,
                datetime.now(timezone.utc).isoformat(),
                dedupe_hash,
                tier,
                category,
            ),
        )
        conn.commit()
        return cursor.lastrowid if cursor.rowcount > 0 else None
    finally:
        conn.close()


def discovery_exists(dedupe_hash: str) -> bool:
    """Check whether a discovery with this dedupe_hash already exists."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM discoveries WHERE dedupe_hash = ? LIMIT 1",
            (dedupe_hash,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


_ORDER_CLAUSES = {
    "discovered_at": "discovered_at DESC",
    # SQLite sorts NULLs last in DESC by default — judged rows have a score,
    # any unjudged stragglers fall to the bottom.
    "combined_score": "combined_score DESC, discovered_at DESC",
}


def get_discoveries(
    ats: str | None = None,
    slug: str | None = None,
    status: str | None = None,
    limit: int | None = None,
    order_by: str = "discovered_at",
) -> list[dict[str, Any]]:
    """Retrieve discoveries with optional filters.

    `order_by` is a literal key into a whitelist (`discovered_at` or
    `combined_score`) — never interpolate user input directly.
    """
    if order_by not in _ORDER_CLAUSES:
        raise ValueError(
            f"order_by must be one of {sorted(_ORDER_CLAUSES)}, got '{order_by}'."
        )

    clauses: list[str] = []
    params: list[Any] = []
    if ats:
        clauses.append("ats = ?")
        params.append(ats)
    if slug:
        clauses.append("slug = ?")
        params.append(slug)
    if status:
        clauses.append("screened_status = ?")
        params.append(status)

    sql = "SELECT * FROM discoveries"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += f" ORDER BY {_ORDER_CLAUSES[order_by]}"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_discovery(discovery_id: int) -> dict[str, Any] | None:
    """Retrieve a single discovery by ID."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM discoveries WHERE id = ?", (discovery_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_discovery_counts() -> dict[str, int]:
    """Return discovery counts per ATS."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT ats, COUNT(*) as count FROM discoveries GROUP BY ats"
        ).fetchall()
        return {row["ats"]: row["count"] for row in rows}
    finally:
        conn.close()


VALID_ENRICHMENT_TIERS = {"skipped", "jsonld", "ats_css", "ai_fallback", "failed"}


def update_discovery_enrichment(
    discovery_id: int,
    tier: str,
    full_description: str | None,
) -> bool:
    """Record enrichment results on a discovery. Returns True if updated."""
    if tier not in VALID_ENRICHMENT_TIERS:
        raise ValueError(
            f"Unknown enrichment tier '{tier}'. Valid: {sorted(VALID_ENRICHMENT_TIERS)}"
        )
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE discoveries SET full_description = ?, enrichment_tier = ?, "
            "enriched_at = ? WHERE id = ?",
            (
                full_description,
                tier,
                datetime.now(timezone.utc).isoformat(),
                discovery_id,
            ),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_unenriched_discoveries(
    ats: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Discoveries that haven't been enriched yet (enrichment_tier IS NULL)."""
    clauses = ["enrichment_tier IS NULL"]
    params: list[Any] = []
    if ats:
        clauses.append("ats = ?")
        params.append(ats)

    sql = "SELECT * FROM discoveries WHERE " + " AND ".join(clauses)
    sql += " ORDER BY discovered_at DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_enrichment_counts() -> dict[str, int]:
    """Return enrichment counts per tier (NULL counted as 'unenriched')."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT COALESCE(enrichment_tier, 'unenriched') AS tier, COUNT(*) AS count "
            "FROM discoveries GROUP BY enrichment_tier"
        ).fetchall()
        return {row["tier"]: row["count"] for row in rows}
    finally:
        conn.close()


def update_discovery_judgement(
    discovery_id: int,
    *,
    ghost_score: float,
    redflag_score: float,
    alignment_score: float,
    combined_score: float,
    screened_status: str,
    judgement_reason: str,
    judgement_detail: dict[str, Any] | None = None,
    resume_match_score: float | None = None,
) -> bool:
    """Persist judge results on a discovery. Returns True if updated."""
    if screened_status not in {"ready", "rejected"}:
        raise ValueError(
            f"screened_status must be 'ready' or 'rejected', got '{screened_status}'."
        )
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE discoveries SET "
            "  ghost_score = ?, redflag_score = ?, alignment_score = ?, "
            "  resume_match_score = ?, combined_score = ?, screened_status = ?, "
            "  judgement_reason = ?, judgement_detail = ?, judged_at = ? "
            "WHERE id = ?",
            (
                ghost_score,
                redflag_score,
                alignment_score,
                resume_match_score,
                combined_score,
                screened_status,
                judgement_reason,
                json.dumps(judgement_detail) if judgement_detail is not None else None,
                datetime.now(timezone.utc).isoformat(),
                discovery_id,
            ),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def mark_discovery_applied(discovery_id: int) -> bool:
    """Flip a discovery's screened_status to 'applied'. Bridge from apply().
    Returns True if a row was updated.
    """
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE discoveries SET screened_status = 'applied' WHERE id = ?",
            (discovery_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def mark_discovery_rejected(discovery_id: int, reason: str | None = None) -> bool:
    """Flip a discovery's screened_status to 'rejected' with an optional reason.
    Used by the dashboard's "Not for me" action. Returns True if updated.

    If a reason is provided, it overwrites judgement_reason — surfacing the
    user's explicit rejection above whatever the AI judge said.
    """
    conn = get_connection()
    try:
        if reason:
            cursor = conn.execute(
                "UPDATE discoveries SET screened_status = 'rejected', "
                "judgement_reason = ? WHERE id = ?",
                (reason, discovery_id),
            )
        else:
            cursor = conn.execute(
                "UPDATE discoveries SET screened_status = 'rejected' WHERE id = ?",
                (discovery_id,),
            )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def update_discovery_classification(
    discovery_id: int,
    *,
    screened_status: str,
    combined_score: float,
    judgement_reason: str,
) -> bool:
    """Update only the gating outcome on a discovery — leaves analyzer
    detail and per-component scores untouched. Used by `judge --reclassify`
    after tuning thresholds, when no AI calls were made.
    """
    if screened_status not in {"ready", "rejected"}:
        raise ValueError(
            f"screened_status must be 'ready' or 'rejected', got '{screened_status}'."
        )
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE discoveries SET combined_score = ?, screened_status = ?, "
            "judgement_reason = ? WHERE id = ?",
            (combined_score, screened_status, judgement_reason, discovery_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_unjudged_discoveries(
    ats: str | None = None,
    require_enriched: bool = True,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Discoveries that haven't been judged yet (judged_at IS NULL).

    By default also requires enrichment_tier IS NOT NULL — judging without
    a description is pointless. Set require_enriched=False to override.
    """
    clauses = ["judged_at IS NULL"]
    params: list[Any] = []
    if require_enriched:
        clauses.append("enrichment_tier IS NOT NULL")
    if ats:
        clauses.append("ats = ?")
        params.append(ats)

    sql = "SELECT * FROM discoveries WHERE " + " AND ".join(clauses)
    sql += " ORDER BY discovered_at DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_company_judgement_summary(
    ats: str | None = None,
) -> list[dict[str, Any]]:
    """Aggregate judged-discovery stats per company.

    Returns rows with: company, total, ready, rejected, avg_combined,
    avg_ghost, avg_redflag, avg_alignment, avg_resume_match (or None).

    Sorted by ready DESC, then total DESC. Useful for spotting patterns
    like 'every Apollo posting flagged' vs 'one bad Coalfire listing.'
    """
    clauses = ["judged_at IS NOT NULL"]
    params: list[Any] = []
    if ats:
        clauses.append("ats = ?")
        params.append(ats)
    where = " WHERE " + " AND ".join(clauses)

    sql = f"""
        SELECT
          company,
          COUNT(*) AS total,
          SUM(CASE WHEN screened_status = 'ready' THEN 1 ELSE 0 END) AS ready,
          SUM(CASE WHEN screened_status = 'rejected' THEN 1 ELSE 0 END) AS rejected,
          AVG(combined_score) AS avg_combined,
          AVG(ghost_score) AS avg_ghost,
          AVG(redflag_score) AS avg_redflag,
          AVG(alignment_score) AS avg_alignment,
          AVG(resume_match_score) AS avg_resume_match
        FROM discoveries
        {where}
        GROUP BY company
        ORDER BY ready DESC, total DESC, company ASC
    """

    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_judged_counts() -> dict[str, int]:
    """Counts of discoveries by screened_status (after judging)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT screened_status, COUNT(*) AS count FROM discoveries "
            "WHERE judged_at IS NOT NULL GROUP BY screened_status"
        ).fetchall()
        return {row["screened_status"]: row["count"] for row in rows}
    finally:
        conn.close()


def update_discovery_forged(
    discovery_id: int,
    *,
    offerings_path: str,
) -> bool:
    """Mark a discovery as forged and record where its offerings live."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE discoveries SET forged_at = ?, offerings_path = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), offerings_path, discovery_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_ready_discoveries(
    ats: str | None = None,
    unforged_only: bool = False,
    unpetitioned_only: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Discoveries with screened_status='ready'. Optionally filter to those
    not yet forged or petitioned."""
    clauses = ["screened_status = 'ready'", "judged_at IS NOT NULL"]
    params: list[Any] = []
    if unforged_only:
        clauses.append("forged_at IS NULL")
    if unpetitioned_only:
        clauses.append("petition_at IS NULL")
    if ats:
        clauses.append("ats = ?")
        params.append(ats)

    sql = "SELECT * FROM discoveries WHERE " + " AND ".join(clauses)
    sql += " ORDER BY combined_score DESC, discovered_at DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def update_discovery_petitioned(
    discovery_id: int,
    *,
    offerings_path: str | None = None,
) -> bool:
    """Mark a discovery as petitioned. If offerings_path is provided and
    the row doesn't already have one, set it (covers the case of running
    petition before forge)."""
    conn = get_connection()
    try:
        if offerings_path is not None:
            cursor = conn.execute(
                "UPDATE discoveries SET petition_at = ?, "
                "offerings_path = COALESCE(offerings_path, ?) WHERE id = ?",
                (
                    datetime.now(timezone.utc).isoformat(),
                    offerings_path,
                    discovery_id,
                ),
            )
        else:
            cursor = conn.execute(
                "UPDATE discoveries SET petition_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), discovery_id),
            )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_applied_companies() -> set[str]:
    """Return the set of companies (lowercased) currently in the applications table.

    Used by `gather` to skip employers already in the user's pipeline.
    Excludes terminal statuses (rejected, ghosted) so the user can re-discover
    employers after a closed-out application.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT company FROM applications "
            "WHERE status NOT IN ('rejected', 'ghosted')"
        ).fetchall()
        return {row["company"].lower() for row in rows if row["company"]}
    finally:
        conn.close()


# Initialize on import
init_db()
