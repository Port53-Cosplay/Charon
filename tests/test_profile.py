"""Tests for profile loading and validation."""

import copy
import pytest

from charon.profile import (
    DEFAULT_PROFILE,
    ProfileError,
    validate_profile,
    get_profile_display,
)


@pytest.fixture
def valid_profile():
    return copy.deepcopy(DEFAULT_PROFILE)


def test_valid_profile_passes(valid_profile):
    validate_profile(valid_profile)  # should not raise


def test_missing_required_keys(valid_profile):
    del valid_profile["values"]
    with pytest.raises(ProfileError, match="missing required keys"):
        validate_profile(valid_profile)


def test_values_must_sum_to_one(valid_profile):
    valid_profile["values"]["security_culture"] = 0.99
    with pytest.raises(ProfileError, match="must sum to 1.0"):
        validate_profile(valid_profile)


def test_invalid_value_dimension(valid_profile):
    valid_profile["values"]["hacking_skills"] = 0.10
    with pytest.raises(ProfileError, match="Unknown value dimensions"):
        validate_profile(valid_profile)


def test_value_weight_must_be_number(valid_profile):
    valid_profile["values"]["security_culture"] = "high"
    with pytest.raises(ProfileError, match="must be a number"):
        validate_profile(valid_profile)


def test_value_weight_range(valid_profile):
    valid_profile["values"]["security_culture"] = -0.5
    with pytest.raises(ProfileError, match="must be between 0 and 1"):
        validate_profile(valid_profile)


def test_dealbreakers_must_be_list(valid_profile):
    valid_profile["dealbreakers"] = "not a list"
    with pytest.raises(ProfileError, match="must be a list"):
        validate_profile(valid_profile)


def test_dealbreaker_items_must_be_strings(valid_profile):
    valid_profile["dealbreakers"] = [123, "valid"]
    with pytest.raises(ProfileError, match="must be a string"):
        validate_profile(valid_profile)


def test_profile_not_dict():
    with pytest.raises(ProfileError, match="must be a YAML mapping"):
        validate_profile("just a string")


def test_display_redacts_secrets(valid_profile):
    valid_profile["notifications"]["mail_pass"] = "supersecret"
    valid_profile["notifications"]["mail_user"] = "admin"
    display = get_profile_display(valid_profile)
    assert display["notifications"]["mail_pass"] == "••••••••"
    assert display["notifications"]["mail_user"] == "••••••••"
    # Original unchanged
    assert valid_profile["notifications"]["mail_pass"] == "supersecret"


def test_display_empty_secrets_not_redacted(valid_profile):
    valid_profile["notifications"]["mail_pass"] = ""
    display = get_profile_display(valid_profile)
    assert display["notifications"]["mail_pass"] == ""
