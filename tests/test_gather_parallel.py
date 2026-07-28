"""Tests for the parallel gather_registry (thread-pooled employer fetches)."""

import threading
import time

from charon import gather as gather_mod


def _fake_registry(n, ats="greenhouse"):
    return {ats: [{"slug": f"emp{i}", "name": f"Employer {i}"} for i in range(n)]}


def test_resolve_gather_workers(monkeypatch):
    monkeypatch.delenv("CHARON_GATHER_WORKERS", raising=False)
    assert gather_mod._resolve_workers(None) == gather_mod.DEFAULT_GATHER_WORKERS
    assert gather_mod._resolve_workers(2) == 2
    assert gather_mod._resolve_workers(0) == 1
    assert gather_mod._resolve_workers(99) == gather_mod.MAX_GATHER_WORKERS
    monkeypatch.setenv("CHARON_GATHER_WORKERS", "6")
    assert gather_mod._resolve_workers(None) == 6


def test_gather_registry_runs_in_parallel(monkeypatch):
    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_gather_employer(ats, entry, *, dry_run=False, skip_companies=()):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return {"ats": ats, "slug": entry["slug"], "name": entry["name"],
                "fetched": 1, "new": 1, "dupes": 0, "skipped": 0, "error": None}

    monkeypatch.setattr(gather_mod, "load_registry", lambda: _fake_registry(8))
    monkeypatch.setattr(gather_mod, "get_applied_companies", lambda: [])
    monkeypatch.setattr(gather_mod, "gather_employer", fake_gather_employer)

    progressed = []
    summaries = gather_mod.gather_registry(
        workers=4, on_progress=lambda s: progressed.append(s)
    )

    assert len(summaries) == 8
    assert len(progressed) == 8
    assert max_active >= 2


def test_gather_registry_unknown_ats_skips_pool(monkeypatch):
    calls = []

    def fake_gather_employer(ats, entry, **kw):
        calls.append(entry["slug"])
        return {"ats": ats, "slug": entry["slug"], "name": entry["name"],
                "fetched": 0, "new": 0, "dupes": 0, "skipped": 0, "error": None}

    registry = _fake_registry(2)
    registry["mystery_ats"] = [{"slug": "weird", "name": "Weird Co"}]
    monkeypatch.setattr(gather_mod, "load_registry", lambda: registry)
    monkeypatch.setattr(gather_mod, "get_applied_companies", lambda: [])
    monkeypatch.setattr(gather_mod, "gather_employer", fake_gather_employer)

    summaries = gather_mod.gather_registry(workers=4)

    assert len(summaries) == 3
    weird = next(s for s in summaries if s["slug"] == "weird")
    assert "not yet implemented" in weird["error"]
    assert "weird" not in calls               # never hit the (fake) adapter


def test_gather_registry_isolates_worker_exceptions(monkeypatch):
    def fake_gather_employer(ats, entry, **kw):
        if entry["slug"] == "emp1":
            raise RuntimeError("db exploded")
        return {"ats": ats, "slug": entry["slug"], "name": entry["name"],
                "fetched": 1, "new": 1, "dupes": 0, "skipped": 0, "error": None}

    monkeypatch.setattr(gather_mod, "load_registry", lambda: _fake_registry(3))
    monkeypatch.setattr(gather_mod, "get_applied_companies", lambda: [])
    monkeypatch.setattr(gather_mod, "gather_employer", fake_gather_employer)

    summaries = gather_mod.gather_registry(workers=4)

    assert len(summaries) == 3
    bad = next(s for s in summaries if s["slug"] == "emp1")
    assert "db exploded" in bad["error"]
    assert sum(1 for s in summaries if s["error"]) == 1


def test_gather_registry_workers1_preserves_order(monkeypatch):
    order = []

    def fake_gather_employer(ats, entry, **kw):
        order.append(entry["slug"])
        return {"ats": ats, "slug": entry["slug"], "name": entry["name"],
                "fetched": 0, "new": 0, "dupes": 0, "skipped": 0, "error": None}

    monkeypatch.setattr(gather_mod, "load_registry", lambda: _fake_registry(4))
    monkeypatch.setattr(gather_mod, "get_applied_companies", lambda: [])
    monkeypatch.setattr(gather_mod, "gather_employer", fake_gather_employer)

    summaries = gather_mod.gather_registry(workers=1, rate_limit_seconds=0)

    assert order == ["emp0", "emp1", "emp2", "emp3"]
    assert [s["slug"] for s in summaries] == order
