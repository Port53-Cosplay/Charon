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
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Iterable, Optional


class CullError(Exception):
    """Raised when cull can't get a usable decision from the model."""


_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
_DEEPSEEK_MODEL = "deepseek-chat"

# Cull is I/O-bound (one DeepSeek HTTP call per row), so the network calls run
# in a thread pool. 8 is a conservative default; override with the
# CHARON_CULL_CONCURRENCY env var if DeepSeek's rate limits allow more.
DEFAULT_CULL_CONCURRENCY = 8
_SYSTEM_PROMPT = """You are a security-job filter for a candidate searching for hands-on defensive cybersecurity roles. Your only job is to drop wrong postings before they get expensive analysis.

You see only the role title, company, and location — no description. That is intentional.

The candidate's target roles are hands-on defensive practitioner roles: incident response, DFIR, SOC analyst, detection engineering, threat analysis, application security, IT/security/compliance auditing, GRC analyst.

Output strict JSON: {"decision": "pass" | "refuse", "reason": "<10 words or fewer>", "confidence": "high" | "medium" | "low"}.

Decision rule:
- refuse if the role is not security at all: Sales Engineer, Marketing, Customer Success, Recruiter, generic Software Engineer, HR, Finance, trading/quant, data science, design, etc.
- refuse if the role is not a hands-on practitioner role, EVEN IF the title contains security words: product/program/project managers, UX/UI designers, Directors, VPs, C-suite, "Head of", account executives, solutions/sales engineers, generic consultants, instructors. "Senior Product Manager - Data Protection" is a refuse; the function is product management, not security work. (Seniority alone is fine — "Senior Security Engineer" and "Staff Security Analyst" are practitioners, not executives.)
- refuse if the posting is obviously a recruiter test/placeholder requisition, not a real job: titles like "Test job 123", "Easy Apply Test", "EA Test", "TEST <anything>", "Demo Requisition". Real companies leave these on their boards; they enrich to nothing and waste the pipeline.
- refuse if the role clearly contradicts the candidate's geographic constraint (US-only, remote).
- Otherwise pass. A plausibly hands-on security title — analyst, engineer, responder, auditor, specialist — passes even if offensive-leaning; the deeper pipeline will judge it.
- If you genuinely cannot tell what the role is, pass.

confidence reflects YOUR certainty:
- high: you are sure (e.g. "Director of Sales", "Marketing Manager", "Senior Product Manager - Security") → only this triggers an actual refuse
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
    ]
    if profile.get("us_canada_only"):
        lines += [
            "## GEOGRAPHIC HARD RULE",
            "The candidate can ONLY work in the United States or Canada. Refuse "
            "(decision 'refuse', confidence 'high') if the Location is anywhere "
            "else. Use your knowledge of world geography: a bare city such as "
            "Bengaluru, Hyderabad, São Paulo, Paris, or London counts as its "
            "real country. A bare 'Remote' with no country, or any US/Canada "
            "location, is acceptable. Only refuse on geography when you can "
            "actually place the location outside the US/Canada.",
            "",
        ]
    lines += [
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


# Geography gate (opt-in per profile via `us_canada_only`). High precision:
# only refuse when the location clearly names a foreign country, and never
# when it mentions the US or Canada (so US/Canada and bare "Remote" pass).
_FOREIGN_NAMES = (
    "belgië", "belgium", "belgique", "nederland", "netherlands", "pays-bas",
    "france", "deutschland", "germany", "allemagne", "united kingdom",
    "england", "scotland", "ireland", "éire", "españa", "spain", "espagne",
    "cataluña", "catalunya", "italia", "italy", "italie", "portugal",
    "poland", "polska", "schweiz", "switzerland", "suisse", "österreich",
    "austria", "autriche", "sweden", "sverige", "denmark", "danmark",
    "norway", "norge", "finland", "suomi", "luxembourg", "luxemburg",
    "south africa", "singapore", "hong kong", "japan", "czech", "tchéquie",
    "tchequie", "romania", "greece", "hungary", "méxico", "mexico", "brasil",
    "brazil", "australia", "new zealand", "india", "united arab emirates",
    "dubai",
)
# Trailing country codes that don't collide with US state abbreviations.
_FOREIGN_CODES = (
    "nl", "be", "fr", "gb", "uk", "ie", "pt", "pl", "ch", "se", "dk", "fi",
    "lu", "za", "sg", "hk", "jp", "cz", "ro", "gr", "hu", "au", "nz", "ae",
    "es", "it", "at",
)


def _is_foreign_location(location: str | None) -> bool:
    """True only when the location clearly names a country outside the US/Canada.
    Conservative: unknown/blank or any mention of the US or Canada returns False,
    so US, Canadian, and bare 'Remote' postings are never blocked.
    """
    loc = (location or "").strip().lower()
    if not loc:
        return False
    if "united states" in loc or "canada" in loc:
        return False
    if any(name in loc for name in _FOREIGN_NAMES):
        return True
    return any(loc.endswith(f", {cc}") or f", {cc}," in loc for cc in _FOREIGN_CODES)


# Evergreen "send us your CV" pages, not real openings — junk in any language.
_OPEN_APP_MARKERS = (
    "open application", "candidature spontan", "spontaneous application",
    "unsolicited application", "initiativbewerbung", "spontane sollicitatie",
    "open sollicitatie", "speculative application", "talent community",
    "talent pool", "candidatura espontá", "candidatura spontanea",
)


def _is_open_application(role: str | None) -> bool:
    """True for evergreen open/spontaneous-application listings (not real jobs)."""
    r = (role or "").lower()
    return any(m in r for m in _OPEN_APP_MARKERS)


def _matched_blocked_employer(row: dict[str, Any], profile: dict[str, Any]) -> str | None:
    """Return the blocked-employer name if this row's company is on the
    profile's `blocked_employers` list (case-insensitive, trimmed exact match),
    else None. These are employers categorically unsuitable regardless of the
    specific posting — e.g. always-on-site municipal boards that would require
    relocation — so they're dropped before any paid analysis.
    """
    blocked = profile.get("blocked_employers") or []
    company = (row.get("company") or "").strip().casefold()
    if not company or not blocked:
        return None
    for name in blocked:
        if isinstance(name, str) and name.strip().casefold() == company:
            return name.strip()
    return None


def cull_one(row: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Run cull on one discovery row.

    Returns {"decision": "pass"|"refuse", "reason": str,
    "confidence": "high"|"medium"|"low"}.

    Caller applies the conservative gate: only refuse when
    decision=='refuse' AND confidence=='high'.
    """
    # Deterministic pre-filter: blocked employers never reach the LLM (or the
    # paid judge). Returned as a high-confidence refuse so the conservative gate
    # in apply_cull_decision writes it as rejected.
    blocked = _matched_blocked_employer(row, profile)
    if blocked:
        return {
            "decision": "refuse",
            "reason": f"blocked employer: {blocked}",
            "confidence": "high",
        }

    # Evergreen open/spontaneous-application pages are never real openings.
    if _is_open_application(row.get("role")):
        return {
            "decision": "refuse",
            "reason": "open/spontaneous application (not a real posting)",
            "confidence": "high",
        }

    # Geography gate — only when this profile opts in (keeps Don's fork, which
    # shares this code, unaffected). US, Canada, and bare "Remote" always pass.
    if profile.get("us_canada_only") and _is_foreign_location(row.get("location")):
        return {
            "decision": "refuse",
            "reason": f"outside US/Canada: {(row.get('location') or '').strip()}",
            "confidence": "high",
        }

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


