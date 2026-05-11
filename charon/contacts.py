"""Find LinkedIn contacts for an offering and save the list to its folder.

Wraps the existing ``charon.dossier.find_contacts`` web-search helper
with two additions:

1. Discovery-keyed entry point: pass an ID, get contacts for that
   discovery's company (role and target roles auto-filled from the
   row + profile).
2. Markdown persistence: writes ``linkedin_contacts.md`` to the
   offering's folder so the contact list lives next to resume.md /
   cover_letter.md and travels with the rest of the application
   materials.

This is the read-only outreach foundation. The outreach-flavored
Sirens feature (tracking who you messaged, drafting outreach in
your voice, marking replies) sits on top of the data shape this
file produces.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


CONTACTS_FILENAME = "linkedin_contacts.md"


class ContactsError(Exception):
    pass


CATEGORY_HEADINGS = {
    "recruiter": "Recruiters",
    "hiring_manager": "Hiring Managers",
    "team_member": "Team Members",
}
CATEGORY_ORDER = ["recruiter", "hiring_manager", "team_member"]


def _format_markdown(
    company: str,
    role: str,
    discovery_id: int,
    result: dict[str, Any],
) -> str:
    """Group contacts by category and render to a clean markdown file."""
    contacts = result.get("contacts") or []
    search_notes = (result.get("search_notes") or "").strip()

    today = datetime.now().strftime("%Y-%m-%d")
    lines: list[str] = [
        f"# LinkedIn Contacts: {company}",
        "",
        f"For role: {role}",
        f"Discovery #{discovery_id} · Generated {today}",
    ]

    if not contacts:
        lines.extend(["", "_No contacts surfaced by the search._"])
        if search_notes:
            lines.extend(["", "---", "", f"Search notes: {search_notes}"])
        return "\n".join(lines) + "\n"

    # Bucket by category
    buckets: dict[str, list[dict[str, Any]]] = {}
    for c in contacts:
        cat = c.get("category") or "team_member"
        if cat not in CATEGORY_HEADINGS:
            cat = "team_member"
        buckets.setdefault(cat, []).append(c)

    for cat in CATEGORY_ORDER:
        rows = buckets.get(cat) or []
        if not rows:
            continue
        lines.extend(["", f"## {CATEGORY_HEADINGS[cat]}", ""])
        for c in rows:
            name = (c.get("name") or "Unknown").strip()
            title = (c.get("title") or "").strip()
            url = (c.get("linkedin_url") or "").strip()
            relevance = (c.get("relevance") or "").strip()

            header = f"- **{name}**"
            if title:
                header += f" — {title}"
            lines.append(header)
            if url:
                lines.append(f"  {url}")
            if relevance:
                lines.append(f"  > {relevance}")
            lines.append("")

    if search_notes:
        lines.extend(["---", "", f"Search notes: {search_notes}"])

    return "\n".join(lines).rstrip() + "\n"


def find_contacts_for_discovery(discovery_id: int) -> dict[str, Any]:
    """Find LinkedIn contacts for a discovery's company and persist to the
    offerings folder as `linkedin_contacts.md`.

    Returns a summary dict with the file path, contact count, and any
    error. Raises ContactsError on prerequisite failures (missing
    discovery, missing offerings folder).
    """
    from charon.db import get_discovery
    from charon.dossier import find_contacts
    from charon.profile import load_profile

    discovery = get_discovery(discovery_id)
    if discovery is None:
        raise ContactsError(f"No discovery with id {discovery_id}.")

    folder_str = discovery.get("offerings_path")
    if not folder_str:
        raise ContactsError(
            f"No offerings folder for #{discovery_id}. "
            f"Run `charon provision --id {discovery_id}` first."
        )
    folder = Path(folder_str)
    if not folder.exists():
        raise ContactsError(f"Offerings folder missing on disk: {folder}")

    # Pull target_roles from profile so the search can prioritize relevant titles
    try:
        profile = load_profile()
    except Exception:  # noqa: BLE001 — proceed without if profile is broken
        profile = {}
    target_roles = profile.get("target_roles") if isinstance(profile, dict) else None
    if not isinstance(target_roles, list):
        target_roles = None

    company = discovery.get("company") or ""
    role = discovery.get("role") or ""

    result = find_contacts(
        company=company,
        role_title=role or None,
        target_roles=target_roles,
    )

    md_text = _format_markdown(company, role, discovery_id, result)
    out_path = folder / CONTACTS_FILENAME
    out_path.write_text(md_text, encoding="utf-8")

    return {
        "id": discovery_id,
        "company": company,
        "role": role,
        "path": str(out_path),
        "count": len(result.get("contacts") or []),
        "by_category": {
            cat: sum(1 for c in (result.get("contacts") or [])
                     if (c.get("category") or "team_member") == cat)
            for cat in CATEGORY_ORDER
        },
    }


__all__ = ["ContactsError", "CONTACTS_FILENAME", "find_contacts_for_discovery"]
