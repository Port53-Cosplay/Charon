"""Tests for the sidebar's profile-link copy buttons."""

import pytest

from charon import dashboard
from charon import profile


def _with_profile(monkeypatch, data):
    monkeypatch.setattr(profile, "load_profile", lambda: data)


def test_links_come_from_the_profile(monkeypatch):
    _with_profile(monkeypatch, {"links": {
        "linkedin": "https://www.linkedin.com/in/someone",
        "github": "https://github.com/someone",
    }})
    assert dashboard._profile_links() == {
        "linkedin": "https://www.linkedin.com/in/someone",
        "github": "https://github.com/someone",
    }


def test_no_links_block_means_no_buttons(monkeypatch):
    _with_profile(monkeypatch, {})
    assert dashboard._profile_links() == {}


def test_unsafe_or_unknown_links_are_dropped(monkeypatch):
    _with_profile(monkeypatch, {"links": {
        "github": "javascript:alert(1)",
        "myspace": "https://myspace.com/someone",
        "linkedin": "",
    }})
    assert dashboard._profile_links() == {}


def test_broken_profile_means_no_buttons(monkeypatch):
    def boom():
        raise profile.ProfileError("bad")
    monkeypatch.setattr(profile, "load_profile", boom)
    assert dashboard._profile_links() == {}
