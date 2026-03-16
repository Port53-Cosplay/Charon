"""Application tracking and ghost detection."""

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from charon.db import (
    add_application,
    get_application,
    get_application_stats,
    get_applications,
    get_stale_applications,
    mark_ghosted,
    update_application_status,
    VALID_STATUSES,
    queue_digest,
)


class ApplyError(Exception):
    """Raised when application tracking fails."""


def extract_email_domain(url: str | None) -> str | None:
    """Extract the domain from a job posting URL for email matching."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        # Strip common subdomains
        parts = host.lower().split(".")
        # Handle job board URLs — these are not the company domain
        # Check the registrable domain (last two parts) against known boards
        job_board_domains = {
            "linkedin.com", "indeed.com", "glassdoor.com", "ziprecruiter.com",
            "monster.com", "dice.com", "lever.co", "greenhouse.io",
            "smartrecruiters.com", "jobvite.com", "icims.com", "ultipro.com",
            "myworkdayjobs.com", "applytojob.com", "workday.com",
            "builtin.com", "simplyhired.com", "careerbuilder.com",
            "wellfound.com", "angel.co", "hired.com",
        }
        registrable = ".".join(parts[-2:]) if len(parts) >= 2 else host
        if registrable in job_board_domains:
            return None
        # Return the registrable domain (last 2 parts, or 3 for co.uk etc)
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return host if host else None
    except Exception:
        return None


def track_application(
    company: str,
    role: str,
    url: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Track a new job application. Returns the application record."""
    if not company or not company.strip():
        raise ApplyError("Company name is required.")
    if not role or not role.strip():
        raise ApplyError("Role/position is required.")

    company = company.strip()
    role = role.strip()
    email_domain = extract_email_domain(url)

    app_id = add_application(
        company=company,
        role=role,
        url=url,
        email_domain=email_domain,
        notes=notes,
    )

    # Queue digest entry
    queue_digest(
        "application",
        f"Applied: {company} - {role}",
        {"app_id": app_id, "company": company, "role": role, "url": url},
    )

    return get_application(app_id)


def update_status(app_id: int, status: str) -> dict[str, Any] | None:
    """Update an application's status."""
    status = status.lower().strip()
    if status not in VALID_STATUSES:
        raise ApplyError(
            f"Invalid status '{status}'. "
            f"Valid: {', '.join(sorted(VALID_STATUSES))}"
        )

    if not update_application_status(app_id, status):
        return None

    app = get_application(app_id)
    if app:
        queue_digest(
            "application",
            f"Status update: {app['company']} - {app['role']} -> {status}",
            {"app_id": app_id, "status": status},
        )
    return app


def check_ghosted(days: int = 21) -> list[dict[str, Any]]:
    """Find and mark applications as ghosted after N days with no response."""
    if days < 1:
        raise ApplyError("Ghost detection threshold must be at least 1 day.")

    stale = get_stale_applications(days)
    if not stale:
        return []

    app_ids = [app["id"] for app in stale]
    mark_ghosted(app_ids)

    # Queue digest entries for each ghosted application
    for app in stale:
        queue_digest(
            "ghosted",
            f"Ghosted: {app['company']} - {app['role']} (no response in {days}+ days)",
            {"app_id": app["id"], "company": app["company"], "role": app["role"]},
        )

    return stale


def get_stats() -> dict[str, int]:
    """Get application statistics by status."""
    return get_application_stats()


def list_applications(status: str | None = None) -> list[dict[str, Any]]:
    """List applications, optionally filtered by status."""
    if status:
        status = status.lower().strip()
        if status not in VALID_STATUSES:
            raise ApplyError(
                f"Invalid status filter '{status}'. "
                f"Valid: {', '.join(sorted(VALID_STATUSES))}"
            )
    return get_applications(status)
