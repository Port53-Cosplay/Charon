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
"""


MIGRATIONS = [
    "ALTER TABLE applications ADD COLUMN dossier_at TEXT",
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


def get_stale_applications(days: int) -> list[dict[str, Any]]:
    """Get applications in 'applied' status older than N days without ghosted notification."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM applications "
            "WHERE status = 'applied' AND ghosted_notified = 0 "
            "AND julianday('now') - julianday(applied_at) >= ? "
            "ORDER BY applied_at",
            (days,),
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


# Initialize on import
init_db()
