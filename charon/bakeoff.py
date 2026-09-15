"""Letter bake-off: several models write the same cover letter, side by side.

Each writer goes through the normal petition path, claim check included, so
the comparison is of what she'd actually get. Output goes under
~/.charon/bakeoff/<discovery id>/<model>/ and never into the real offerings
folder, so the letter on her Ready card is untouched. Runs inside the
service because that's where the API keys are.
"""

from __future__ import annotations

import copy
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from charon.tailor import slugify


DEFAULT_BAKEOFF_DIR = "~/.charon/bakeoff"
MAX_MODELS = 6
_MODEL_RE = re.compile(r"^(openrouter:)?[a-z0-9][a-z0-9._/-]{1,80}$")

_lock = threading.Lock()
_jobs: dict[int, dict[str, Any]] = {}


class BakeoffError(Exception):
    """Raised for a bake-off request that can't start."""


def validate_models(models: Any) -> list[str]:
    if not isinstance(models, list) or not models:
        raise BakeoffError("models must be a non-empty list")
    if len(models) > MAX_MODELS:
        raise BakeoffError(f"at most {MAX_MODELS} models per bake-off")
    clean: list[str] = []
    for m in models:
        if not isinstance(m, str) or not _MODEL_RE.match(m.strip()):
            raise BakeoffError(f"not a model id: {m!r}")
        if m.strip() not in clean:
            clean.append(m.strip())
    return clean


def bakeoff_root(discovery_id: int) -> Path:
    return Path(DEFAULT_BAKEOFF_DIR).expanduser() / str(int(discovery_id))


def _write_one(discovery: dict[str, Any], profile: dict[str, Any], model: str) -> dict[str, Any]:
    from charon.letter import petition_discovery

    prof = copy.deepcopy(profile)
    forge = prof.setdefault("forge", {})
    forge["offerings_dir"] = str(bakeoff_root(discovery["id"]) / slugify(model, max_len=80))

    started = time.monotonic()
    try:
        result = petition_discovery(discovery, profile=prof, model_override=model, force=True)
    except Exception as e:  # noqa: BLE001 — one writer failing shouldn't sink the rest
        result = {"error": f"{type(e).__name__}: {e}"}
    result["model"] = model
    result["seconds"] = round(time.monotonic() - started, 1)
    return result


def run_bakeoff(discovery_id: int, models: list[str]) -> dict[str, Any]:
    from charon.db import get_discovery
    from charon.profile import load_profile

    discovery = get_discovery(discovery_id)
    if discovery is None:
        raise BakeoffError(f"No discovery with id {discovery_id}.")
    # Petition only writes for ready rows; a bake-off on an applied or
    # archived row is still a fair test. This copy is never saved.
    discovery = dict(discovery, screened_status="ready")
    profile = load_profile()

    with ThreadPoolExecutor(max_workers=len(models)) as pool:
        results = list(pool.map(lambda m: _write_one(discovery, profile, m), models))

    summary = {
        "discovery_id": discovery_id,
        "company": discovery.get("company"),
        "role": discovery.get("role"),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }
    root = bakeoff_root(discovery_id)
    root.mkdir(parents=True, exist_ok=True)
    (root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _worker(discovery_id: int, models: list[str]) -> None:
    summary: dict[str, Any] | None = None
    error: str | None = None
    try:
        summary = run_bakeoff(discovery_id, models)
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"
    with _lock:
        _jobs[discovery_id].update({
            "running": False,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error": error,
            "summary": summary,
        })


def start_bakeoff(discovery_id: int, models: Any) -> dict[str, Any]:
    clean = validate_models(models)
    with _lock:
        if (_jobs.get(discovery_id) or {}).get("running"):
            raise BakeoffError(f"A bake-off for #{discovery_id} is already running.")
        _jobs[discovery_id] = {
            "running": True,
            "models": clean,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "error": None,
            "summary": None,
        }
    threading.Thread(target=_worker, args=(discovery_id, clean), daemon=True).start()
    return job_snapshot(discovery_id)


def job_snapshot(discovery_id: int) -> dict[str, Any]:
    with _lock:
        return copy.deepcopy(_jobs.get(discovery_id) or {"running": False, "summary": None})


__all__ = ["BakeoffError", "bakeoff_root", "job_snapshot", "run_bakeoff", "start_bakeoff", "validate_models"]
