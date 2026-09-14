"""Company contacts, found outside LinkedIn, one list per company.

The old contacts button searched LinkedIn for each posting separately and
saved a file into that posting's folder, so a company with four open roles
was searched four times for the same people. It's replaced by a per-company
search over public non-LinkedIn sources, stored like dossiers.
"""

import time

import pytest

from charon import dashboard
from charon.contacts import (
    MAX_COMPANY_CONTACTS,
    find_company_contacts,
    validate_company_contacts,
)
from charon.db import add_discovery, save_history, update_discovery_judgement


def _person(name, url, **kw):
    base = {"name": name, "title": "Security Manager", "category": "security_leadership",
            "source_type": "conference", "url": url, "relevance": "runs the SOC"}
    base.update(kw)
    return base


class TestValidation:
    def test_linkedin_only_people_are_dropped(self):
        out = validate_company_contacts({"contacts": [
            _person("Only On LinkedIn", "https://www.linkedin.com/in/someone"),
            _person("Gave A Talk", "https://bsidesnova.org/speakers/gave-a-talk"),
        ]})
        assert [c["name"] for c in out["contacts"]] == ["Gave A Talk"]

    def test_linkedin_contact_route_is_stripped_but_person_kept(self):
        out = validate_company_contacts({"contacts": [
            _person("Keeps Blog", "https://keepsblog.dev/about",
                    contact_route="linkedin.com/in/keepsblog"),
        ]})
        assert out["contacts"][0]["contact_route"] is None

    @pytest.mark.parametrize("url", ["ftp://x.org", "javascript:alert(1)", "", None, "bsides.org"])
    def test_non_http_urls_are_rejected(self, url):
        assert validate_company_contacts({"contacts": [_person("X", url)]})["contacts"] == []

    def test_unknown_labels_become_other(self):
        c = validate_company_contacts({"contacts": [
            _person("Y", "https://y.dev", category="ceo", source_type="tiktok"),
        ]})["contacts"][0]
        assert (c["category"], c["source_type"]) == ("other", "other")

    def test_list_is_capped(self):
        many = [_person(f"P{i}", f"https://p{i}.dev") for i in range(40)]
        assert len(validate_company_contacts({"contacts": many})["contacts"]) == MAX_COMPANY_CONTACTS

    def test_garbage_is_safe(self):
        assert validate_company_contacts("nope") == {"contacts": [], "search_notes": ""}


class TestSearch:
    def test_prompt_rules_out_linkedin_and_invented_emails(self, monkeypatch):
        import charon.ai as ai_mod

        seen = {}

        def fake_search(system, user, max_tokens, max_searches):
            seen["system"], seen["user"] = system, user
            return {"contacts": [_person("Z", "https://z.dev")], "search_notes": "ok"}

        monkeypatch.setattr(ai_mod, "query_claude_web_search_json", fake_search)
        out = find_company_contacts("Moxfive", {"target_roles": ["DFIR analyst"]})

        assert "Do not return LinkedIn profiles" in seen["system"]
        assert "Never guess, construct or pattern-match an email address" in seen["system"]
        assert "Moxfive" in seen["user"] and "DFIR analyst" in seen["user"]
        assert out["contacts"][0]["name"] == "Z"


def _seed_ready(company, dedupe_hash):
    rid = add_discovery(
        ats="lever", slug=dedupe_hash, company=company, role="DFIR Consultant",
        url=f"https://example.com/{dedupe_hash}", dedupe_hash=dedupe_hash,
        location="Remote", description="x" * 900, posted_at=None,
        tier="tier_2", category="security_product_general",
    )
    update_discovery_judgement(
        rid, ghost_score=18, redflag_score=42, alignment_score=92,
        combined_score=75.5, screened_status="ready", judgement_reason="combined 75.5 >= 70",
    )
    return rid


def _wait(kind, company, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not dashboard._research_job_running(kind, company):
            return
        time.sleep(0.02)
    raise AssertionError(f"{kind} build did not finish")


class TestDashboard:
    def test_one_search_is_shared_by_every_posting_from_the_company(self, monkeypatch):
        import charon.contacts as contacts_mod
        import charon.profile as profile_mod

        calls = []

        def fake_find(company, profile):
            calls.append(company)
            return {"contacts": [_person("Pat", "https://pat.dev")], "search_notes": ""}

        monkeypatch.setattr(contacts_mod, "find_company_contacts", fake_find)
        monkeypatch.setattr(profile_mod, "load_profile", lambda: {})

        first = _seed_ready("Moxfive", "cc-a")
        _seed_ready("Moxfive", "cc-b")
        dashboard._start_research("contacts", first)
        _wait("contacts", "Moxfive")

        rows = dashboard._ready_discoveries()
        assert len(rows) == 2
        assert calls == ["Moxfive"]
        ids = {r["company_contacts"]["id"] for r in rows}
        assert len(ids) == 1
        assert rows[0]["company_contacts"]["score"] == 1.0

    def test_stored_linkedin_links_never_reach_the_page(self):
        rid = save_history("contacts", "company", "Sophos", 2.0, {"contacts": [
            _person("Old Row", "https://linkedin.com/in/old-row"),
            _person("Good Row", "https://sophos.com/blog/authors/good-row"),
        ]}, company="Sophos")
        payload = dashboard._contacts_payload(rid)
        assert [c["name"] for c in payload["contacts"]] == ["Good Row"]
        assert payload["is_latest"] is True

    def test_dossier_and_contacts_can_build_side_by_side(self, monkeypatch):
        import threading
        import charon.contacts as contacts_mod
        import charon.dossier as dossier_mod
        import charon.profile as profile_mod

        release = threading.Event()

        def slow_find(company, profile):
            release.wait(5)
            return {"contacts": [], "search_notes": ""}

        def slow_dossier(company, profile, role_title=None, include_contacts=True):
            release.wait(5)
            return {"company": company, "summary": "", "overall_score": 50,
                    "dimensions": {}, "verdict": "", "weighted_score": 50}

        monkeypatch.setattr(contacts_mod, "find_company_contacts", slow_find)
        monkeypatch.setattr(dossier_mod, "analyze_dossier", slow_dossier)
        monkeypatch.setattr(dossier_mod, "save_dossier_markdown", lambda r, p: None)
        monkeypatch.setattr(profile_mod, "load_profile", lambda: {})

        rid = _seed_ready("BeyondTrust", "cc-side")
        try:
            dashboard._start_research("dossier", rid)
            dashboard._start_research("contacts", rid)  # different kind: allowed
            with pytest.raises(dashboard.DashboardError, match="contacts search"):
                dashboard._start_research("contacts", rid)
        finally:
            release.set()
            _wait("dossier", "BeyondTrust")
            _wait("contacts", "BeyondTrust")

    def test_applications_carry_company_research(self):
        from charon.db import add_application

        add_application(company="Moxfive", role="DFIR Consultant")
        save_history("contacts", "company", "Moxfive", 3.0, {"contacts": []}, company="Moxfive")
        apps, _ = dashboard._applications()
        assert apps[0]["company_contacts"]["score"] == 3.0
        assert apps[0]["dossier"] is None
