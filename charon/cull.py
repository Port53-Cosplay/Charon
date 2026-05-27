"""Cull — DeepSeek pre-judge pass.

A cheap, fast first-cut between gather and enrich. Looks at title +
company + location alone (no description fetch needed) and culls
confident non-fits before they burn Sonnet tokens on enrichment and
judging.

Uses DeepSeek V3 via its OpenAI-compatible API. At ~$0.27/M input
tokens, a full cull of ~1500 unjudged rows costs roughly $0.08 — a
rounding error compared to the Sonnet enrich + judge spend it
prevents.

Conservative by design: refuse only when the model reports high
confidence in a mismatch. False negatives (passing a junk row) are
cheap — the existing pipeline catches them downstream. False
positives (refusing a good row) are bad — that row never sees Sonnet.

Charon culls the unworthy at the riverbank before they reach the
ferryman's coin.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any


class CullError(Exception):
    """Raised when cull can't get a usable decision from the model."""


_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
_DEEPSEEK_MODEL = "deepseek-chat"
_SYSTEM_PROMPT = """You are a security-job filter for a candidate searching for defensive cybersecurity roles. Your only job is to drop the most-obviously-wrong postings before they get expensive analysis.

You see only the role title, company, and location — no description. That is intentional.

The candidate's target roles are defensive: incident response, DFIR, SOC analyst, detection engineering, threat analysis, application security, IT/security/compliance auditing, GRC analyst.

Output strict JSON: {"decision": "pass" | "refuse", "reason": "<10 words or fewer>", "confidence": "high" | "medium" | "low"}.

Decision rule (CONSERVATIVE):
- refuse ONLY if you are confident the role is not security at all (Sales Engineer, Marketing, Customer Success, Recruiter, generic Software Engineer, HR, Finance, etc.) OR clearly contradicts the candidate's geographic constraint (US-only, remote).
- Anything plausibly security-adjacent: pass. Even if it's offensive-leaning or senior — the deeper pipeline will judge it.
- When in doubt, pass. The downstream judge will do the careful work.

confidence reflects YOUR certainty:
- high: you are sure (e.g. "Director of Sales", "Marketing Manager") → only this triggers an actual refuse
- medium / low: you are guessing → caller will pass these through anyway
"""


def _resolve_api_key() -> str:
    """Try env first, fall back to Vault. Raises CullError if neither works."""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key

    try:
        from charon.vault import get_secret  # type: ignore
        v = get_secret("charon/deepseek-api")
        if v and v.get("key"):
            return str(v["key"])
    except Exception:
        pass

    raise CullError(
        "No DeepSeek API key found. Set DEEPSEEK_API_KEY env var or store at "
        "secret/empire12/charon/deepseek-api in Vault."
    )


def _build_user_prompt(row: dict[str, Any], profile: dict[str, Any]) -> str:
    target_roles = profile.get("target_roles") or []
    dealbreakers = profile.get("dealbreakers") or []
    company = (row.get("company") or "").strip() or "(unknown)"
    role = (row.get("role") or "").strip() or "(unknown)"
    location = (row.get("location") or "").strip() or "(not specified)"
    tier = row.get("tier") or "(no tier)"
    ats = row.get("ats") or "(no ats)"

    lines = [
        "## CANDIDATE TARGET ROLES",
        *(f"- {r}" for r in target_roles),
        "",
        "## CANDIDATE DEALBREAKERS",
        *(f"- {d}" for d in dealbreakers),
        "",
        "## POSTING",
        f"Company: {company}",
        f"Role: {role}",
        f"Location: {location}",
        f"Employer tier: {tier}",
        f"ATS: {ats}",
        "",
        "Return JSON only. No markdown fence, no prose.",
    ]
    return "\n".join(lines)


_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)


def _parse_model_output(text: str) -> dict[str, Any]:
    """Extract the first JSON object from the model's response."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _JSON_RE.search(text)
    if not m:
        raise CullError(f"No JSON object in model response: {text[:200]!r}")
    return json.loads(m.group(0))


def cull_one(row: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Run cull on one discovery row.

    Returns {"decision": "pass"|"refuse", "reason": str,
    "confidence": "high"|"medium"|"low"}.

    Caller applies the conservative gate: only refuse when
    decision=='refuse' AND confidence=='high'.
    """
    # OpenAI SDK is OpenAI-compatible with DeepSeek's endpoint — just
    # point base_url at api.deepseek.com and use the same Chat
    # Completions surface.
    from openai import OpenAI

    api_key = _resolve_api_key()
    client = OpenAI(api_key=api_key, base_url=_DEEPSEEK_BASE_URL)

    user_prompt = _build_user_prompt(row, profile)
    try:
        resp = client.chat.completions.create(
            model=_DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
            max_tokens=300,
        )
    except Exception as e:  # noqa: BLE001
        raise CullError(f"DeepSeek call failed: {type(e).__name__}: {e}") from e

    if not resp.choices:
        raise CullError("DeepSeek returned no choices.")
    text = (resp.choices[0].message.content or "").strip()
    if not text:
        raise CullError("DeepSeek returned empty content.")

    parsed = _parse_model_output(text)
    decision = (parsed.get("decision") or "").strip().lower()
    confidence = (parsed.get("confidence") or "").strip().lower()
    reason = (parsed.get("reason") or "").strip() or "(no reason)"

    if decision not in {"pass", "refuse"}:
        raise CullError(f"Unexpected decision value: {decision!r}")
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"

    return {"decision": decision, "reason": reason, "confidence": confidence}


def apply_cull_decision(
    discovery_id: int,
    decision: dict[str, Any],
) -> str:
    """Apply the conservative gate and write to the DB.

    Returns 'refused' (wrote screened_status='rejected' + reason) or
    'passed' (just set culled_at).
    """
    from charon.db import mark_discovery_culled, mark_discovery_rejected

    if decision["decision"] == "refuse" and decision["confidence"] == "high":
        reason = f"[cull] {decision['reason']}"
        mark_discovery_rejected(discovery_id, reason=reason)
        mark_discovery_culled(discovery_id)
        return "refused"
    mark_discovery_culled(discovery_id)
    return "passed"


__all__ = ["CullError", "cull_one", "apply_cull_decision"]
