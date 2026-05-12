"""Sirens — voice-true LinkedIn post writer.

The premise: DeAnna writes a brain-dump (associative, mid-thought,
unedited) and Sirens polishes it into something postable WITHOUT
turning it into LinkedIn corporate-voice glue. The voice block lives
in profile.yaml so it's the canonical source for both Sirens and
(eventually) petition.

Inputs:
  - brain_dump: the actual content DeAnna typed
  - optional magical_question: the prompt that inspired her (used as
    context the LLM should be aware of, not pasted verbatim into the
    post)
  - optional context: a recent discovery / application reference she
    wants to weave in (e.g. "I just applied to GuidePoint for Sr.
    DFIR Consultant")

Output: structured JSON with the polished post text, char count, and
any flagged voice violations the model caught in its own draft (so
the UI can show a "could be tighter here" hint).

Cost: one Sonnet call per polish, ~$0.01-0.03. No web search.
"""

from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any


TEMPLATES_DIR = Path(__file__).parent / "templates"
MAGICAL_QUESTIONS_FILE = "magical_questions.yaml"

DRAFTS_DIRNAME = "sirens/drafts"

LINKEDIN_CHAR_LIMIT = 3000


class SirensError(Exception):
    pass


# ── magical questions ───────────────────────────────────────────────


def _load_magical_questions() -> list[str]:
    import yaml

    path = TEMPLATES_DIR / MAGICAL_QUESTIONS_FILE
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return []
    questions = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(questions, list):
        return []
    return [str(q) for q in questions if isinstance(q, str) and q.strip()]


def random_magical_question() -> str | None:
    questions = _load_magical_questions()
    return random.choice(questions) if questions else None


# ── voice prompt ────────────────────────────────────────────────────


def voice_block_from_profile(profile: dict[str, Any]) -> str:
    """Pull the voice description from profile.yaml. Falls back to a
    minimal safety net if the voice block is missing.

    Shared by Sirens (posts) and petition (cover letters) so both flows
    speak with the same voice. Tone-of-output rules (length, structure,
    banned phrases) stay in each caller's prompt — only the voice
    description itself comes from here.
    """
    voice = profile.get("voice") if isinstance(profile, dict) else None
    if isinstance(voice, dict):
        desc = voice.get("description")
        if isinstance(desc, str) and desc.strip():
            return desc.strip()
    return (
        "Conversational, specific, no LinkedIn corporate voice, no "
        "engagement-bait phrasings. Vary sentence length. Use "
        "contractions. Read aloud — if no real person would say it, "
        "rewrite."
    )


# Backwards-compat shim for any internal callers
_voice_block = voice_block_from_profile


SIRENS_SYSTEM_TEMPLATE = """\
You are Sirens — a writing collaborator for a real person who hates
LinkedIn corporate voice. Your one job is to take their unedited
brain-dump and shape it into a postable piece WITHOUT laundering
their voice into AI-speak or hustle-bait.

You are NOT writing the post from scratch. The brain-dump is the
post; you are tightening it, sharpening the rhythm, fixing typos,
trimming repetitions — minimal intervention. If the brain-dump is
already good, return it almost as-is. If it's rough, polish it the
way a thoughtful editor would: preserve sentence structure choices,
preserve "like" and parentheticals and tangents that circle back,
preserve emotional honesty. Don't reach for metaphor the writer
didn't reach for. Don't add a tidy summary at the end.

VOICE TO MATCH:

{voice_block}

OUTPUT RULES:

- Final post text is plain text (no markdown), under 3000 characters
  (LinkedIn's limit). Aim for 1200-2200 if it can land at that
  length without strain. Hard cap at 3000.
- DO NOT add a header, title, or "✨ Post:" label.
- DO NOT add hashtags unless the brain-dump explicitly mentioned
  one. If you add any, max two, precisely chosen.
- DO NOT add an engagement CTA ("What do you think?", "Drop a
  comment below", "Tag someone who needs this").
- DO NOT moralize, gloss, or wrap the post in scaffolding.
- If the brain-dump references a recent application or job hunt
  context, weave it in naturally only if the context dict says to.
  Otherwise leave it out.

Return JSON ONLY, matching this schema:

{{
  "post": "the polished post, plain text",
  "char_count": 1234,
  "notes": "1-2 sentences on what you changed and why (or 'no
            changes, this lands as-is')",
  "voice_warnings": ["any lines you almost rewrote into AI-speak
                     and pulled back from, or rhythm patterns that
                     drifted corporate — short strings"]
}}

The "post" field is what the user will copy. Everything else is for
their context.
"""


