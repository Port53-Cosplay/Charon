"""Local HTTP dashboard for browsing the funnel.

`charon manifest` starts a small server on localhost and opens the
dashboard in your default browser. First cut: a single "Ready" tab —
score-sorted, score-badged, with "Mark Applied" buttons that bridge
straight into the applications table and flip the discovery's status
to 'applied' atomically.

Built on Python's stdlib http.server — no new dependencies. The
server is read-only for funnel state (discoveries/judgements) except
for the one allowed write: marking a ready discovery as applied,
which is the killer ergonomic win.

Future tabs (Gathered, Judged, Provisioned, Crossed, Sirens) plug
into the same dispatch table. See ROADMAP §10.
"""

from __future__ import annotations

import json
import socket
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


TEMPLATES_DIR = Path(__file__).parent / "templates"
ASSETS_DIR = TEMPLATES_DIR / "assets"
MANIFEST_TEMPLATE = "manifest.html"
DEFAULT_PORT = 7777
LOOPBACK = "127.0.0.1"

# Image / static asset MIME map. Kept tight — we don't want surprise types.
_STATIC_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class DashboardError(Exception):
    pass


# ── data layer ──────────────────────────────────────────────────────


def _ready_discoveries() -> list[dict[str, Any]]:
    from charon.db import get_discoveries

    rows = get_discoveries(status="ready", order_by="combined_score")
    rows = [r for r in rows if r.get("judged_at")]
    return [_summarize_discovery(r) for r in rows]


ARCHIVE_DAYS = 45
TERMINAL_STATUSES_FOR_ARCHIVE = ("ghosted", "rejected", "offered")


def _applications(include_archived: bool = False) -> tuple[list[dict[str, Any]], int]:
    """Fetch tracked applications, with best-effort back-link to the
    discovery row so the dashboard can offer "Open folder" /
    "Find contacts" buttons on applications that came from the funnel.

    The link is by exact (company, role) match — applications don't carry
    a discovery_id today. Manually-typed `apply --add` rows that don't
    match a discovery just won't get the offering-side actions.
    Logged as a §11.5 candidate for a real FK later.

    By default, applications that have been in a terminal status
    (stranded / rejected / offered) for ``ARCHIVE_DAYS`` or more days
    are filtered out — they're not deleted, just hidden so the active
    view stays focused. Pass include_archived=True to see everything.
    """
    from datetime import datetime, timezone
    from charon.contacts import CONTACTS_FILENAME
    from charon.db import get_applications, get_connection

    apps = get_applications()
    if not apps:
        return [], 0

    # One-shot lookup: company+role -> (discovery_id, offerings_path)
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, company, role, offerings_path FROM discoveries "
            "WHERE offerings_path IS NOT NULL OR screened_status = 'applied'"
        ).fetchall()
    finally:
        conn.close()
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        key = ((r["company"] or "").strip().lower(), (r["role"] or "").strip().lower())
        by_key[key] = {
            "discovery_id": r["id"],
            "offerings_path": r["offerings_path"],
        }

    now = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    archived_count = 0
    for app in apps:
        key = ((app.get("company") or "").strip().lower(),
               (app.get("role") or "").strip().lower())
        link = by_key.get(key) or {}
        offerings_path = link.get("offerings_path")

        has_contacts = False
        if offerings_path:
            try:
                has_contacts = (Path(offerings_path) / CONTACTS_FILENAME).exists()
            except OSError:
                has_contacts = False

        days_since = None
        applied_at = app.get("applied_at")
        if applied_at:
            try:
                applied_dt = datetime.fromisoformat(applied_at.replace("Z", "+00:00"))
                if applied_dt.tzinfo is None:
                    applied_dt = applied_dt.replace(tzinfo=timezone.utc)
                days_since = (now - applied_dt).days
            except (ValueError, AttributeError):
                pass

        # Archive filter: hide terminal-status applications whose updated_at
        # is older than ARCHIVE_DAYS. Stays in the DB; just falls out of
        # the dashboard's default view.
        status = app.get("status")
        is_archived = False
        if status in TERMINAL_STATUSES_FOR_ARCHIVE:
            updated_at = app.get("updated_at")
            if updated_at:
                try:
                    updated_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                    if updated_dt.tzinfo is None:
                        updated_dt = updated_dt.replace(tzinfo=timezone.utc)
                    if (now - updated_dt).days >= ARCHIVE_DAYS:
                        is_archived = True
                except (ValueError, AttributeError):
                    pass
        if is_archived and not include_archived:
            archived_count += 1
            continue

        out.append({
            "id": app["id"],
            "company": app["company"],
            "role": app["role"],
            "url": app.get("url"),
            "status": status,
            "applied_at": applied_at,
            "updated_at": app.get("updated_at"),
            "notes": app.get("notes"),
            "days_since": days_since,
            "discovery_id": link.get("discovery_id"),
            "offerings_path": offerings_path,
            "has_offerings": bool(offerings_path),
            "has_contacts": has_contacts,
            "is_archived": is_archived,
        })
    return out, archived_count


