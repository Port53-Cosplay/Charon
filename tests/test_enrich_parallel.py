"""Tests for the parallel enrich_batch (thread-pooled row enrichment)."""

import threading
import time

from charon import enrich as enrich_mod


def _fake_targets(n):
    return [{"id": i, "company": f"co{i}", "role": f"role{i}", "url": f"https://x/{i}"}
            for i in range(n)]


def test_resolve_enrich_workers(monkeypatch):
    monkeypatch.delenv("CHARON_ENRICH_WORKERS", raising=False)
    assert enrich_mod._resolve_workers(None) == enrich_mod.DEFAULT_ENRICH_WORKERS
    assert enrich_mod._resolve_workers(2) == 2
    assert enrich_mod._resolve_workers(0) == 1
    assert enrich_mod._resolve_workers(99) == enrich_mod.MAX_ENRICH_WORKERS
    monkeypatch.setenv("CHARON_ENRICH_WORKERS", "6")
    assert enrich_mod._resolve_workers(None) == 6


def test_enrich_batch_runs_in_parallel(monkeypatch):
    active = 0
    max_active = 0
    writes = []
    lock = threading.Lock()

    def fake_enrich_discovery(discovery, *, profile=None, force=False):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return {"tier": "jsonld", "full_description": "desc", "source_url": discovery["url"]}

    monkeypatch.setattr(enrich_mod, "enrich_discovery", fake_enrich_discovery)
    monkeypatch.setattr(
        enrich_mod, "update_discovery_enrichment",
        lambda did, tier, desc: writes.append(did),
    )
    monkeypatch.setattr(
        enrich_mod, "get_unenriched_discoveries", lambda **kw: _fake_targets(8)
    )

    progressed = []
    results = enrich_mod.enrich_batch(
        workers=4, on_progress=lambda r: progressed.append(r)
    )

    assert len(results) == 8
    assert len(progressed) == 8
    assert sorted(writes) == list(range(8))   # DB write exactly once per row
    assert max_active >= 2


def test_enrich_batch_downgrades_raising_rows(monkeypatch):
    writes = []

    def fake_enrich_discovery(discovery, *, profile=None, force=False):
        if discovery["id"] == 1:
            raise RuntimeError("fetch exploded")
        return {"tier": "jsonld", "full_description": "desc", "source_url": discovery["url"]}

    monkeypatch.setattr(enrich_mod, "enrich_discovery", fake_enrich_discovery)
    monkeypatch.setattr(
        enrich_mod, "update_discovery_enrichment",
        lambda did, tier, desc: writes.append((did, tier)),
    )
    monkeypatch.setattr(
        enrich_mod, "get_unenriched_discoveries", lambda **kw: _fake_targets(3)
    )

    results = enrich_mod.enrich_batch(workers=4)

    assert len(results) == 3                          # batch completed
    by_id = {r["discovery_id"]: r for r in results}
    assert by_id[1]["tier"] == "failed"
    assert "fetch exploded" in by_id[1]["error"]
    assert dict(writes)[1] == "failed"                # failure still written
    assert by_id[0]["tier"] == "jsonld" and by_id[2]["tier"] == "jsonld"


def test_enrich_batch_workers1_is_sequential(monkeypatch):
    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_enrich_discovery(discovery, *, profile=None, force=False):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return {"tier": "skipped", "full_description": "d", "source_url": None}

    monkeypatch.setattr(enrich_mod, "enrich_discovery", fake_enrich_discovery)
    monkeypatch.setattr(enrich_mod, "update_discovery_enrichment", lambda *a: None)
    monkeypatch.setattr(
        enrich_mod, "get_unenriched_discoveries", lambda **kw: _fake_targets(4)
    )

    results = enrich_mod.enrich_batch(workers=1, rate_limit_seconds=0)

    assert max_active == 1
    assert [r["discovery_id"] for r in results] == [0, 1, 2, 3]
