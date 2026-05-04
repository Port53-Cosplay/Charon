"""The Three Judges of the Underworld.

`charon judge` runs the existing v1 analyzers (ghostbust, redflags,
role_alignment) against enriched discoveries in batch mode. Each
discovery gets three scores and a combined score. Above the threshold:
`screened_status='ready'`. Below: `'rejected'` with a reason.

Token cost reality: roughly $0.02-0.05 per discovery on Sonnet-4 at
typical description lengths. Batch sizes above DEFAULT_BULK_WARN_AT
trigger a confirmation prompt in the CLI layer.
"""

from __future__ import annotations

from typing import Any, Callable

from charon.ai import AIError
from charon.db import (
    get_discoveries,
    get_discovery,
    get_judged_counts,
    get_unjudged_discoveries,
    update_discovery_judgement,
)
from charon.ghostbust import analyze_ghostbust
from charon.hunt import analyze_role_alignment
from charon.redflags import analyze_redflags


DEFAULT_READY_THRESHOLD = 60
DEFAULT_BULK_WARN_AT = 50  # warn before judging more than this many at once


class JudgeError(Exception):
    """Raised when judging fails for reasons the user should see."""


def _judge_config(profile: dict[str, Any] | None) -> dict[str, Any]:
    cfg = (profile or {}).get("judge") or {}
    return {
        "ready_threshold": float(cfg.get("ready_threshold", DEFAULT_READY_THRESHOLD)),
        "bulk_warn_at": int(cfg.get("bulk_warn_at", DEFAULT_BULK_WARN_AT)),
    }


def compute_combined(ghost: float, redflag: float, alignment: float) -> float:
    """Combined score 0-100. Higher is better.

    Mirrors v1 hunt's averaging logic, minus the dossier dimension
    (dossier doesn't run as part of judge — it's expensive and per-job).

    Inverts ghost and redflag (low-is-good) so all three components
    align on the same scale.
    """
    score = ((100 - ghost) + (100 - redflag) + alignment) / 3.0
    return round(max(0.0, min(100.0, score)), 1)


def _description_for(discovery: dict[str, Any]) -> str:
    """Pick the best available text for analyzers. Prefers full_description,
    falls back to description (which may be empty for un-enriched Workday rows).
    """
    return (
        (discovery.get("full_description") or "").strip()
        or (discovery.get("description") or "").strip()
    )


def _build_reason(
    *,
    threshold: float,
    combined: float,
    ghost: dict[str, Any],
    redflag: dict[str, Any],
    role: dict[str, Any],
    passed: bool,
) -> str:
    """One-line judgement reason for the row's `judgement_reason` field."""
    parts: list[str] = []
    if passed:
        parts.append(f"combined {combined:.1f} >= {threshold:.0f}")
    else:
        parts.append(f"combined {combined:.1f} < {threshold:.0f}")

    ghost_score = ghost.get("ghost_score", 0)
    redflag_score = redflag.get("redflag_score", 0)
    alignment_score = role.get("alignment_score", 0)
    parts.append(f"ghost={ghost_score} redflag={redflag_score} align={alignment_score}")

    dealbreakers = redflag.get("dealbreakers_found", [])
    if dealbreakers:
        parts.append(f"{len(dealbreakers)} dealbreaker(s)")

    return "; ".join(parts)


def judge_discovery(
    discovery: dict[str, Any],
    *,
    profile: dict[str, Any],
    threshold: float | None = None,
) -> dict[str, Any]:
    """Run the three analyzers on one discovery. Returns a result dict.

    Does NOT write to the DB — caller is responsible. Profile is REQUIRED
    here because redflags needs dealbreakers/yellow/green flags.
    """
    cfg = _judge_config(profile)
    if threshold is None:
        threshold = cfg["ready_threshold"]

    text = _description_for(discovery)
    if not text or len(text) < 100:
        return {
            "screened_status": "rejected",
            "ghost_score": 0.0,
            "redflag_score": 0.0,
            "alignment_score": 0.0,
            "combined_score": 0.0,
            "judgement_reason": "no usable description (run charon enrich first)",
            "judgement_detail": None,
            "error": "no description",
        }

    target_roles = profile.get("target_roles", []) or []

    try:
        ghost = analyze_ghostbust(text)
        redflag = analyze_redflags(text, profile)
        role = analyze_role_alignment(text, target_roles) if target_roles else {
            "alignment_score": 50,
            "closest_target": None,
            "overlap": [],
            "gaps": [],
            "stepping_stone": False,
            "assessment": "no target_roles configured; skipping role alignment",
        }
    except AIError as e:
        return {
            "screened_status": "rejected",
            "ghost_score": 0.0,
            "redflag_score": 0.0,
            "alignment_score": 0.0,
            "combined_score": 0.0,
            "judgement_reason": f"AI error: {e}",
            "judgement_detail": None,
            "error": str(e),
        }

    ghost_score = float(ghost.get("ghost_score", 0))
    redflag_score = float(redflag.get("redflag_score", 0))
    alignment_score = float(role.get("alignment_score", 0))
    combined = compute_combined(ghost_score, redflag_score, alignment_score)

    passed = combined >= threshold
    reason = _build_reason(
        threshold=threshold,
        combined=combined,
        ghost=ghost,
        redflag=redflag,
        role=role,
        passed=passed,
    )

    return {
        "screened_status": "ready" if passed else "rejected",
        "ghost_score": ghost_score,
        "redflag_score": redflag_score,
        "alignment_score": alignment_score,
        "combined_score": combined,
        "judgement_reason": reason,
        "judgement_detail": {
            "ghostbust": ghost,
            "redflags": redflag,
            "role_alignment": role,
        },
    }