def _ghost_check() -> dict[str, Any]:
    """Run the stale-applications sweep from the dashboard.

    Reads `applications.ghosted_after_days` from the profile (default 21),
    flips qualifying rows to 'ghosted', and returns a summary of what was
    touched alongside the refreshed applications list.
    """
    from charon.apply import ApplyError, check_ghosted
    from charon.profile import load_profile

    try:
        prof = load_profile()
    except Exception as e:  # noqa: BLE001
        raise DashboardError(f"Profile error: {e}") from e

    days = int((prof.get("applications") or {}).get("ghosted_after_days", 21))
    try:
        ghosted = check_ghosted(days)
    except ApplyError as e:
        raise DashboardError(str(e)) from e

    return {
        "days": days,
        "ghosted": [
            {"id": app["id"], "company": app["company"], "role": app["role"]}
            for app in ghosted
        ],
        "count": len(ghosted),
    }


def _update_status(app_id: int, status: str) -> dict[str, Any]:
    """Bridge for updating an application's status from the dashboard."""
    from charon.db import VALID_STATUSES, get_application, update_application_status

    if status not in VALID_STATUSES:
        raise DashboardError(
            f"Invalid status '{status}'. "
            f"Valid: {', '.join(sorted(VALID_STATUSES))}"
        )
    ok = update_application_status(app_id, status)
    if not ok:
        raise DashboardError(f"No application with id {app_id}.")
    app = get_application(app_id) or {}
    return {"id": app_id, "status": app.get("status")}


def _summarize_discovery(r: dict[str, Any]) -> dict[str, Any]:
    """Cherry-pick fields the dashboard cares about — keeps the JSON tight."""
    from charon.contacts import CONTACTS_FILENAME

    offerings_path = r.get("offerings_path")
    has_contacts = False
    if offerings_path:
        try:
            has_contacts = (Path(offerings_path) / CONTACTS_FILENAME).exists()
        except OSError:
            has_contacts = False

    # Parse judgement_detail if it's structured JSON; surface a digest the UI
    # can render without re-parsing the whole blob.
    judgement_digest = None
    detail_raw = r.get("judgement_detail")
    if detail_raw:
        try:
            parsed = json.loads(detail_raw)
            judgement_digest = _digest_judgement(parsed)
        except (TypeError, ValueError, json.JSONDecodeError):
            judgement_digest = None

    return {
        "id": r["id"],
        "company": r["company"],
        "role": r["role"],
        "url": r["url"],
        "location": r.get("location"),
        "combined_score": _round1(r.get("combined_score")),
        "alignment_score": _round1(r.get("alignment_score")),
        "ghost_score": _round1(r.get("ghost_score")),
        "redflag_score": _round1(r.get("redflag_score")),
        "resume_match_score": _round1(r.get("resume_match_score")),
        "tier": r.get("tier"),
        "ats": r.get("ats"),
        "offerings_path": offerings_path,
        "forged_at": r.get("forged_at"),
        "petition_at": r.get("petition_at"),
        "has_contacts": has_contacts,
        # Detail-view fields (loaded eagerly so click-to-expand is instant)
        "full_description": r.get("full_description"),
        "judgement_reason": r.get("judgement_reason"),
        "judgement_digest": judgement_digest,
    }


