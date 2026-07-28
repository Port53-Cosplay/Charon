"""Tests for the concurrent cull orchestrator (cull_batch)."""

import threading
import time

from charon import cull as cull_mod


def test_resolve_concurrency(monkeypatch):
    monkeypatch.delenv("CHARON_CULL_CONCURRENCY", raising=False)
    assert cull_mod._resolve_concurrency(None) == cull_mod.DEFAULT_CULL_CONCURRENCY
    assert cull_mod._resolve_concurrency(3) == 3
    assert cull_mod._resolve_concurrency(0) == 1  # floor at 1
    monkeypatch.setenv("CHARON_CULL_CONCURRENCY", "12")
    assert cull_mod._resolve_concurrency(None) == 12
    assert cull_mod._resolve_concurrency(5) == 5  # explicit arg wins over env


def test_cull_batch_runs_in_parallel(monkeypatch):
    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_cull_one(row, profile):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return {"decision": "pass", "reason": "ok", "confidence": "low"}

    applied = []
    monkeypatch.setattr(cull_mod, "cull_one", fake_cull_one)
    monkeypatch.setattr(
        cull_mod, "apply_cull_decision",
        lambda did, dec: (applied.append(did), "passed")[1],
    )

    rows = [{"id": i} for i in range(8)]
    results = []
    cull_mod.cull_batch(
        rows, {}, concurrency=4,
        on_result=lambda r, o, e: results.append((r["id"], o, e)),
    )

    assert len(applied) == 8               # every row's decision was applied
    assert len(results) == 8               # callback fired once per row
    assert all(e is None for _, o, e in results)
    assert all(o == "passed" for _, o, e in results)
    assert max_active >= 2                  # genuinely overlapped, not sequential


def test_cull_batch_isolates_errors(monkeypatch):
    def fake_cull_one(row, profile):
        if row["id"] == 2:
            raise cull_mod.CullError("boom")
        return {"decision": "refuse", "reason": "x", "confidence": "high"}

    monkeypatch.setattr(cull_mod, "cull_one", fake_cull_one)
    monkeypatch.setattr(cull_mod, "apply_cull_decision", lambda did, dec: "refused")

    outcomes, errors = {}, {}

    def on_result(row, outcome, error):
        outcomes[row["id"]] = outcome
        errors[row["id"]] = error

    cull_mod.cull_batch([{"id": i} for i in range(4)], {}, concurrency=4, on_result=on_result)

    assert errors[2] is not None and outcomes[2] is None      # the failing row
    assert outcomes[0] == "refused" and errors[0] is None     # the others succeed
    assert sum(1 for e in errors.values() if e is not None) == 1


def test_cull_batch_empty_is_a_noop(monkeypatch):
    calls = []
    monkeypatch.setattr(cull_mod, "cull_one", lambda r, p: calls.append("cull"))
    cull_mod.cull_batch([], {}, on_result=lambda *a: calls.append("cb"))
    assert calls == []
