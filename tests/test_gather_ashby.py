"""Tests for the Ashby adapter."""

import json
from pathlib import Path

import httpx
import pytest

from charon.gather import GatherError, gather_employer
from charon.gather import ashby


FIXTURES = Path(__file__).parent / "fixtures"


def _mock_client(payload, status_code: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if status_code != 200:
            return httpx.Response(status_code, json={"error": "test"})
        return httpx.Response(200, json=payload)
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestAshbyAdapter:
    def test_fetches_and_normalizes(self):
        payload = json.loads((FIXTURES / "ashby_sample.json").read_text(encoding="utf-8"))
        client = _mock_client(payload)
        try:
            jobs = ashby.fetch_jobs("example", entry={"name": "Example Co"}, client=client)
        finally:
            client.close()

        assert len(jobs) == 4
        first = jobs[0]
        assert first["company"] == "Example Co"
        assert first["role"] == "Senior Security Engineer"
        assert first["url"] == "https://jobs.ashbyhq.com/example/abc-001"
        assert first["location"] == "Remote, North America"
        assert "Build and tune our detection coverage" in first["description"]
        assert first["posted_at"] == "2026-04-25T18:30:00Z"

    def test_secondary_locations_fallback(self):
        payload = json.loads((FIXTURES / "ashby_sample.json").read_text(encoding="utf-8"))
        client = _mock_client(payload)
        try:
            jobs = ashby.fetch_jobs("example", client=client)
        finally:
            client.close()
        assert jobs[1]["location"] == "New York, London"

    def test_remote_flag_fallback(self):
        payload = json.loads((FIXTURES / "ashby_sample.json").read_text(encoding="utf-8"))
        client = _mock_client(payload)
        try:
            jobs = ashby.fetch_jobs("example", client=client)
        finally:
            client.close()
        # Third job has no location, no secondaries, but isRemote=true
        assert jobs[2]["location"] == "Remote"

    def test_html_description_stripped(self):
        payload = json.loads((FIXTURES / "ashby_sample.json").read_text(encoding="utf-8"))
        client = _mock_client(payload)
        try:
            jobs = ashby.fetch_jobs("example", client=client)
        finally:
            client.close()
        # Fourth job has HTML-only description
        desc = jobs[3]["description"]
        assert "<p>" not in desc
        assert "<strong>" not in desc
        # BeautifulSoup splits on tag boundaries; verify the words survive
        for word in ("HTML", "only", "here", "Item"):
            assert word in desc

    def test_404_raises(self):
        client = _mock_client({}, status_code=404)
        try:
            with pytest.raises(GatherError, match="404"):
                ashby.fetch_jobs("nope", client=client)
        finally:
            client.close()

    def test_500_raises(self):
        client = _mock_client({}, status_code=500)
        try:
            with pytest.raises(GatherError, match="500"):
                ashby.fetch_jobs("err", client=client)
        finally:
            client.close()

    def test_empty_jobs(self):
        client = _mock_client({"jobs": []})
        try:
            jobs = ashby.fetch_jobs("empty", client=client)
        finally:
            client.close()
        assert jobs == []

    def test_missing_jobs_field(self):
        client = _mock_client({"apiVersion": "2"})
        try:
            jobs = ashby.fetch_jobs("empty", client=client)
        finally:
            client.close()
        assert jobs == []

    def test_jobs_not_list_raises(self):
        client = _mock_client({"jobs": "not a list"})
        try:
            with pytest.raises(GatherError, match="not a list"):
                ashby.fetch_jobs("bad", client=client)
        finally:
            client.close()

    def test_response_not_dict_raises(self):
        client = _mock_client(["array", "not", "object"])
        try:
            with pytest.raises(GatherError, match="not a JSON object"):
                ashby.fetch_jobs("bad", client=client)
        finally:
            client.close()

    def test_empty_slug_raises(self):
        with pytest.raises(GatherError, match="empty"):
            ashby.fetch_jobs("")

    def test_missing_url_or_title_skipped(self):
        payload = {
            "jobs": [
                {"title": "No URL"},
                {"jobUrl": "https://jobs.ashbyhq.com/x/2", "title": "Real"},
                {"jobUrl": "https://jobs.ashbyhq.com/x/3"},
            ]
        }
        client = _mock_client(payload)
        try:
            jobs = ashby.fetch_jobs("example", client=client)
        finally:
            client.close()
        assert len(jobs) == 1
        assert jobs[0]["role"] == "Real"

    def test_apply_url_fallback(self):
        payload = {
            "jobs": [
                {
                    "title": "Has only applyUrl",
                    "applyUrl": "https://jobs.ashbyhq.com/x/apply-only",
                    "location": "Remote",
                }
            ]
        }
        client = _mock_client(payload)
        try:
            jobs = ashby.fetch_jobs("example", client=client)
        finally:
            client.close()
        assert len(jobs) == 1
        assert jobs[0]["url"] == "https://jobs.ashbyhq.com/x/apply-only"


class TestAshbyViaOrchestrator:
    def test_dispatches_through_gather_employer(self, monkeypatch):
        payload = json.loads((FIXTURES / "ashby_sample.json").read_text(encoding="utf-8"))

        def fake_fetch(slug, *, entry=None, client=None):
            assert slug == "vanta"
            return [
                {
                    "company": "Vanta",
                    "role": p["title"],
                    "url": p["jobUrl"],
                    "location": "Remote",
                    "description": p.get("descriptionPlain", ""),
                    "posted_at": p.get("publishedAt"),
                }
                for p in payload["jobs"] if "jobUrl" in p
            ]
        monkeypatch.setattr(ashby, "fetch_jobs", fake_fetch)

        entry = {"slug": "vanta", "name": "Vanta", "tier": "tier_1", "category": "grc"}
        summary = gather_employer("ashby", entry)

        assert summary["fetched"] == 4
        assert summary["new"] == 4
        assert summary["error"] is None
