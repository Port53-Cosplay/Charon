"""Tests for the parallel judge_batch (thread-pooled judge_one_id calls)."""

import threading
import time

from charon import screen as screen_mod


def _fake_targets(n):
    return [{"id": i, "company": f"co{i}", "role": f"role{i}"} for i in range(n)]


def test_resolve_judge_workers(monkeypatch):
    monkeypatch.delenv("CHARON_JUDGE_WORKERS", raising=False)
    assert screen_mod._resolve_judge_workers(None) == screen_mod.DEFAULT_JUDGE_WORKERS
    assert screen_mod._resolve_judge_workers(3) == 3
    assert screen_mod._resolve_judge_workers(0) == 1  # floor at 1
    assert screen_mod._resolve_judge_workers(99) == screen_mod.MAX_JUDGE_WORKERS  # cap
    monkeypatch.setenv("CHARON_JUDGE_WORKERS", "6")
    assert screen_mod._resolve_judge_workers(None) == 6
    assert screen_mod._resolve_judge_workers(2) == 2  # explicit arg wins over env
    monkeypatch.setenv("CHARON_JUDGE_WORKERS", "50")
    assert screen_mod._resolve_judge_workers(None) == screen_mod.MAX_JUDGE_WORKERS


def test_judge_batch_runs_in_parallel(monkeypatch):
    active = 0
    max_active = 0
    resume_loads = 0
    lock = threading.Lock()

    def fake_judge_one_id(did, *, profile, threshold, rejudge, resume_text):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return {"discovery_id": did, "screened_status": "ready"}

    def fake_load_resume(profile):
        nonlocal resume_loads
        resume_loads += 1
        return "resume text"

    monkeypatch.setattr(screen_mod, "judge_one_id", fake_judge_one_id)
    monkeypatch.setattr(screen_mod, "_maybe_load_resume", fake_load_resume)
    monkeypatch.setattr(
        screen_mod, "get_unjudged_discoveries", lambda **kw: _fake_targets(8)
    )

    progressed = []
    results = screen_mod.judge_batch(
        profile={}, workers=4, on_progress=lambda r: progressed.append(r)
    )

    assert len(results) == 8
    assert len(progressed) == 8
    assert resume_loads == 1                # loaded once, not per row
    assert max_active >= 2                  # genuinely overlapped


def test_judge_batch_isolates_errors(monkeypatch):
    def fake_judge_one_id(did, **kw):
        if did == 2:
            raise screen_mod.JudgeError("boom")
        return {"discovery_id": did, "screened_status": "ready"}

    monkeypatch.setattr(screen_mod, "judge_one_id", fake_judge_one_id)
    monkeypatch.setattr(screen_mod, "_maybe_load_resume", lambda p: None)
    monkeypatch.setattr(
        screen_mod, "get_unjudged_discoveries", lambda **kw: _fake_targets(4)
    )

    results = screen_mod.judge_batch(profile={}, workers=4)

    assert len(results) == 4
    by_id = {r["discovery_id"]: r for r in results}
    assert by_id[2].get("error") == "boom"
    assert by_id[2]["screened_status"] == "rejected"
    assert all("error" not in by_id[i] for i in (0, 1, 3))


def test_judge_batch_workers1_is_sequential(monkeypatch):
    active = 0
    max_active = 0
    order = []
    lock = threading.Lock()

    def fake_judge_one_id(did, **kw):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.01)
        order.append(did)
        with lock:
            active -= 1
        return {"discovery_id": did, "screened_status": "ready"}

    monkeypatch.setattr(screen_mod, "judge_one_id", fake_judge_one_id)
    monkeypatch.setattr(screen_mod, "_maybe_load_resume", lambda p: None)
    monkeypatch.setattr(
        screen_mod, "get_unjudged_discoveries", lambda **kw: _fake_targets(4)
    )

    results = screen_mod.judge_batch(profile={}, workers=1)

    assert max_active == 1
    assert order == [0, 1, 2, 3]            # sequential path preserves order
    assert [r["discovery_id"] for r in results] == [0, 1, 2, 3]


def _ai_error_result(did):
    return {"discovery_id": did, "screened_status": "rejected",
            "judgement_reason": "AI error: credit balance too low", "error": "boom"}


def test_breaker_stops_sequential_batch_on_consecutive_ai_errors(monkeypatch):
    calls = []

    def fake_judge_one_id(did, **kw):
        calls.append(did)
        return _ai_error_result(did)

    monkeypatch.setattr(screen_mod, "judge_one_id", fake_judge_one_id)
    monkeypatch.setattr(screen_mod, "_maybe_load_resume", lambda p: None)
    monkeypatch.setattr(
        screen_mod, "get_unjudged_discoveries", lambda **kw: _fake_targets(50)
    )

    results = screen_mod.judge_batch(profile={}, workers=1)

    assert len(calls) == screen_mod.JUDGE_BREAKER_THRESHOLD   # stopped at 5, not 50
    assert len(results) == screen_mod.JUDGE_BREAKER_THRESHOLD


def test_breaker_stops_parallel_batch_early(monkeypatch):
    import time as time_mod

    def fake_judge_one_id(did, **kw):
        time_mod.sleep(0.01)
        return _ai_error_result(did)

    monkeypatch.setattr(screen_mod, "judge_one_id", fake_judge_one_id)
    monkeypatch.setattr(screen_mod, "_maybe_load_resume", lambda p: None)
    monkeypatch.setattr(
        screen_mod, "get_unjudged_discoveries", lambda **kw: _fake_targets(60)
    )

    results = screen_mod.judge_batch(profile={}, workers=4)

    # In-flight rows may land after the trip, but the queue must not drain.
    assert len(results) < 60


def test_breaker_resets_on_success(monkeypatch):
    # Alternating error/success never trips the CONSECUTIVE breaker.
    def fake_judge_one_id(did, **kw):
        if did % 2 == 0:
            return _ai_error_result(did)
        return {"discovery_id": did, "screened_status": "ready"}

    monkeypatch.setattr(screen_mod, "judge_one_id", fake_judge_one_id)
    monkeypatch.setattr(screen_mod, "_maybe_load_resume", lambda p: None)
    monkeypatch.setattr(
        screen_mod, "get_unjudged_discoveries", lambda **kw: _fake_targets(20)
    )

    results = screen_mod.judge_batch(profile={}, workers=1)
    assert len(results) == 20
