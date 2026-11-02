"""Prep — the blank cover letter for a ready discovery, shared by CLI and web.

`charon provision` and the Ready card's Prep button both land here, so they
can't drift. Prep writes cover_letter.docx (see letter_template.py) into the
discovery's offerings folder and nothing else: no résumé copy, no LLM. The
letter is addressed from the newest company contacts search; searching is a
separate, paid step each caller asks about before running.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from charon.letter_template import (
    LETTER_FILENAME,
    build_letter_template,
    pick_addressee,
)
from charon.resumes import closest_target_of, resume_path_for
from charon.tailor import DEFAULT_OFFERINGS_DIR, offerings_folder


def company_key(name: str | None) -> str:
    return " ".join((name or "").split()).casefold()


def latest_contacts(company: str | None) -> dict[str, Any] | None:
    """The newest company-contacts search for a company, or None if never searched."""
    import json

    from charon.db import get_connection

    key = company_key(company)
    if not key:
        return None
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT company, input_value, result_json FROM history "
            "WHERE command = 'contacts' ORDER BY timestamp DESC",
        ).fetchall()
    finally:
        conn.close()
    for row_company, input_value, raw in rows:
        if company_key(row_company or input_value) != key:
            continue
        try:
            result = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            result = {}
        return result if isinstance(result, dict) else {}
    return None


def has_contacts(company: str | None) -> bool:
    return latest_contacts(company) is not None


def search_contacts(company: str, profile: dict[str, Any] | None) -> int:
    """Run the (paid) contacts search and store it. Returns the history id."""
    from charon.contacts import find_company_contacts
    from charon.db import save_history

    result = find_company_contacts(company, profile)
    return save_history(
        "contacts", "company", company, float(len(result.get("contacts") or [])),
        result, company=company,
    )


def prep_discovery(
    discovery: dict[str, Any],
    profile: dict[str, Any] | None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Write the letter template for one discovery.

    Never overwrites a letter silently: an existing one is skipped, or with
    force set aside as cover_letter.previous-<stamp>.docx first.
    """
    from charon.db import update_discovery_petitioned

    discovery_id = discovery.get("id")
    result: dict[str, Any] = {"id": discovery_id, "errors": []}

    _, source = resume_path_for(profile, closest_target_of(discovery))
    source_path = Path(os.path.expanduser(source)) if source else None
    if source_path is None or source_path.suffix.lower() != ".docx" or not source_path.is_file():
        result["errors"].append(
            "letter: the letterhead comes from your .docx resume, and none is configured for this posting"
        )
        return result

    base = ((profile or {}).get("forge") or {}).get("offerings_dir", DEFAULT_OFFERINGS_DIR)
    folder = offerings_folder(discovery, base_dir=base)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / LETTER_FILENAME
    result["offerings_path"] = str(folder)

    if out.exists():
        if not force:
            result["letter_path"] = str(out)
            result["skipped_reason"] = "letter template already exists"
            return result
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out.rename(folder / f"cover_letter.previous-{stamp}.docx")

    addressee = pick_addressee(latest_contacts(discovery.get("company")))
    try:
        built = build_letter_template(discovery, source_path, out, addressee=addressee)
    except (OSError, ValueError) as e:
        result["errors"].append(f"letter: {e}")
        return result

    update_discovery_petitioned(discovery_id, offerings_path=str(folder))
    result.update(letter_path=built["letter_path"], greeting=built["greeting"])
    return result


__all__ = [
    "company_key",
    "has_contacts",
    "latest_contacts",
    "prep_discovery",
    "search_contacts",
]
