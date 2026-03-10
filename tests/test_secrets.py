"""Tests for secret retrieval (no live Vault required)."""

import os
import pytest

from charon.secrets import SecretsError, get_imap_password


class TestGetImapPassword:
    def test_from_account_config(self):
        profile = {
            "inbox": {
                "accounts": [
                    {"name": "gmail", "imap_pass": "direct-pass"},
                ],
            },
        }
        assert get_imap_password(profile, "gmail") == "direct-pass"

    def test_from_env_var(self, monkeypatch):
        monkeypatch.setenv("CHARON_IMAP_PASS_GMAIL", "env-pass")
        profile = {
            "inbox": {
                "accounts": [
                    {"name": "gmail", "imap_pass": ""},
                ],
            },
        }
        assert get_imap_password(profile, "gmail") == "env-pass"

    def test_no_password_raises(self):
        profile = {
            "inbox": {
                "accounts": [
                    {"name": "gmail", "imap_pass": ""},
                ],
            },
        }
        # Clear any env var that might interfere
        os.environ.pop("CHARON_IMAP_PASS_GMAIL", None)
        with pytest.raises(SecretsError, match="No password found"):
            get_imap_password(profile, "gmail")

    def test_account_not_found(self):
        profile = {
            "inbox": {"accounts": []},
        }
        os.environ.pop("CHARON_IMAP_PASS_MISSING", None)
        with pytest.raises(SecretsError, match="No password found"):
            get_imap_password(profile, "missing")

    def test_case_insensitive_account_name(self):
        profile = {
            "inbox": {
                "accounts": [
                    {"name": "Gmail", "imap_pass": "case-pass"},
                ],
            },
        }
        assert get_imap_password(profile, "GMAIL") == "case-pass"

    def test_vault_config_without_url_skips_vault(self, monkeypatch):
        monkeypatch.setenv("CHARON_IMAP_PASS_TEST", "env-fallback")
        profile = {
            "vault": {"url": ""},
            "inbox": {
                "accounts": [
                    {"name": "test", "imap_pass": ""},
                ],
            },
        }
        # Should skip Vault (no URL) and use env var
        assert get_imap_password(profile, "test") == "env-fallback"

    def test_priority_account_config_over_env(self, monkeypatch):
        monkeypatch.setenv("CHARON_IMAP_PASS_GMAIL", "env-pass")
        profile = {
            "inbox": {
                "accounts": [
                    {"name": "gmail", "imap_pass": "config-pass"},
                ],
            },
        }
        # Account config should win over env var
        assert get_imap_password(profile, "gmail") == "config-pass"