def _resolve_concurrency(concurrency: Optional[int]) -> int:
    """Pick the worker count: explicit arg, else CHARON_CULL_CONCURRENCY, else default."""
    if concurrency is not None:
        return max(1, concurrency)
    env = os.environ.get("CHARON_CULL_CONCURRENCY", "").strip()
    if env.isdigit() and int(env) > 0:
        return int(env)
    return DEFAULT_CULL_CONCURRENCY


def cull_batch(
    rows: Iterable[dict[str, Any]],
    profile: dict[str, Any],
    *,
    concurrency: Optional[int] = None,
    on_result: Optional[Callable[[dict[str, Any], Optional[str], Optional[Exception]], None]] = None,
) -> None:
    """Cull many rows, running the DeepSeek calls concurrently.

    The network call (`cull_one`) runs in a thread pool; the DB write
    (`apply_cull_decision`) runs in the CALLING thread as each result lands, so
    SQLite access stays single-threaded (same thread that owns the connection).

    `on_result(row, outcome, error)` is invoked once per row, in the calling
    thread — `outcome` is 'passed'/'refused' on success (error None), or `error`
    is the exception and outcome is None on failure. Use it for progress
    counters. Exceptions never propagate out of the pool; each row is isolated.
    """
    rows = list(rows)
    if not rows:
        return
    workers = min(_resolve_concurrency(concurrency), len(rows))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(cull_one, row, profile): row for row in rows}
        for fut in as_completed(futures):
            row = futures[fut]
            try:
                decision = fut.result()
                outcome = apply_cull_decision(row["id"], decision)
                if on_result:
                    on_result(row, outcome, None)
            except CullError as e:
                if on_result:
                    on_result(row, None, e)
            except Exception as e:  # noqa: BLE001
                if on_result:
                    on_result(row, None, e)


__all__ = ["CullError", "cull_one", "apply_cull_decision", "cull_batch"]