# ── core polish call ────────────────────────────────────────────────


def polish_post(
    brain_dump: str,
    *,
    magical_question: str | None = None,
    context: str | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Polish a brain-dump into a postable piece.

    Returns a dict with post / char_count / notes / voice_warnings.
    Raises SirensError if the AI fails or returns malformed output.
    """
    if not brain_dump or not brain_dump.strip():
        raise SirensError("brain_dump is empty — nothing to polish.")

    if profile is None:
        from charon.profile import load_profile
        try:
            profile = load_profile()
        except Exception as e:  # noqa: BLE001
            raise SirensError(f"Profile error: {e}") from e

    voice_block = _voice_block(profile)
    system_prompt = SIRENS_SYSTEM_TEMPLATE.format(voice_block=voice_block)

    pieces: list[str] = []
    if magical_question:
        pieces.append(
            f"## Inspiration prompt (the magical question the writer was "
            f"turning over — for your context, NOT to paste into the post)\n\n"
            f"{magical_question.strip()}"
        )
    if context:
        pieces.append(f"## Context to weave in if relevant\n\n{context.strip()}")
    pieces.append(f"## Brain-dump (the actual content)\n\n{brain_dump.strip()}")

    user_prompt = (
        "\n\n".join(pieces)
        + "\n\n## Ask\n\nPolish this into a postable piece. Return ONLY the JSON "
        "described in the system prompt."
    )

    from charon.ai import AIError, query_claude_json
    try:
        result = query_claude_json(
            system_prompt,
            user_prompt,
            max_tokens=2048,
            temperature=0.6,
        )
    except AIError as e:
        raise SirensError(f"AI call failed: {e}") from e

    post = (result.get("post") or "").strip()
    if not post:
        raise SirensError(f"AI returned an empty post: {result!r}")

    return {
        "post": post,
        "char_count": int(result.get("char_count") or len(post)),
        "notes": (result.get("notes") or "").strip(),
        "voice_warnings": [
            str(v) for v in (result.get("voice_warnings") or [])
            if isinstance(v, str) and v.strip()
        ],
        "over_limit": len(post) > LINKEDIN_CHAR_LIMIT,
    }


# ── draft persistence ───────────────────────────────────────────────


def _drafts_dir() -> Path:
    home = Path.home() / ".charon" / "sirens" / "drafts"
    home.mkdir(parents=True, exist_ok=True)
    return home


def save_draft(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a draft (input + output) as a single JSON file in the
    drafts directory. Returns the saved file's metadata.

    The shape mirrors what the standalone linkedin-helper tool used in
    localStorage so future migration is painless:
    {id, name, topic, dump, savedAt, polished_post, magical_question}
    """
    drafts = _drafts_dir()
    ts = datetime.now()
    draft_id = ts.strftime("%Y%m%d-%H%M%S")
    name = payload.get("name") or f"Draft {ts.strftime('%Y-%m-%d %H:%M')}"
    record = {
        "id": draft_id,
        "name": str(name),
        "magical_question": payload.get("magical_question") or "",
        "dump": payload.get("dump") or "",
        "polished_post": payload.get("polished_post") or "",
        "savedAt": ts.isoformat(),
    }
    out_path = drafts / f"{draft_id}.json"
    out_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {"path": str(out_path), **record}


def list_drafts(limit: int = 50) -> list[dict[str, Any]]:
    drafts = _drafts_dir()
    files = sorted(drafts.glob("*.json"), reverse=True)
    out: list[dict[str, Any]] = []
    for f in files[:limit]:
        try:
            record = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        record["path"] = str(f)
        out.append(record)
    return out


__all__ = [
    "SirensError",
    "LINKEDIN_CHAR_LIMIT",
    "polish_post",
    "random_magical_question",
    "save_draft",
    "list_drafts",
    "voice_block_from_profile",
]