def judge_one_id(
    discovery_id: int,
    *,
    profile: dict[str, Any],
    threshold: float | None = None,
    rejudge: bool = False,
) -> dict[str, Any]:
    """Judge one discovery by ID, write to DB. Returns the result."""
    discovery = get_discovery(discovery_id)
    if discovery is None:
        raise JudgeError(f"No discovery with id {discovery_id}.")

    if discovery.get("judged_at") and not rejudge:
        return {
            "screened_status": discovery.get("screened_status"),
            "ghost_score": discovery.get("ghost_score"),
            "redflag_score": discovery.get("redflag_score"),
            "alignment_score": discovery.get("alignment_score"),
            "combined_score": discovery.get("combined_score"),
            "judgement_reason": discovery.get("judgement_reason"),
            "judgement_detail": None,
            "discovery_id": discovery_id,
            "company": discovery.get("company"),
            "role": discovery.get("role"),
            "skipped_reason": "already judged (use --rejudge to re-run)",
        }

    result = judge_discovery(discovery, profile=profile, threshold=threshold)
    if result.get("error") and result["judgement_reason"].startswith("no usable description"):
        # Don't write rejection rows for un-enriched discoveries — let the user
        # know to run enrich first. Caller surfaces this as a warning.
        result["discovery_id"] = discovery_id
        result["company"] = discovery.get("company")
        result["role"] = discovery.get("role")
        return result

    update_discovery_judgement(
        discovery_id,
        ghost_score=result["ghost_score"],
        redflag_score=result["redflag_score"],
        alignment_score=result["alignment_score"],
        combined_score=result["combined_score"],
        screened_status=result["screened_status"],
        judgement_reason=result["judgement_reason"],
        judgement_detail=result.get("judgement_detail"),
    )
    result["discovery_id"] = discovery_id
    result["company"] = discovery.get("company")
    result["role"] = discovery.get("role")
    return result


def judge_batch(
    *,
    ats: str | None = None,
    rejudge: bool = False,
    limit: int | None = None,
    threshold: float | None = None,
    profile: dict[str, Any],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Judge many discoveries. Default: only unjudged + already-enriched.

    With rejudge=True, picks up everything matching the ats/limit filter
    regardless of prior judgement state.
    """
    if rejudge:
        targets = get_discoveries(ats=ats, limit=limit)
    else:
        targets = get_unjudged_discoveries(ats=ats, limit=limit)

    results: list[dict[str, Any]] = []
    for discovery in targets:
        try:
            result = judge_one_id(
                discovery["id"],
                profile=profile,
                threshold=threshold,
                rejudge=rejudge,
            )
        except JudgeError as e:
            result = {
                "discovery_id": discovery["id"],
                "company": discovery.get("company"),
                "role": discovery.get("role"),
                "screened_status": "rejected",
                "judgement_reason": str(e),
                "error": str(e),
            }
        results.append(result)
        if on_progress:
            on_progress(result)

    return results


def list_by_status(
    status: str,
    ats: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """List judged discoveries by screened_status (ready / rejected)."""
    if status not in {"ready", "rejected"}:
        raise JudgeError(f"status must be 'ready' or 'rejected', got '{status}'.")

    rows = get_discoveries(ats=ats, status=status, limit=limit)
    # Filter to only judged rows (status='rejected' could match unjudged
    # discoveries that failed enrich; we want judged-only here).
    return [r for r in rows if r.get("judged_at")]


__all__ = [
    "DEFAULT_BULK_WARN_AT",
    "DEFAULT_READY_THRESHOLD",
    "JudgeError",
    "compute_combined",
    "judge_batch",
    "judge_discovery",
    "judge_one_id",
    "list_by_status",
]
