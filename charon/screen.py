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
    update_discovery_classification,
    update_discovery_judgement,
)
from charon.ghostbust import analyze_ghostbust
from charon.hunt import analyze_role_alignment
from charon.redflags import analyze_redflags
from charon.resume_match import (
    ResumeMatchError,
    analyze_resume_match,
    load_resume_text,
)


DEFAULT_READY_THRESHOLD = 60
DEFAULT_ALIGNMENT_FLOOR = 50  # auto-reject if alignment_score < floor regardless of combined
DEFAULT_BULK_WARN_AT = 50  # warn before judging more than this many at once

DEFAULT_WEIGHTS_4 = {
    "ghost": 0.15,
    "redflag": 0.20,
    "role_alignment": 0.25,
    "resume_match": 0.40,
}
DEFAULT_WEIGHTS_3 = {
    "ghost": 0.20,
    "redflag": 0.25,
    "role_alignment": 0.55,
}


class JudgeError(Exception):
    """Raised when judging fails for reasons the user should see."""


def _judge_config(profile: dict[str, Any] | None) -> dict[str, Any]:
    cfg = (profile or {}).get("judge") or {}
    weights = cfg.get("weights")
    return {
        "ready_threshold": float(cfg.get("ready_threshold", DEFAULT_READY_THRESHOLD)),
        "alignment_floor": float(cfg.get("alignment_floor", DEFAULT_ALIGNMENT_FLOOR)),
        "bulk_warn_at": int(cfg.get("bulk_warn_at", DEFAULT_BULK_WARN_AT)),
        "weights": weights if isinstance(weights, dict) else None,
        "resume_path": (profile or {}).get("resume_path") or "",
    }


def compute_combined_weighted(
    *,
    ghost: float,
    redflag: float,
    alignment: float,
    resume_match: float | None,
    weights: dict[str, float] | None,
) -> float:
    """Combined score with optional weights and optional resume_match.

    Falls back to equal-component formula if weights is None.
    Falls back to 3-component formula if resume_match is None.
    """
    components = {
        "ghost": 100.0 - ghost,
        "redflag": 100.0 - redflag,
        "role_alignment": alignment,
    }
    if resume_match is not None:
        components["resume_match"] = resume_match

    if weights is None:
        # Equal weighting across the components we have
        score = sum(components.values()) / len(components)
        return round(max(0.0, min(100.0, score)), 1)

    # Use only the weights for components we actually have
    active = {k: weights.get(k, 0) for k in components if weights.get(k, 0) > 0}
    if not active:
        # All weights zero — fall back to equal
        score = sum(components.values()) / len(components)
        return round(max(0.0, min(100.0, score)), 1)

    total_weight = sum(active.values())
    score = sum(active[k] * components[k] for k in active) / total_weight
    return round(max(0.0, min(100.0, score)), 1)


def _decide_status(
    *,
    threshold: float,
    floor: float,
    ghost: float,
    redflag: float,
    alignment: float,
    combined: float,
    resume_match: float | None = None,
    dealbreakers_count: int = 0,
) -> tuple[str, str]:
    """Pure gating logic. Returns (screened_status, judgement_reason)."""
    if alignment < floor:
        reason = (
            f"alignment {alignment:.0f} < floor {floor:.0f}; "
            f"ghost={ghost:.0f} redflag={redflag:.0f}"
        )
        return "rejected", reason

    parts: list[str] = []
    if combined >= threshold:
        parts.append(f"combined {combined:.1f} >= {threshold:.0f}")
        status = "ready"
    else:
        parts.append(f"combined {combined:.1f} < {threshold:.0f}")
        status = "rejected"

    score_part = f"ghost={ghost:.0f} redflag={redflag:.0f} align={alignment:.0f}"
    if resume_match is not None:
        score_part += f" resume={resume_match:.0f}"
    parts.append(score_part)

    if dealbreakers_count:
        parts.append(f"{dealbreakers_count} dealbreaker(s)")
    return status, "; ".join(parts)


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




