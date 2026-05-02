"""Tests for the Workday adapter."""

import json
from pathlib import Path

import httpx
import pytest

from charon.gather import GatherError, gather_employer
from charon.gather import workday


FIXTURES = Path(__file__).parent / "fixtures"


SCHELLMAN_ENTRY = {
    "slug": "schellman",
    "name": "Schellman",
    "tier": "tier_1",
    "category": "audit",
    "workday": {"tenant": "schellman", "wd": "wd1", "site": "Careers"},
}


def _paginated_mock_client(pages: list[dict], status_code: int = 200) -> httpx.Client:
    """Returns each page in sequence on successive POSTs."""
    state = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if status_code != 200:
            return httpx.Response(status_code, json={"error": "test"})
        idx = state["i"]
        if idx >= len(pages):
            return httpx.Response(200, json={"total": 0, "jobPostings": []})
        state["i"] += 1
        return httpx.Response(200, json=pages[idx])

    return httpx.Client(transport=httpx.MockTransport(handler))


class TestResolveTenant:
    def test_reads_workday_block(self):
        tenant, wd, site = workday._resolve_tenant(SCHELLMAN_ENTRY)
        assert tenant == "schellman"
        assert wd == "wd1"
        assert site == "Careers"

    def test_missing_entry_raises(self):
        with pytest.raises(GatherError, match="registry entry"):
            workday._resolve_tenant(None)

    def test_missing_workday_block(self):
        with pytest.raises(GatherError, match="workday"):
            workday._resolve_tenant({"slug": "x", "name": "X"})

    def test_missing_required_field(self):
        with pytest.raises(GatherError, match="tenant, wd"):
            workday._resolve_tenant({"slug": "x", "workday": {"tenant": "x"}})


class TestBuildJobURL:
    def test_with_leading_slash(self):
        url = workday._build_job_url("schellman", "wd1", "Careers", "/job/Tampa-FL/Senior_R1")
        assert url == "https://schellman.wd1.myworkdayjobs.com/en-US/Careers/job/Tampa-FL/Senior_R1"

    def test_without_leading_slash(self):
        url = workday._build_job_url("crowdstrike", "wd5", "crowdstrikecareers", "job/Remote/X")
        assert url == "https://crowdstrike.wd5.myworkdayjobs.com/en-US/crowdstrikecareers/job/Remote/X"


class TestWorkdayPagination:
    def test_two_page_walk(self):
        page1 = json.loads((FIXTURES / "workday_page1.json").read_text(encoding="utf-8"))
        page2 = json.loads((FIXTURES / "workday_page2.json").read_text(encoding="utf-8"))
        client = _paginated_mock_client([page1, page2])
        try:
            jobs = workday.fetch_jobs(
                "schellman",
                entry=SCHELLMAN_ENTRY,
                client=client,
                page_delay=0,
            )
        finally:
            client.close()

        # 25 total, but page1 has 2 entries that get skipped
        # (one with no externalPath, one with null title)
        # Page 1 valid: 18, Page 2 valid: 5 → 23 total
        assert len(jobs) == 23

        first = jobs[0]
        assert first["company"] == "Schellman"
        assert first["role"] == "Senior Security Engineer"
        assert first["url"] == (
            "https://schellman.wd1.myworkdayjobs.com/en-US/Careers"
            "/job/USA-Remote/Senior-Security-Engineer_R12345"
        )
        assert first["location"] == "USA-Remote"
        assert first["posted_at"] == "Posted 2 Days Ago"
        # Description deferred to Phase 7
        assert first["description"] == ""

    def test_stops_when_total_reached(self):
        # Build a 3-page sequence but total is only 20 (one full page)
        page = {
            "total": 20,
            "jobPostings": [
                {"title": f"R{i}", "externalPath": f"/job/R{i}"} for i in range(20)
            ],
        }
        # If adapter respected total, only 1 page should be fetched
        request_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            request_count["n"] += 1
            return httpx.Response(200, json=page)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        try:
            jobs = workday.fetch_jobs(
                "schellman",
                entry=SCHELLMAN_ENTRY,
                client=client,
                page_delay=0,
            )
        finally:
            client.close()
        assert len(jobs) == 20
        assert request_count["n"] == 1

    def test_stops_on_partial_page(self):
        # Don't include `total` — adapter should stop on partial page
        partial_page = {
            "jobPostings": [
                {"title": f"R{i}", "externalPath": f"/job/R{i}"} for i in range(5)
            ]
        }
        request_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            request_count["n"] += 1
            return httpx.Response(200, json=partial_page)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        try:
            jobs = workday.fetch_jobs(
                "schellman",
                entry=SCHELLMAN_ENTRY,
                client=client,
                page_delay=0,
            )
        finally:
            client.close()
        assert len(jobs) == 5
        assert request_count["n"] == 1

    def test_empty_jobs_list(self):
        client = _paginated_mock_client([{"total": 0, "jobPostings": []}])
        try:
            jobs = workday.fetch_jobs(
                "schellman", entry=SCHELLMAN_ENTRY, client=client, page_delay=0
            )
        finally:
            client.close()
        assert jobs == []

    def test_missing_jobPostings_returns_empty(self):
        client = _paginated_mock_client([{"total": 0}])
        try:
            jobs = workday.fetch_jobs(
                "schellman", entry=SCHELLMAN_ENTRY, client=client, page_delay=0
            )
        finally:
            client.close()
        assert jobs == []


