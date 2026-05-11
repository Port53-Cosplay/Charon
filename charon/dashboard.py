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
MANIFEST_TEMPLATE = "manifest.html"
DEFAULT_PORT = 7777
LOOPBACK = "127.0.0.1"


class DashboardError(Exception):
    pass


# ── data layer ──────────────────────────────────────────────────────


def _ready_discoveries() -> list[dict[str, Any]]:
    from charon.db import get_discoveries

    rows = get_discoveries(status="ready", order_by="combined_score")
    rows = [r for r in rows if r.get("judged_at")]
    return [_summarize_discovery(r) for r in rows]


def _summarize_discovery(r: dict[str, Any]) -> dict[str, Any]:
    """Cherry-pick fields the dashboard cares about — keeps the JSON tight."""
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
        "offerings_path": r.get("offerings_path"),
        "forged_at": r.get("forged_at"),
        "petition_at": r.get("petition_at"),
    }


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
        if path == "/api/ready":
            self._serve_json({"ready": _ready_discoveries()})
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
