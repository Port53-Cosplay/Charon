#!/usr/bin/env python3
"""Ingest paste-judge results into the discoveries DB.

Reads JSON from stdin in the shape produced by Charon's paste-judge
prompt, validates it, and writes scores + judged_at + screened_status
for each discovery. Computes combined_score from the profile's
judge.weights and applies the same ready/rejected gating that the
in-process judge uses (alignment_floor + threshold + dealbreaker
count).

Output: one line per discovery on stdout ("OK #1234 ready 75.5" or
"ERR #1234 reason..."), then a summary line. Exit 0 on full success,
1 on any per-row failure (still ingests the OK ones), 2 on input
errors (no rows written).

Usage:
    cat results.json | charon-ingest-judge

Or via SSH from anywhere with bastion access:
    ssh root@ops "ssh 192.168.14.149 \\
        sudo -u charon /home/charon/venv/bin/python \\
        /opt/charon-src/scripts/judge_ingest.py" < results.json
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            print("ERR empty stdin — nothing to ingest", file=sys.stderr)
            return 2
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"ERR JSON parse failed: {e}", file=sys.stderr)
        return 2

    judgements = payload.get("judgements") if isinstance(payload, dict) else payload
    if not isinstance(judgements, list):
        print("ERR payload must have a 'judgements' list", file=sys.stderr)
        return 2
    if not judgements:
        print("ERR judgements list is empty", file=sys.stderr)
        return 2

    # Lazy-import after stdin validation so the help/error path is fast
    from charon.db import (
        get_connection,
        get_discovery,
    )
    from charon.profile import load_profile
    from charon.screen import _decide_status, _judge_config, compute_combined_weighted

    try:
        profile = load_profile()
    except Exception as e:  # noqa: BLE001
        print(f"ERR load_profile failed: {e}", file=sys.stderr)
        return 2

    cfg = _judge_config(profile)
    threshold = cfg["ready_threshold"]
    floor = cfg["alignment_floor"]
    weights = cfg["weights"]

    now_iso = datetime.now(timezone.utc).isoformat()
    ok_count = 0
    fail_count = 0
    ready_count = 0
    rejected_count = 0

    conn = get_connection()
    try:
        for j in judgements:
            try:
                disc_id = int(j["discovery_id"])
                ghost = float(j["ghost_score"])
                redflag = float(j["redflag_score"])
                alignment = float(j["alignment_score"])
                rm = float(j["resume_match_score"])
            except (KeyError, TypeError, ValueError) as e:
                print(f"ERR malformed entry: {e}  raw={j!r}", file=sys.stderr)
                fail_count += 1
                continue

            existing = get_discovery(disc_id)
            if existing is None:
                print(f"ERR #{disc_id} no such discovery", file=sys.stderr)
                fail_count += 1
                continue

            # 5th dimension is deterministic; the paste-judge LLM doesn't
            # produce it. Compute it here from the existing discovery row
            # (ats, tier, full_description) so the combined score reflects
            # the same 5-component formula as in-process judge.
            from charon.monoculture import score_monoculture
            mono_detail = score_monoculture(existing, profile)
            mono_score = (
                float(mono_detail["monoculture_score"]) if mono_detail else None
            )

            combined = compute_combined_weighted(
                ghost=ghost,
                redflag=redflag,
                alignment=alignment,
                resume_match=rm,
                weights=weights,
                monoculture=mono_score,
            )

            # Dealbreakers count from the structured detail block
            detail_block = j.get("judgement_detail") or {}
            if isinstance(detail_block, dict) and mono_detail is not None:
                detail_block["screening_monoculture"] = mono_detail
            redflag_block = (
                detail_block.get("redflags") if isinstance(detail_block, dict) else {}
            ) or {}
            dealbreakers_raw = redflag_block.get("dealbreakers_found") or []
            dealbreakers_count = len(dealbreakers_raw) if isinstance(dealbreakers_raw, list) else 0

            status, reason = _decide_status(
                threshold=threshold,
                floor=floor,
                ghost=ghost,
                redflag=redflag,
                alignment=alignment,
                resume_match=rm,
                combined=combined,
                dealbreakers_count=dealbreakers_count,
                monoculture=mono_score,
            )

            # Prefer the model's prose reason when status was set by
            # the gate above as just a numeric explanation
            model_reason = (j.get("judgement_reason") or "").strip()
            final_reason = reason
            if model_reason and status == "ready":
                final_reason = model_reason

            detail_json = json.dumps(detail_block) if detail_block else None

            try:
                conn.execute(
                    "UPDATE discoveries SET "
                    "  ghost_score = ?, redflag_score = ?, alignment_score = ?, "
                    "  resume_match_score = ?, combined_score = ?, "
                    "  monoculture_score = ?, "
                    "  screened_status = ?, judgement_reason = ?, "
                    "  judgement_detail = ?, judged_at = ? "
                    "WHERE id = ?",
                    (
                        ghost, redflag, alignment, rm, combined,
                        mono_score,
                        status, final_reason, detail_json, now_iso,
                        disc_id,
                    ),
                )
                print(f"OK #{disc_id} {status} {combined:.1f}")
                ok_count += 1
                if status == "ready":
                    ready_count += 1
                else:
                    rejected_count += 1
            except Exception as e:  # noqa: BLE001
                print(f"ERR #{disc_id} DB write: {e}", file=sys.stderr)
                fail_count += 1
        conn.commit()
    finally:
        conn.close()

    print(
        f"\nSUMMARY ingested={ok_count} (ready={ready_count}, "
        f"rejected={rejected_count}) failed={fail_count}"
    )
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