class TestWorkdayErrors:
    def test_404_raises(self):
        client = _paginated_mock_client([], status_code=404)
        try:
            with pytest.raises(GatherError, match="404"):
                workday.fetch_jobs(
                    "schellman", entry=SCHELLMAN_ENTRY, client=client, page_delay=0
                )
        finally:
            client.close()

    def test_405_raises(self):
        client = _paginated_mock_client([], status_code=405)
        try:
            with pytest.raises(GatherError, match="405"):
                workday.fetch_jobs(
                    "schellman", entry=SCHELLMAN_ENTRY, client=client, page_delay=0
                )
        finally:
            client.close()

    def test_500_raises(self):
        client = _paginated_mock_client([], status_code=500)
        try:
            with pytest.raises(GatherError, match="500"):
                workday.fetch_jobs(
                    "schellman", entry=SCHELLMAN_ENTRY, client=client, page_delay=0
                )
        finally:
            client.close()

    def test_non_dict_response_raises(self):
        def handler(request):
            return httpx.Response(200, json=["not", "an", "object"])
        client = httpx.Client(transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(GatherError, match="not a JSON object"):
                workday.fetch_jobs(
                    "schellman", entry=SCHELLMAN_ENTRY, client=client, page_delay=0
                )
        finally:
            client.close()

    def test_jobPostings_not_list_raises(self):
        client = _paginated_mock_client([{"jobPostings": "wrong"}])
        try:
            with pytest.raises(GatherError, match="not a list"):
                workday.fetch_jobs(
                    "schellman", entry=SCHELLMAN_ENTRY, client=client, page_delay=0
                )
        finally:
            client.close()

    def test_empty_slug_raises(self):
        with pytest.raises(GatherError, match="empty"):
            workday.fetch_jobs("", entry=SCHELLMAN_ENTRY)


class TestWorkdayViaOrchestrator:
    def test_dispatches_through_gather_employer(self, monkeypatch):
        page1 = json.loads((FIXTURES / "workday_page1.json").read_text(encoding="utf-8"))
        page2 = json.loads((FIXTURES / "workday_page2.json").read_text(encoding="utf-8"))

        captured_entry = {}

        def fake_fetch(slug, *, entry=None, client=None, page_delay=1.0):
            captured_entry["e"] = entry
            assert slug == "schellman"
            return [
                {
                    "company": "Schellman",
                    "role": p["title"],
                    "url": f"https://schellman.wd1.myworkdayjobs.com/en-US/Careers{p['externalPath']}",
                    "location": p.get("locationsText"),
                    "description": "",
                    "posted_at": p.get("postedOn"),
                }
                for p in (page1["jobPostings"] + page2["jobPostings"])
                if p.get("title") and p.get("externalPath")
            ]
        monkeypatch.setattr(workday, "fetch_jobs", fake_fetch)

        summary = gather_employer("workday", SCHELLMAN_ENTRY)

        assert summary["fetched"] == 23
        assert summary["new"] == 23
        assert summary["error"] is None
        # Adapter received the full entry (so it can read .workday block)
        assert captured_entry["e"]["workday"]["tenant"] == "schellman"