def _digest_judgement(parsed: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the human-useful bits from judgement_detail's JSON.

    Top-level analyzer keys per screen.py: 'ghostbust', 'redflags',
    'role_alignment', 'resume_match' (note plurals + 'role_alignment',
    not 'redflag' / 'alignment').
    """
    out: dict[str, Any] = {}

    ghost = parsed.get("ghostbust")
    if isinstance(ghost, dict):
        signals: list[dict[str, Any]] = []
        for s in ghost.get("signals") or []:
            if isinstance(s, dict):
                signals.append({
                    "severity": s.get("severity") or "info",
                    "category": s.get("category"),
                    "finding":  s.get("finding") or "",
                })
        if signals or ghost.get("summary"):
            out["ghost"] = {"summary": ghost.get("summary"), "signals": signals}

    def _flatten_flags(raw_list: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in (raw_list or []):
            if isinstance(item, dict):
                items.append({
                    "flag":           item.get("flag") or "",
                    "evidence":       item.get("evidence") or "",
                    "interpretation": item.get("interpretation") or "",
                })
            elif isinstance(item, str):
                items.append({"flag": item, "evidence": "", "interpretation": ""})
        return items

    red = parsed.get("redflags")
    if isinstance(red, dict):
        red_block = {
            "summary":      red.get("summary"),
            "dealbreakers": _flatten_flags(red.get("dealbreakers_found")),
            "yellow":       _flatten_flags(red.get("yellow_flags_found")),
            "green":        _flatten_flags(red.get("green_flags_found")),
        }
        if any(red_block[k] for k in ("dealbreakers", "yellow", "green")) or red_block["summary"]:
            out["redflags"] = red_block

    align = parsed.get("role_alignment")
    if isinstance(align, dict):
        align_block = {
            "closest_target": align.get("closest_target"),
            "overlap":        [str(d) for d in (align.get("overlap") or [])],
            "gaps":           [str(d) for d in (align.get("gaps") or [])],
            "stepping_stone": align.get("stepping_stone"),
            "assessment":     align.get("assessment"),
        }
        if any(align_block.values()):
            out["alignment"] = align_block

    rm = parsed.get("resume_match")
    if isinstance(rm, dict):
        rm_block = {
            "match_type":   rm.get("match_type"),
            "summary":      rm.get("summary"),
            "overlap":      [str(d) for d in (rm.get("overlap") or [])],
            "gaps":         [str(d) for d in (rm.get("gaps") or [])],
            "transferable": [str(d) for d in (rm.get("transferable") or [])],
        }
        if any(rm_block.values()):
            out["resume_match"] = rm_block

    return out or None


def _round1(v: float | None) -> float | None:
    if v is None:
        return None
    return round(float(v), 1)


def _apply_to_discovery(discovery_id: int, notes: str | None) -> dict[str, Any]:
    """Bridge: record an application + flip the discovery's status.

    Pulls company/role/url from the discovery row so the caller doesn't
    have to retype them. Returns the new application record.
    """
    from charon.apply import ApplyError, track_application
    from charon.db import get_discovery, mark_discovery_applied

    discovery = get_discovery(discovery_id)
    if discovery is None:
        raise DashboardError(f"No discovery with id {discovery_id}.")
    if discovery.get("screened_status") == "applied":
        raise DashboardError(f"Discovery #{discovery_id} is already marked applied.")

    try:
        app = track_application(
            company=discovery["company"],
            role=discovery["role"],
            url=discovery.get("url"),
            notes=notes,
        )
    except ApplyError as e:
        raise DashboardError(str(e)) from e

    mark_discovery_applied(discovery_id)
    return app


def _reject_discovery(discovery_id: int, reason: str | None) -> dict[str, Any]:
    """User-driven rejection ("Not for me"). Flips the discovery's status to
    'rejected' and stores the optional reason in judgement_reason.

    The reason is captured so future rejections can be pattern-matched
    (e.g. "no federal-adjacent roles") and filtered upstream — but that
    filter doesn't exist yet. For now we just persist what the user said.
    """
    from charon.db import get_discovery, mark_discovery_rejected

    discovery = get_discovery(discovery_id)
    if discovery is None:
        raise DashboardError(f"No discovery with id {discovery_id}.")
    if discovery.get("screened_status") == "applied":
        raise DashboardError(
            f"Discovery #{discovery_id} was already applied to; can't reject it."
        )

    cleaned = (reason or "").strip() or None
    mark_discovery_rejected(discovery_id, cleaned)
    return {"id": discovery_id, "reason": cleaned}


def _provision_discovery(discovery_id: int) -> dict[str, Any]:
    """Bridge: forge + petition + render for a discovery. Blocks ~30s.

    Mirrors `charon provision --id N` step-for-step (without the click
    layer). Returns a summary dict including any error and the rendered
    artifact paths.
    """
    from charon.db import (
        get_discovery,
        update_discovery_forged,
        update_discovery_petitioned,
    )
    from charon.letter import petition_discovery
    from charon.profile import load_profile
    from charon.tailor import forge_discovery

    discovery = get_discovery(discovery_id)
    if discovery is None:
        raise DashboardError(f"No discovery with id {discovery_id}.")

    try:
        profile = load_profile()
    except Exception as e:  # noqa: BLE001
        raise DashboardError(f"Profile error: {e}") from e

    summary: dict[str, Any] = {"id": discovery_id, "errors": []}

    # Forge resume
    try:
        forge_result = forge_discovery(discovery, profile=profile)
    except Exception as e:  # noqa: BLE001
        forge_result = {"error": f"{type(e).__name__}: {e}"}
    if forge_result.get("offerings_path") and not forge_result.get("error"):
        update_discovery_forged(
            discovery_id, offerings_path=forge_result["offerings_path"]
        )
    elif forge_result.get("error"):
        summary["errors"].append(f"forge: {forge_result['error']}")

    # Petition cover letter (independent of forge)
    try:
        petition_result = petition_discovery(discovery, profile=profile)
    except Exception as e:  # noqa: BLE001
        petition_result = {"error": f"{type(e).__name__}: {e}"}
    if petition_result.get("letter_path") and not petition_result.get("error"):
        update_discovery_petitioned(
            discovery_id, offerings_path=petition_result.get("offerings_path")
        )
    elif petition_result.get("error"):
        summary["errors"].append(f"petition: {petition_result['error']}")

    # Auto-render .html alongside .md (mirrors provision_cmd's tail)
    if (
        (forge_result.get("offerings_path") and not forge_result.get("error"))
        or (petition_result.get("letter_path") and not petition_result.get("error"))
    ):
        from charon.render import RenderError, render_offering
        try:
            r = render_offering(discovery_id)
            summary["resume_path"] = r.get("resume_path")
            summary["cover_letter_path"] = r.get("cover_letter_path")
            summary["errors"].extend(r.get("errors") or [])
        except RenderError as e:
            summary["errors"].append(f"render: {e}")
        except Exception as e:  # noqa: BLE001
            summary["errors"].append(f"render: {type(e).__name__}: {e}")

    summary["offerings_path"] = (
        forge_result.get("offerings_path") or petition_result.get("offerings_path")
    )
    summary["ok"] = bool(summary["offerings_path"]) and not (
        forge_result.get("error") and petition_result.get("error")
    )
    return summary


def _find_contacts(discovery_id: int) -> dict[str, Any]:
    """Bridge: surface LinkedIn contacts for a discovery and persist the list
    to its offerings folder. Synchronous web-search call — typically ~10–20s.
    """
    from charon.contacts import ContactsError, find_contacts_for_discovery

    try:
        return find_contacts_for_discovery(discovery_id)
    except ContactsError as e:
        raise DashboardError(str(e)) from e


def _open_offerings_folder(discovery_id: int) -> dict[str, Any]:
    """Open the offering's folder in the user's file manager.

    Uses subprocess.Popen with the platform-native opener instead of
    click.launch / os.startfile. The HTTP server runs handlers in
    worker threads (ThreadingHTTPServer), and os.startfile relies on
    ShellExecuteEx which expects a single-threaded COM apartment —
    when called from a non-STA thread it can fail silently
    (returns success, no window appears). subprocess.Popen bypasses
    COM entirely by spawning the file manager as a child process,
    which inherits the user's interactive session correctly.
    """
    import subprocess
    import sys
    from charon.db import get_discovery

    discovery = get_discovery(discovery_id)
    if discovery is None:
        raise DashboardError(f"No discovery with id {discovery_id}.")
    folder = discovery.get("offerings_path")
    if not folder:
        raise DashboardError(f"No offerings folder for #{discovery_id}.")
    p = Path(folder)
    if not p.exists():
        raise DashboardError(f"Offerings folder missing on disk: {folder}")

    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer.exe", str(p)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except OSError as e:
        raise DashboardError(f"Couldn't launch file manager: {e}") from e

    return {"id": discovery_id, "folder": str(p)}


# ── HTTP request handler ────────────────────────────────────────────


class _Handler(BaseHTTPRequestHandler):
    server_version = "CharonManifest/0.10"

    # Silence default request logging — drowns the CLI.
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            self._serve_html()
            return
        if path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
            return
        if path == "/api/ready":
            self._serve_json({"ready": _ready_discoveries()})
            return
        if path == "/api/applications":
            qs = urllib.parse.parse_qs(parsed.query or "")
            include_archived = qs.get("archived", ["0"])[0] in {"1", "true", "yes"}
            apps, archived_hidden = _applications(include_archived=include_archived)
            self._serve_json({"applications": apps, "archived_hidden": archived_hidden})
            return
        self._serve_status(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/apply/"):
            try:
                discovery_id = int(path.rsplit("/", 1)[-1])
            except ValueError:
                self._serve_status(HTTPStatus.BAD_REQUEST, "discovery id must be an integer")
                return
            body = self._read_json_body() or {}
            notes = body.get("notes") if isinstance(body, dict) else None
            try:
                app = _apply_to_discovery(discovery_id, notes)
            except DashboardError as e:
                self._serve_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._serve_json({"ok": True, "application": app, "ready": _ready_discoveries()})
            return
        if path.startswith("/api/reject/"):
            try:
                discovery_id = int(path.rsplit("/", 1)[-1])
            except ValueError:
                self._serve_status(HTTPStatus.BAD_REQUEST, "discovery id must be an integer")
                return
            body = self._read_json_body() or {}
            reason = body.get("reason") if isinstance(body, dict) else None
            try:
                rec = _reject_discovery(discovery_id, reason)
            except DashboardError as e:
                self._serve_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._serve_json({"ok": True, "rejection": rec, "ready": _ready_discoveries()})
            return
        if path.startswith("/api/provision/"):
            try:
                discovery_id = int(path.rsplit("/", 1)[-1])
            except ValueError:
                self._serve_status(HTTPStatus.BAD_REQUEST, "discovery id must be an integer")
                return
            try:
                summary = _provision_discovery(discovery_id)
            except DashboardError as e:
                self._serve_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._serve_json(
                {"ok": summary.get("ok", False), "summary": summary, "ready": _ready_discoveries()}
            )
            return
        if path.startswith("/api/contacts/"):
            try:
                discovery_id = int(path.rsplit("/", 1)[-1])
            except ValueError:
                self._serve_status(HTTPStatus.BAD_REQUEST, "discovery id must be an integer")
                return
            try:
                summary = _find_contacts(discovery_id)
            except DashboardError as e:
                self._serve_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._serve_json(
                {"ok": True, "contacts": summary, "ready": _ready_discoveries()}
            )
            return
        if path == "/api/ghost-check":
            try:
                summary = _ghost_check()
            except DashboardError as e:
                self._serve_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._serve_json(
                {"ok": True, "summary": summary, "applications": _applications()[0]}
            )
            return
        if path.startswith("/api/applications/") and path.endswith("/status"):
            try:
                app_id = int(path.split("/")[-2])
            except (ValueError, IndexError):
                self._serve_status(HTTPStatus.BAD_REQUEST, "application id must be an integer")
                return
            body = self._read_json_body() or {}
            new_status = body.get("status") if isinstance(body, dict) else None
            if not new_status or not isinstance(new_status, str):
                self._serve_status(HTTPStatus.BAD_REQUEST, "status (string) is required")
                return
            try:
                rec = _update_status(app_id, new_status)
            except DashboardError as e:
                self._serve_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._serve_json({"ok": True, "updated": rec, "applications": _applications()[0]})
            return
        if path.startswith("/api/open-offerings/"):
            try:
                discovery_id = int(path.rsplit("/", 1)[-1])
            except ValueError:
                self._serve_status(HTTPStatus.BAD_REQUEST, "discovery id must be an integer")
                return
            try:
                rec = _open_offerings_folder(discovery_id)
            except DashboardError as e:
                self._serve_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._serve_json({"ok": True, "opened": rec})
            return
        self._serve_status(HTTPStatus.NOT_FOUND, "not found")

    # ── helpers ─────────────────────────────────────────────────

    def _read_json_body(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def _serve_html(self) -> None:
        path = TEMPLATES_DIR / MANIFEST_TEMPLATE
        try:
            body = path.read_bytes()
        except OSError:
            self._serve_status(HTTPStatus.INTERNAL_SERVER_ERROR, "template missing")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Local-only — no caching needed and reload should pick up template edits
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, rel_path: str) -> None:
        """Serve a file from charon/templates/assets/.

        Path-traversal guarded: reject anything with '..' or absolute
        paths, and verify the resolved file is actually inside ASSETS_DIR.
        Only known image MIME types are served.
        """
        if not rel_path or ".." in rel_path or rel_path.startswith("/") or "\\" in rel_path:
            self._serve_status(HTTPStatus.BAD_REQUEST, "invalid asset path")
            return
        target = (ASSETS_DIR / rel_path).resolve()
        try:
            target.relative_to(ASSETS_DIR.resolve())
        except ValueError:
            self._serve_status(HTTPStatus.BAD_REQUEST, "asset path escapes /static")
            return
        if not target.is_file():
            self._serve_status(HTTPStatus.NOT_FOUND, "asset not found")
            return
        mime = _STATIC_MIME.get(target.suffix.lower())
        if mime is None:
            self._serve_status(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "unsupported asset type")
            return
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def _serve_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_status(self, status: HTTPStatus, message: str) -> None:
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ── server lifecycle ────────────────────────────────────────────────


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((LOOPBACK, port))
            return True
        except OSError:
            return False


def start_server(
    port: int = DEFAULT_PORT,
    *,
    open_browser: bool = True,
    block: bool = True,
) -> ThreadingHTTPServer:
    """Start the dashboard. Blocks on serve_forever() by default."""
    if not _port_is_free(port):
        raise DashboardError(
            f"Port {port} is already in use. "
            f"Use 'charon manifest --port <other>' to pick a different port."
        )

    httpd = ThreadingHTTPServer((LOOPBACK, port), _Handler)
    url = f"http://{LOOPBACK}:{port}/"

    if open_browser:
        # Give the server a moment to come up before launching the browser
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()

    if block:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()
    return httpd


__all__ = ["DashboardError", "start_server", "DEFAULT_PORT"]
