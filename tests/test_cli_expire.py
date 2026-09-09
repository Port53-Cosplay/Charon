"""Tests for the charon expire CLI command via Click's CliRunner."""

from click.testing import CliRunner

from charon.cli import cli
from charon.db import (
    add_discovery,
    get_connection,
    get_discovery,
    update_discovery_judgement,
)

OLD = "2026-01-01T00:00:00+00:00"


def _seed_ready(dedupe_hash, judged_at=None):
    new_id = add_discovery(
        ats="lever",
        slug="coalfire",
        company="Coalfire",
        role="SOC Assessor",
        url=f"https://jobs.lever.co/coalfire/{dedupe_hash}",
        dedupe_hash=dedupe_hash,
        location="Remote",
        description="",
        posted_at="Posted Today",
        tier="tier_1",
        category="audit",
    )
    update_discovery_judgement(
        new_id,
        ghost_score=15,
        redflag_score=20,
        alignment_score=80,
        combined_score=78.0,
        screened_status="ready",
        judgement_reason="combined 78.0 >= 60",
    )
    if judged_at is not None:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE discoveries SET judged_at = ? WHERE id = ?",
                (judged_at, new_id),
            )
            conn.commit()
        finally:
            conn.close()
    return new_id


class TestExpireCommand:
    def test_requires_exactly_one_cutoff(self):
        result = CliRunner().invoke(cli, ["expire"])
        assert "Pick exactly one" in result.output

        result = CliRunner().invoke(
            cli, ["expire", "--older-than", "30", "--all-ready"]
        )
        assert "Pick exactly one" in result.output

    def test_older_than_with_yes_expires(self):
        old = _seed_ready("cx-old", judged_at=OLD)
        fresh = _seed_ready("cx-fresh")

        result = CliRunner().invoke(cli, ["expire", "--older-than", "30", "--yes"])
        assert result.exit_code == 0
        assert "EXPIRE SUMMARY" in result.output
        assert get_discovery(old)["screened_status"] == "expired"
        assert get_discovery(fresh)["screened_status"] == "ready"

    def test_abort_leaves_rows_untouched(self):
        rid = _seed_ready("cx-abort", judged_at=OLD)

        result = CliRunner().invoke(cli, ["expire", "--all-ready"], input="n\n")
        assert "Aborted" in result.output
        assert get_discovery(rid)["screened_status"] == "ready"

    def test_bad_before_reports_error(self):
        result = CliRunner().invoke(cli, ["expire", "--before", "not-a-date"])
        assert "Invalid ISO" in result.output

    def test_nothing_to_expire(self):
        result = CliRunner().invoke(cli, ["expire", "--all-ready", "--yes"])
        assert "Nothing to expire" in result.output

    def test_list_shows_expired(self):
        rid = _seed_ready("cx-list", judged_at=OLD)
        CliRunner().invoke(cli, ["expire", "--all-ready", "--yes"])

        result = CliRunner().invoke(cli, ["expire", "--list"])
        assert result.exit_code == 0
        assert f"#{rid}" in result.output
        assert "Coalfire" in result.output
