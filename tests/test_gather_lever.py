"""Tests for the Lever adapter."""

import json
from pathlib import Path

import httpx
import pytest

from charon.gather import GatherError, gather_employer
from charon.gather import lever


FIXTURES = Path(__file__).parent / "fixtures"


def _mock_client(payload, status_code: int = 200) -> httpx.Client:
    """Build an httpx client that returns the given JSON for any request."""
    def handler(request: httpx.Request) -> httpx.Response:
        if status_code != 200:
            return httpx.Response(status_code, json={"error": "test"})
        return httpx.Response(200, json=payload)
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestLeverAdapter:
    def test_fetches_and_normalizes(self):
        payload = json.loads((FIXTURES / "lever_sample.json").read_text(encoding="utf-8"))
        client = _mock_client(payload)
        try:
            jobs = lever.fetch_jobs("example", entry={"name": "Example Co"}, client=client)
        finally:
            client.close()

        # Third entry has no URL — skipped
        assert len(jobs) == 2

        first = jobs[0]
        assert first["company"] == "Example Co"
        assert first["role"] == "Senior Detection Engineer"
        assert first["url"] == "https://jobs.lever.co/example/0001-aaaa-bbbb-cccc"
        assert first["location"] == "Remote - North America"
        # Plain-text fields preferred; HTML stripped from list content
        assert "Senior Detection Engineer" in first["description"]
        assert "Build detections" in first["description"]
        assert "<ul>" not in first["description"]
        assert "<li>" not in first["description"]
        # Epoch-ms converted to ISO-8601
        assert first["posted_at"] is not None
        assert first["posted_at"].startswith("2025-04-")  # 1745529600000 = 2025-04-24

    def test_all_locations_fallback(self):
        payload = json.loads((FIXTURES / "lever_sample.json").read_text(encoding="utf-8"))
        client = _mock_client(payload)
        try:
            jobs = lever.fetch_jobs("example", client=client)
        finally:
            client.close()
        # Second job uses allLocations array
        assert jobs[1]["location"] == "Remote, New York"

    def test_404_raises(self):
        client = _mock_client({}, status_code=404)
        try:
            with pytest.raises(GatherError, match="404"):
                lever.fetch_jobs("nonexistent-slug", client=client)
        finally:
            client.close()

    def test_500_raises(self):
        client = _mock_client({}, status_code=500)
        try:
            with pytest.raises(GatherError, match="500"):
                lever.fetch_jobs("server-error", client=client)
        finally:
            client.close()

    def test_empty_list(self):
        client = _mock_client([])
        try:
            jobs = lever.fetch_jobs("empty", client=client)
        finally:
            client.close()
        assert jobs == []

    def test_non_list_response_raises(self):
        client = _mock_client({"jobs": []})
        try:
            with pytest.raises(GatherError, match="not a JSON list"):
                lever.fetch_jobs("wrong-shape", client=client)
        finally:
            client.close()

    def test_empty_slug_raises(self):
        with pytest.raises(GatherError, match="empty"):
            lever.fetch_jobs("")

    def test_missing_url_or_title_skipped(self):
        payload = [
            {"text": "No URL"},
            {"hostedUrl": "https://jobs.lever.co/x/2", "text": "Real"},
            {"hostedUrl": "https://jobs.lever.co/x/3"},  # no text
        ]
        client = _mock_client(payload)
        try:
            jobs = lever.fetch_jobs("example", client=client)
        finally:
            client.close()
        assert len(jobs) == 1
        assert jobs[0]["role"] == "Real"

    def test_apply_url_fallback(self):
        payload = [
            {
                "text": "No hostedUrl",
                "applyUrl": "https://jobs.lever.co/x/apply-only",
                "categories": {},
            }
        ]
        client = _mock_client(payload)
        try:
            jobs = lever.fetch_jobs("example", client=client)
        finally:
            client.close()
        assert len(jobs) == 1
        assert jobs[0]["url"] == "https://jobs.lever.co/x/apply-only"


class TestLeverViaOrchestrator:
    def test_dispatches_through_gather_employer(self, monkeypatch):
        payload = json.loads((FIXTURES / "lever_sample.json").read_text(encoding="utf-8"))

        def fake_fetch(slug, *, entry=None, client=None):
            assert slug == "sysdig"
            return [
                {
                    "company": "Sysdig",
                    "role": p["text"],
                    "url": p["hostedUrl"],
                    "location": "Remote",
                    "description": p.get("descriptionPlain", ""),
                    "posted_at": None,
                }
                for p in payload if "hostedUrl" in p
            ]
        monkeypatch.setattr(lever, "fetch_jobs", fake_fetch)

        entry = {"slug": "sysdig", "name": "Sysdig", "tier": "tier_2", "category": "cloud_security"}
        summary = gather_employer("lever", entry)

        assert summary["fetched"] == 2
        assert summary["new"] == 2
        assert summary["error"] is None
