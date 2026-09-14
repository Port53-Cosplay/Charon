"""Dossiers on the Ready view.

The research engine shipped as `charon dossier` in Phase 3 and never got a
button. The Ready card now shows the newest dossier for a posting's company,
builds one on a background thread (web research outlasts Cloudflare's request
limit), and flags anything older than six months.
"""

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from charon import dashboard
from charon.db import add_discovery, get_connection, save_history, update_discovery_judgement


def _dossier_result(company="GuidePoint Security", score=76.1):
    dims = {
        name: {"score": 70.0, "evidence": [f"{name} evidence"], "assessment": f"{name} ok"}
        for name in (
            "security_culture", "people_treatment", "leadership_transparency",
            "work_life_balance", "compensation", "financial_health",
        )
    }
    return {
        "company": company,
        "summary": "A security services firm.",
        "overall_score": 70.0,
        "dimensions": dims,
        "verdict": "Reasonable place to work.",
        "weighted_score": score,
        "contacts": {"contacts": [{"name": "Someone", "linkedin_url": "https://linkedin.com/in/x"}]},
    }


def _save_dossier(company, *, days_ago, score=76.1):
    rid = save_history("dossier", "company", company, score, _dossier_result(company, score), company=company)
    stamp = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    conn = get_connection()
    try:
        conn.execute("UPDATE history SET timestamp = ? WHERE id = ?", (stamp, rid))
        conn.commit()
    finally:
        conn.close()
    return rid


def _seed_ready(company="GuidePoint Security", dedupe_hash="dd-ready"):
    rid = add_discovery(
        ats="lever", slug="guidepoint", company=company,
        role="SecOps Engineer", url=f"https://example.com/{dedupe_hash}",
        dedupe_hash=dedupe_hash, location="Remote", description="x" * 900,
        posted_at=None, tier="tier_2", category="security_product_general",
    )
    update_discovery_judgement(
        rid, ghost_score=18, redflag_score=22, alignment_score=78,
        combined_score=73.1, screened_status="ready",
        judgement_reason="combined 73.1 >= 70",
    )
    return rid


class TestIndex:
    def test_newest_dossier_per_company_wins(self):
        old = _save_dossier("GuidePoint Security", days_ago=120, score=60.0)
        new = _save_dossier("GuidePoint Security", days_ago=5, score=76.1)
        entry = dashboard._dossier_index()["guidepoint security"]
        assert entry["id"] == new != old
        assert entry["score"] == 76.1

    def test_company_names_match_loosely(self):
        _save_dossier("  GuidePoint   Security ", days_ago=5)
        assert "guidepoint security" in dashboard._dossier_index()

    def test_six_months_is_stale(self):
        _save_dossier("Old Co", days_ago=200)
        _save_dossier("Fresh Co", days_ago=120)
        index = dashboard._dossier_index()
        assert index["old co"]["stale"] is True
        assert index["fresh co"]["stale"] is False

    def test_ready_rows_carry_their_company_dossier(self):
        _seed_ready()
        _save_dossier("GuidePoint Security", days_ago=129)
        row = dashboard._ready_discoveries()[0]
        assert row["dossier"]["id"]
        assert row["dossier"]["stale"] is False
        assert row["dossier_building"] is False

    def test_ready_row_without_a_dossier(self):
        _seed_ready(company="Moxfive", dedupe_hash="dd-none")
        assert dashboard._ready_discoveries()[0]["dossier"] is None


class TestPayload:
    def test_contacts_are_left_out(self):
        rid = _save_dossier("GuidePoint Security", days_ago=5)
        payload = dashboard._dossier_payload(rid)
        assert "contacts" not in payload
        assert payload["weighted_score"] == 76.1
        assert payload["dimensions"]["security_culture"]["score"] == 70.0
        assert payload["is_latest"] is True

    def test_unknown_id(self):
        with pytest.raises(dashboard.DashboardError):
            dashboard._dossier_payload(99999)


class TestBuild:
    def _wait(self, company, timeout=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not dashboard._dossier_job_running(company):
                return
            time.sleep(0.02)
        raise AssertionError("dossier build did not finish")

    def test_build_saves_history_without_contacts(self, monkeypatch):
        import charon.dossier as dossier_mod
        import charon.profile as profile_mod

        calls = {}

        def fake_analyze(company, profile, role_title=None, include_contacts=True):
            calls["include_contacts"] = include_contacts
            calls["role"] = role_title
            result = _dossier_result(company)
            result.pop("contacts")
            return result

        monkeypatch.setattr(dossier_mod, "analyze_dossier", fake_analyze)
        monkeypatch.setattr(dossier_mod, "save_dossier_markdown", lambda r, p: None)
        monkeypatch.setattr(profile_mod, "load_profile", lambda: {"dossier": {}})

        rid = _seed_ready()
        snap = dashboard._start_dossier_build(rid)
        assert snap["running"] is True
        self._wait("GuidePoint Security")

        job = dashboard._dossier_job_snapshot("GuidePoint Security")
        assert job["error"] is None
        assert job["dossier"]["id"] == job["history_id"]
        assert calls == {"include_contacts": False, "role": "SecOps Engineer"}

    def test_a_second_build_for_the_same_company_is_refused(self, monkeypatch):
        import threading
        import charon.dossier as dossier_mod
        import charon.profile as profile_mod

        release = threading.Event()

        def slow_analyze(company, profile, role_title=None, include_contacts=True):
            release.wait(5)
            return _dossier_result(company)

        monkeypatch.setattr(dossier_mod, "analyze_dossier", slow_analyze)
        monkeypatch.setattr(dossier_mod, "save_dossier_markdown", lambda r, p: None)
        monkeypatch.setattr(profile_mod, "load_profile", lambda: {"dossier": {}})

        rid = _seed_ready()
        dashboard._start_dossier_build(rid)
        try:
            with pytest.raises(dashboard.DashboardError, match="already being built"):
                dashboard._start_dossier_build(rid)
        finally:
            release.set()
            self._wait("GuidePoint Security")

    def test_a_failed_build_reports_the_error(self, monkeypatch):
        import charon.dossier as dossier_mod
        import charon.profile as profile_mod
        from charon.ai import AIError

        def broken(company, profile, role_title=None, include_contacts=True):
            raise AIError("Rate limited.")

        monkeypatch.setattr(dossier_mod, "analyze_dossier", broken)
        monkeypatch.setattr(profile_mod, "load_profile", lambda: {"dossier": {}})

        rid = _seed_ready(company="Sophos", dedupe_hash="dd-fail")
        dashboard._start_dossier_build(rid)
        self._wait("Sophos")
        job = dashboard._dossier_job_snapshot("Sophos")
        assert job["error"] == "Rate limited."
        assert job["dossier"] is None


class TestAnalyzeDossierContactsFlag:
    def test_contacts_search_is_skipped_when_asked(self, monkeypatch):
        import charon.dossier as dossier_mod

        monkeypatch.setattr(dossier_mod, "lookup_stock", lambda c: None)
        monkeypatch.setattr(
            dossier_mod, "query_claude_web_search_json",
            lambda *a, **kw: _dossier_result("Moxfive"),
        )

        def boom(*a, **kw):
            raise AssertionError("contacts search should not run")

        monkeypatch.setattr(dossier_mod, "find_contacts", boom)
        result = dossier_mod.analyze_dossier(
            "Moxfive", {"values": {"security_culture": 1.0}}, include_contacts=False
        )
        assert result["company"] == "Moxfive"
