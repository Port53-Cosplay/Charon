"""Screening-monoculture risk scorer — the 5th judge dimension.

Premise: a posting's value to the candidate is partly a function of whether
a human will actually read the application. When most US employers funnel
through the same handful of algorithmic screening vendors (HireVue,
Pymetrics, Eightfold AI, Workday's AI hiring tools), applicants face
correlated rejections regardless of fit — the Mobley v. Workday class
action covers the 10,000+ employer customers of one such tool.

This module produces a `monoculture_score` 0-100 (lower = better, i.e.
more likely to land on a human's desk). Three sub-signals blend into the
score per `profile.monoculture.weights`:

  ats_risk         from `discovery.ats` (Workday > Greenhouse/Lever >
                   Ashby > direct-careers > unknown)
  size_risk        from `discovery.tier` (tier_3 enterprise > tier_2
                   mid > tier_1 boutique)
  jd_pattern_risk  regex hits on `discovery.full_description` for known
                   screening vendors and automated-assessment phrases

Fully deterministic — no API calls. The vendor / phrase lists, the ATS
risk weights, and the tier risk weights are all overridable from
profile.yaml; defaults below are sensible starting points.

The output dict slots into `judgement_detail["screening_monoculture"]`
alongside the four LLM analyzers. compute_combined_weighted in screen.py
subtracts the score from 100 the same way it does for ghost / redflag,
so high monoculture risk sinks the combined score.
"""

from __future__ import annotations

import re
from typing import Any


# Default sub-weights inside the monoculture score itself.
DEFAULT_SUB_WEIGHTS = {
    "ats": 0.4,
    "size": 0.3,
    "jd_patterns": 0.3,
}

# discovery.ats → 0-100 risk. Workday is the heaviest per Mobley v. Workday.
DEFAULT_ATS_RISK = {
    "workday": 90,
    "icims": 75,
    "greenhouse": 50,
    "lever": 50,
    "ashby": 30,
    "direct": 10,
    "unknown": 50,
}

# discovery.tier (from companies.yaml) → 0-100 risk. Tier_3 = enterprise.
DEFAULT_SIZE_RISK = {
    "tier_3": 80,
    "tier_2": 50,
    "tier_1": 25,
    "unknown": 50,
}

# Vendor names that appear in JDs when the posting will route through an
# algorithmic screen. Each match adds its weight to jd_pattern_risk, capped
# at 100.
DEFAULT_VENDOR_PATTERNS = [
    {"pattern": r"\bHireVue\b",                          "weight": 30},
    {"pattern": r"\bPymetrics\b",                        "weight": 30},
    {"pattern": r"\bEightfold(?:\s+AI)?\b",              "weight": 30},
    {"pattern": r"\bPlum(?:\.io)?\b",                    "weight": 25},
    {"pattern": r"\bModern\s+Hire\b",                    "weight": 25},
    {"pattern": r"\bSpark\s+Hire\b",                     "weight": 25},
    {"pattern": r"\bMya(?:\s+Systems)?\b",               "weight": 25},
    {"pattern": r"\bHackerRank\b",                       "weight": 20},
    {"pattern": r"\bCodility\b",                         "weight": 20},
]

# Phrases that strongly suggest automated screening even when no vendor is
# named explicitly. Less specific than vendor names so weighted lower.
DEFAULT_PHRASE_PATTERNS = [
    {"pattern": r"AI[-\s]?powered screening",            "weight": 30},
    {"pattern": r"one[-\s]?way video",                   "weight": 25},
    {"pattern": r"game[-\s]?based assessment",           "weight": 20},
    {"pattern": r"automated assessment",                 "weight": 20},
    {"pattern": r"\bvideo interview\b",                  "weight": 15},
]


def _config(profile: dict[str, Any] | None) -> dict[str, Any]:
    cfg = (profile or {}).get("monoculture") or {}
    weights = cfg.get("weights")
    if not isinstance(weights, dict):
        weights = DEFAULT_SUB_WEIGHTS
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "weights": {str(k): float(v) for k, v in weights.items()},
        "ats_risk": {str(k).lower(): float(v) for k, v in (cfg.get("ats_risk") or DEFAULT_ATS_RISK).items()},
        "size_risk": {str(k).lower(): float(v) for k, v in (cfg.get("size_risk") or DEFAULT_SIZE_RISK).items()},
        "vendor_patterns": cfg.get("vendor_patterns") or DEFAULT_VENDOR_PATTERNS,
        "phrase_patterns": cfg.get("phrase_patterns") or DEFAULT_PHRASE_PATTERNS,
    }


