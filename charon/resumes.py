"""Which résumé a posting is measured against, and which one gets attached.

Charon keeps two curated résumés, an IR / blue-team one and an Audit / GRC
one, and routes each posting to one of them by the judge's closest_target.
Everything that reads a résumé goes through here: the résumé-match analyzer,
forge (attaching the file), and petition (writing the cover letter). Before
this module they read `profile.resume_path` separately, which on the portal
resolved to a résumé from May that had since been replaced by both of these,
so the score, the attachment and the letter could each describe a different
document.

Profile shape:

    resumes:
      ir:  ~/.charon/offerings/Resumes/DeAnnaShanks_Resume_IR_2Page.docx
      grc: ~/.charon/offerings/Resumes/DeAnnaShanks_Resume_AuditGRC_2Page.docx
      grc_targets: [compliance auditor, it auditor, grc analyst, security auditor]

Profiles without a `resumes` block keep working: IR falls back to
forge.default_resume_md, then resume_path; GRC falls back to
forge.grc_resume_md, then to the IR résumé.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from charon.resume_match import ResumeMatchError, load_resume_text


DEFAULT_GRC_TARGETS = [
    "compliance auditor",
    "it auditor",
    "grc analyst",
    "security auditor",
]

KIND_IR = "ir"
KIND_GRC = "grc"


def resume_paths(profile: dict[str, Any] | None) -> dict[str, str]:
    """Configured résumé path per kind ('' when nothing is configured)."""
    prof = profile or {}
    block = prof.get("resumes") or {}
    forge = prof.get("forge") or {}
    if not isinstance(block, dict):
        block = {}
    if not isinstance(forge, dict):
        forge = {}

    ir = (
        str(block.get("ir") or "").strip()
        or str(forge.get("default_resume_md") or "").strip()
        or str(prof.get("resume_path") or "").strip()
    )
    grc = (
        str(block.get("grc") or "").strip()
        or str(forge.get("grc_resume_md") or "").strip()
        or ir
    )
    return {KIND_IR: ir, KIND_GRC: grc}


def grc_targets(profile: dict[str, Any] | None) -> list[str]:
    """Lower-cased closest_target values that route to the GRC résumé."""
    prof = profile or {}
    for source in (prof.get("resumes"), prof.get("forge")):
        if isinstance(source, dict):
            targets = source.get("grc_targets")
            if isinstance(targets, list) and targets:
                return [str(t).strip().lower() for t in targets]
    return list(DEFAULT_GRC_TARGETS)


def closest_target_of(discovery: dict[str, Any]) -> str:
    """The judge's role_alignment.closest_target from stored judgement_detail."""
    detail_raw = discovery.get("judgement_detail")
    if not detail_raw:
        return ""
    try:
        detail = json.loads(detail_raw) if isinstance(detail_raw, str) else detail_raw
    except (ValueError, TypeError):
        return ""
    if not isinstance(detail, dict):
        return ""
    ra = detail.get("role_alignment") or {}
    if not isinstance(ra, dict):
        return ""
    return str(ra.get("closest_target") or "").strip()


def kind_for(closest_target: str, profile: dict[str, Any] | None) -> str:
    """'grc' when closest_target is one of the GRC targets, otherwise 'ir'."""
    ct = (closest_target or "").strip().lower()
    return KIND_GRC if ct and ct in grc_targets(profile) else KIND_IR


def resume_path_for(
    profile: dict[str, Any] | None, closest_target: str = ""
) -> tuple[str, str]:
    """(kind, path) for a posting. path is '' when that kind isn't configured."""
    kind = kind_for(closest_target, profile)
    return kind, resume_paths(profile)[kind]


def load_resume_for(
    profile: dict[str, Any] | None, closest_target: str = ""
) -> tuple[str, str | None]:
    """(kind, text) for a posting; text is None when unset or unreadable."""
    kind, path = resume_path_for(profile, closest_target)
    if not path:
        return kind, None
    try:
        return kind, load_resume_text(path)
    except ResumeMatchError:
        return kind, None


def load_all(profile: dict[str, Any] | None) -> dict[str, str]:
    """Text of every configured résumé, keyed by kind.

    Empty unless a `resumes` block is configured, so callers can tell routed
    judging apart from the legacy single-résumé path. Read once per batch.
    """
    block = (profile or {}).get("resumes")
    if not isinstance(block, dict) or not block:
        return {}
    out: dict[str, str] = {}
    for kind, path in resume_paths(profile).items():
        if not path:
            continue
        try:
            out[kind] = load_resume_text(path)
        except ResumeMatchError:
            continue
    return out


def describe(profile: dict[str, Any] | None) -> dict[str, str]:
    """Resolved filename per kind, for audit trails and CLI output."""
    return {
        kind: (Path(path).expanduser().name if path else "")
        for kind, path in resume_paths(profile).items()
    }


__all__ = [
    "DEFAULT_GRC_TARGETS",
    "KIND_GRC",
    "KIND_IR",
    "closest_target_of",
    "describe",
    "grc_targets",
    "kind_for",
    "load_all",
    "load_resume_for",
    "resume_path_for",
    "resume_paths",
]
