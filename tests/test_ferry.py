"""Tests for the ferry — the chained gather → cull → enrich → (gate) → judge job."""

import time

import pytest

import charon.cull
import charon.db
import charon.enrich
import charon.gather
import charon.profile
import charon.screen
from charon import dashboard


@pytest.fixture(autouse=True)
def _reset_pipeline_state():
    """Fresh ferry + legacy job state for every test."""
    dashboard._ferry_state.clear()
    dashboard._ferry_state.update(dashboard._fresh_ferry_state())
    for state in (
        dashboard._gather_state,
        dashboard._cull_state,
        dashboard._enrich_state,
        dashboard._judge_state,
    ):
        state["running"] = False
    yield
    dashboard._ferry_state.clear()
    dashboard._ferry_state.update(dashboard._fresh_ferry_state())


def _mock_chain_stages(monkeypatch, *, judgeable=5):
    """Stub every stage the chain worker calls."""
    monkeypatch.setattr(charon.profile, "load_profile", lambda: {})
    monkeypatch.setattr(
        charon.gather, "load_registry", lambda: {"greenhouse": [{"slug": "a", "name": "A"}]}
    )
    monkeypatch.setattr(
        charon.gather, "list_employers", lambda reg, ats=None: [("greenhouse", {"slug": "a"})]
    )

    def fake_gather(on_progress=None, **kw):
        if on_progress:
            on_progress({"new": 3, "dupes": 1, "error": None})
        return []

    monkeypatch.setattr(charon.gather, "gather_registry", fake_gather)
    monkeypatch.setattr(
        charon.db, "get_unculled_discoveries", lambda **kw: [{"id": 1}, {"id": 2}]
    )

    def fake_cull(rows, profile, *, on_result=None, **kw):
        for row in rows:
            if on_result:
                on_result(row, "passed", None)

    monkeypatch.setattr(charon.cull, "cull_batch", fake_cull)
    monkeypatch.setattr(
        charon.db, "get_enrichable_discoveries", lambda **kw: [{"id": 1}]
    )

    def fake_enrich(on_progress=None, **kw):
        if on_progress:
            on_progress({"tier": "jsonld"})
        return []

    monkeypatch.setattr(charon.enrich, "enrich_batch", fake_enrich)
    monkeypatch.setattr(dashboard, "_count_judgeable", lambda: judgeable)


def _run_chain_synchronously():
    """Seed the state _start_ferry would and run the chain worker inline."""
    with dashboard._ferry_lock:
        dashboard._ferry_state["running"] = True
        dashboard._ferry_state["phase"] = "gather"
    dashboard._ferry_worker()
    return dashboard._ferry_status_snapshot()


def test_ferry_chain_pauses_at_judge_gate(monkeypatch):
    _mock_chain_stages(monkeypatch, judgeable=5)
    snap = _run_chain_synchronously()

    assert snap["phase"] == "awaiting_judge"
    assert snap["running"] is False
    assert snap["judgeable_count"] == 5
    assert snap["cost_low"] == pytest.approx(0.10)
    assert snap["cost_high"] == pytest.approx(0.25)
    assert snap["est_minutes_low"] >= 1
    # Stage counters flowed through
    assert snap["gather"]["total_new"] == 3
    assert snap["cull"]["processed"] == 2
    assert snap["cull"]["passed"] == 2
    assert snap["enrich"]["recovered"] == 1


def test_ferry_chain_zero_judgeable_goes_done(monkeypatch):
    _mock_chain_stages(monkeypatch, judgeable=0)
    snap = _run_chain_synchronously()
    assert snap["phase"] == "done"
    assert snap["running"] is False


def test_ferry_stage_error_runs_aground(monkeypatch):
    _mock_chain_stages(monkeypatch)

    def exploding_cull(rows, profile, **kw):
        raise RuntimeError("deepseek down")

    monkeypatch.setattr(charon.cull, "cull_batch", exploding_cull)
    snap = _run_chain_synchronously()

    assert snap["phase"] == "error"
    assert "deepseek down" in snap["error"]
    assert snap["running"] is False


def test_ferry_refuses_while_legacy_job_runs():
    dashboard._cull_state["running"] = True
    with pytest.raises(dashboard.DashboardError, match="cull"):
        dashboard._start_ferry()


def test_legacy_jobs_refuse_while_ferry_runs():
    dashboard._ferry_state["running"] = True
    with pytest.raises(dashboard.DashboardError, match="ferry"):
        dashboard._start_cull_batch(10)
    with pytest.raises(dashboard.DashboardError, match="ferry"):
        dashboard._start_enrich_batch(10)
    with pytest.raises(dashboard.DashboardError, match="ferry"):
        dashboard._start_gather()
    with pytest.raises(dashboard.DashboardError, match="ferry"):
        dashboard._start_judge_batch(10)


def test_ferry_judge_requires_the_gate(monkeypatch):
    monkeypatch.setattr(dashboard, "_count_judgeable", lambda: 3)
    with pytest.raises(dashboard.DashboardError, match="judge gate"):
        dashboard._start_ferry_judge()      # phase is 'idle'


def test_ferry_judge_leg_runs_to_done(monkeypatch):
    monkeypatch.setattr(dashboard, "_count_judgeable", lambda: 2)
    monkeypatch.setattr(charon.profile, "load_profile", lambda: {})

    def fake_judge_batch(*, profile, on_progress=None, **kw):
        for i in (1, 2):
            if on_progress:
                on_progress({"screened_status": "ready" if i == 1 else "rejected"})
        return []

    monkeypatch.setattr(charon.screen, "judge_batch", fake_judge_batch)

    with dashboard._ferry_lock:
        dashboard._ferry_state["phase"] = "awaiting_judge"
    dashboard._start_ferry_judge()

    deadline = time.time() + 5
    while time.time() < deadline:
        snap = dashboard._ferry_status_snapshot()
        if not snap["running"]:
            break
        time.sleep(0.02)

    assert snap["phase"] == "done"
    assert snap["judge"]["limit"] == 2
    assert snap["judge"]["processed"] == 2
    assert snap["judge"]["ready_added"] == 1
    assert snap["judge"]["refused_added"] == 1


def test_stats_cullable_counts_only_fresh_rows():
    from charon.db import add_discovery, get_connection

    ids = []
    for i in range(4):
        ids.append(add_discovery(
            ats="greenhouse", slug=f"s{i}", company=f"C{i}", role="Analyst",
            url=f"https://x/{i}", dedupe_hash=f"h{i}",
        ))

    conn = get_connection()
    try:
        # ids[1]: already culled; ids[2]: already judged; ids[3]: rejected
        conn.execute("UPDATE discoveries SET culled_at = '2026-01-01' WHERE id = ?", (ids[1],))
        conn.execute("UPDATE discoveries SET judged_at = '2026-01-01' WHERE id = ?", (ids[2],))
        conn.execute("UPDATE discoveries SET screened_status = 'rejected' WHERE id = ?", (ids[3],))
        conn.commit()
    finally:
        conn.close()

    assert dashboard._stats()["cullable"] == 1