def _match_patterns(
    text: str,
    patterns: list[dict[str, Any]],
    category: str,
) -> tuple[float, list[dict[str, Any]]]:
    """Accumulate weights from patterns that match `text`. Returns
    (total_weight, signals). Each signal is `{category, evidence, risk}`."""
    if not text:
        return 0.0, []
    total = 0.0
    signals: list[dict[str, Any]] = []
    for pat in patterns:
        if not isinstance(pat, dict):
            continue
        rx = pat.get("pattern")
        if not rx:
            continue
        try:
            if re.search(rx, text, re.IGNORECASE):
                w = float(pat.get("weight", 20))
                total += w
                signals.append({
                    "category": category,
                    "evidence": rx,
                    "risk": w,
                })
        except re.error:
            # Bad regex in user-config — skip rather than crash judge
            continue
    return total, signals


def score_monoculture(
    discovery: dict[str, Any],
    profile: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Score a discovery on screening-monoculture risk.

    Returns None when monoculture is disabled in profile. Otherwise:

        {
          "monoculture_score": 0-100,   # blended (lower = better)
          "ats_risk":          0-100,
          "size_risk":         0-100,
          "jd_pattern_risk":   0-100,
          "signals":           [{category, evidence, risk}, ...],
          "summary":           str,
          "applied_weights":   {ats, size, jd_patterns}  # normalized
        }
    """
    cfg = _config(profile)
    if not cfg["enabled"]:
        return None

    signals: list[dict[str, Any]] = []

    # ── ATS risk ───────────────────────────────────────────────────────
    ats_raw = (discovery.get("ats") or "").strip().lower()
    ats_key = ats_raw or "unknown"
    ats_risk = float(cfg["ats_risk"].get(ats_key, cfg["ats_risk"].get("unknown", 50)))
    signals.append({
        "category": "ats",
        "evidence": f"ATS = {ats_raw or 'unknown'}",
        "risk": ats_risk,
    })

    # ── Size risk via tier ─────────────────────────────────────────────
    tier_raw = (discovery.get("tier") or "").strip().lower()
    tier_key = tier_raw or "unknown"
    size_risk = float(cfg["size_risk"].get(tier_key, cfg["size_risk"].get("unknown", 50)))
    signals.append({
        "category": "size",
        "evidence": f"tier = {tier_raw or 'unknown'}",
        "risk": size_risk,
    })

    # ── JD pattern risk (regex on full_description) ────────────────────
    jd_text = (discovery.get("full_description") or "").strip()
    vendor_weight, vendor_signals = _match_patterns(
        jd_text, cfg["vendor_patterns"], "vendor_mention"
    )
    phrase_weight, phrase_signals = _match_patterns(
        jd_text, cfg["phrase_patterns"], "screening_phrase"
    )
    jd_pattern_risk = min(100.0, vendor_weight + phrase_weight)
    signals.extend(vendor_signals)
    signals.extend(phrase_signals)

    # ── Blend the three sub-signals ────────────────────────────────────
    components = {
        "ats": ats_risk,
        "size": size_risk,
        "jd_patterns": jd_pattern_risk,
    }
    active = {
        k: max(0.0, float(cfg["weights"].get(k, 0)))
        for k in components
    }
    if sum(active.values()) <= 0:
        # All weights zero → equal blend across the three
        active = {k: 1.0 for k in components}
    total_w = sum(active.values())
    blended = sum(active[k] * components[k] for k in active) / total_w
    blended = max(0.0, min(100.0, blended))

    # ── Summary line ───────────────────────────────────────────────────
    summary_bits: list[str] = []
    if ats_key != "unknown":
        summary_bits.append(f"ATS={ats_raw}({int(ats_risk)})")
    if tier_key != "unknown":
        summary_bits.append(f"size={tier_raw}({int(size_risk)})")
    if jd_pattern_risk > 0:
        n = len(vendor_signals) + len(phrase_signals)
        summary_bits.append(f"jd_patterns({int(jd_pattern_risk)}, {n} hit{'s' if n != 1 else ''})")
    summary = " · ".join(summary_bits) if summary_bits else "no monoculture signals detected"

    return {
        "monoculture_score": round(blended, 1),
        "ats_risk": round(ats_risk, 1),
        "size_risk": round(size_risk, 1),
        "jd_pattern_risk": round(jd_pattern_risk, 1),
        "signals": signals,
        "summary": summary,
        "applied_weights": {k: round(v / total_w, 3) for k, v in active.items()},
    }


__all__ = ["score_monoculture"]