def judge_discovery(
    discovery: dict[str, Any],
    *,
    profile: dict[str, Any],
    threshold: float | None = None,
    resume_text: str | None = None,
) -> dict[str, Any]:
    """Run the analyzers on one discovery. Returns a result dict.

    Does NOT write to the DB — caller is responsible. Profile is REQUIRED.
    `resume_text`, if provided, enables the 4th analyzer (resume_match)
    and shifts the combined formula to 4 components.
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
            "resume_match_score": None,
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
        resume_result = None
        if resume_text:
            resume_result = analyze_resume_match(text, resume_text)
    except AIError as e:
        return {
            "screened_status": "rejected",
            "ghost_score": 0.0,
            "redflag_score": 0.0,
            "alignment_score": 0.0,
            "resume_match_score": None,
            "combined_score": 0.0,
            "judgement_reason": f"AI error: {e}",
            "judgement_detail": None,
            "error": str(e),
        }

    ghost_score = float(ghost.get("ghost_score", 0))
    redflag_score = float(redflag.get("redflag_score", 0))
    alignment_score = float(role.get("alignment_score", 0))
    resume_match_score = (
        float(resume_result.get("match_score", 0)) if resume_result else None
    )

    combined = compute_combined_weighted(
        ghost=ghost_score,
        redflag=redflag_score,
        alignment=alignment_score,
        resume_match=resume_match_score,
        weights=cfg["weights"],
    )
    dealbreakers_count = len(redflag.get("dealbreakers_found", []))

    status, reason = _decide_status(
        threshold=threshold,
        floor=cfg["alignment_floor"],
        ghost=ghost_score,
        redflag=redflag_score,
        alignment=alignment_score,
        resume_match=resume_match_score,
        combined=combined,
        dealbreakers_count=dealbreakers_count,
    )

    detail: dict[str, Any] = {
        "ghostbust": ghost,
        "redflags": redflag,
        "role_alignment": role,
    }
    if resume_result is not None:
        detail["resume_match"] = resume_result

    return {
        "screened_status": status,
        "ghost_score": ghost_score,
        "redflag_score": redflag_score,
        "alignment_score": alignment_score,
        "resume_match_score": resume_match_score,
        "combined_score": combined,
        "judgement_reason": reason,
        "judgement_detail": detail,
    }


def _maybe_load_resume(profile: dict[str, Any] | None) -> str | None:
    """Load resume text from configured path, or None if unset/missing."""
    cfg = _judge_config(profile)
    raw_path = cfg["resume_path"]
    if not raw_path:
        return None
    try:
        return load_resume_text(raw_path)
    except ResumeMatchError:
        return None


def judge_one_id(
    discovery_id: int,
    *,
    profile: dict[str, Any],
    threshold: float | None = None,
    rejudge: bool = False,
    resume_text: str | None = None,
) -> dict[str, Any]:
    """Judge one discovery by ID, write to DB. Returns the result.

    `resume_text` may be passed from the caller to avoid re-reading the
    file on every call. If None, attempts to load from profile.resume_path.
    Pass empty string explicitly to disable.
    """
    discovery = get_discovery(discovery_id)
    if discovery is None:
        raise JudgeError(f"No discovery with id {discovery_id}.")

    if discovery.get("judged_at") and not rejudge:
        return {
            "screened_status": discovery.get("screened_status"),
            "ghost_score": discovery.get("ghost_score"),
            "redflag_score": discovery.get("redflag_score"),
            "alignment_score": discovery.get("alignment_score"),
            "resume_match_score": discovery.get("resume_match_score"),
            "combined_score": discovery.get("combined_score"),
            "judgement_reason": discovery.get("judgement_reason"),
            "judgement_detail": None,
            "discovery_id": discovery_id,
            "company": discovery.get("company"),
            "role": discovery.get("role"),
            "skipped_reason": "already judged (use --rejudge to re-run)",
        }

    if resume_text is None:
        resume_text = _maybe_load_resume(profile)

    result = judge_discovery(
        discovery, profile=profile, threshold=threshold, resume_text=resume_text
    )
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
        resume_match_score=result.get("resume_match_score"),
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
    status: str | None = None,
    limit: int | None = None,
    threshold: float | None = None,
    profile: dict[str, Any],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Judge many discoveries. Default: only unjudged + already-enriched.

    With rejudge=True, picks up everything matching the ats/status/limit
    filters regardless of prior judgement state. Reads the configured
    resume once upfront and threads it through all per-discovery calls.

    `status` filter only applies when rejudge=True (unjudged rows have
    status='new' by default).
    """
    if rejudge:
        targets = get_discoveries(ats=ats, status=status, limit=limit)
    else:
        targets = get_unjudged_discoveries(ats=ats, limit=limit)

    # Load resume once for the whole batch
    resume_text = _maybe_load_resume(profile)

    results: list[dict[str, Any]] = []
    for discovery in targets:
        try:
            result = judge_one_id(
                discovery["id"],
                profile=profile,
                threshold=threshold,
                rejudge=rejudge,
                resume_text=resume_text,
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


def reclassify_one(
    discovery: dict[str, Any],
    *,
    profile: dict[str, Any] | None,
    threshold: float | None = None,
) -> dict[str, Any] | None:
    """Re-apply the gating logic to an already-judged discovery's stored scores.

    No AI calls. Honors the configured weights and falls back to a 3-component
    formula for rows judged before resume_match was introduced.

    Returns the new classification or None if the discovery hasn't been judged
    yet (no scores to reclassify).
    """
    cfg = _judge_config(profile)
    if threshold is None:
        threshold = cfg["ready_threshold"]
    floor = cfg["alignment_floor"]

    ghost = discovery.get("ghost_score")
    redflag = discovery.get("redflag_score")
    alignment = discovery.get("alignment_score")
    if ghost is None or redflag is None or alignment is None:
        return None

    resume_match = discovery.get("resume_match_score")  # may be None on legacy rows
    combined = compute_combined_weighted(
        ghost=ghost,
        redflag=redflag,
        alignment=alignment,
        resume_match=resume_match,
        weights=cfg["weights"],
    )

    # Pull dealbreakers count from stored detail if available
    dealbreakers_count = 0
    detail = discovery.get("judgement_detail")
    if isinstance(detail, str):
        try:
            import json as _json
            parsed = _json.loads(detail)
            dealbreakers_count = len((parsed.get("redflags") or {}).get("dealbreakers_found", []))
        except (ValueError, TypeError):
            pass

    status, reason = _decide_status(
        threshold=threshold,
        floor=floor,
        ghost=ghost,
        redflag=redflag,
        alignment=alignment,
        resume_match=resume_match,
        combined=combined,
        dealbreakers_count=dealbreakers_count,
    )

    return {
        "screened_status": status,
        "ghost_score": ghost,
        "redflag_score": redflag,
        "alignment_score": alignment,
        "resume_match_score": resume_match,
        "combined_score": combined,
        "judgement_reason": reason,
    }


def reclassify_batch(
    *,
    ats: str | None = None,
    limit: int | None = None,
    threshold: float | None = None,
    profile: dict[str, Any] | None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Reclassify all already-judged discoveries against the current profile.

    Free — no AI calls. Useful after tuning ready_threshold or alignment_floor.
    """
    targets = get_discoveries(ats=ats, limit=limit)
    targets = [t for t in targets if t.get("judged_at")]

    results: list[dict[str, Any]] = []
    for discovery in targets:
        new = reclassify_one(discovery, profile=profile, threshold=threshold)
        if new is None:
            continue
        # Compare to existing classification
        prev_status = discovery.get("screened_status")
        prev_reason = discovery.get("judgement_reason")
        new["discovery_id"] = discovery["id"]
        new["company"] = discovery.get("company")
        new["role"] = discovery.get("role")
        new["previous_status"] = prev_status
        new["changed"] = (prev_status != new["screened_status"])

        # Persist if anything changed (status or reason)
        if new["changed"] or new["judgement_reason"] != prev_reason:
            update_discovery_classification(
                discovery["id"],
                screened_status=new["screened_status"],
                combined_score=new["combined_score"],
                judgement_reason=new["judgement_reason"],
            )

        results.append(new)
        if on_progress:
            on_progress(new)

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
    "DEFAULT_ALIGNMENT_FLOOR",
    "DEFAULT_BULK_WARN_AT",
    "DEFAULT_READY_THRESHOLD",
    "JudgeError",
    "compute_combined",
    "judge_batch",
    "judge_discovery",
    "judge_one_id",
    "list_by_status",
    "reclassify_batch",
    "reclassify_one",
]
