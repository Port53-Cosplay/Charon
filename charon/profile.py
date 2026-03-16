"""Profile loading, validation, and default generation."""

import os
from pathlib import Path
from typing import Any

import yaml


CHARON_DIR = Path.home() / ".charon"
PROFILE_PATH = CHARON_DIR / "profile.yaml"

DEFAULT_PROFILE = {
    "values": {
        "security_culture": 0.30,
        "people_treatment": 0.25,
        "leadership_transparency": 0.20,
        "work_life_balance": 0.15,
        "compensation": 0.10,
    },
    "dealbreakers": [
        "requires or strongly implies on-site work or relocation",
        "shift work, overnight hours, or on-call rotation required",
        "no salary or compensation range provided anywhere in posting",
        "remote work not available, not mentioned, or clearly not genuine",
        "rigid core hours inconsistent with async/flexible work",
    ],
    "yellow_flags": [
        "heavy synchronous meeting culture or real-time availability expectations",
        "fast-paced, high-pressure, or hustle language",
        "strong preference for local candidates",
        "unlimited PTO without supporting context",
        "like a family culture language",
    ],
    "green_flags": [
        "async-first or results-oriented work culture",
        "explicitly flexible or self-directed schedule",
        "transparent salary range included in posting",
        "security team has organizational authority",
        "genuine remote-first culture with documented practices",
    ],
    "target_roles": [
        "AI red team",
        "LLM security",
        "AI security researcher",
        "application security",
        "penetration tester",
        "offensive security",
    ],
    "notifications": {
        "enabled": False,
        "mail_server": "smtp.yourmailserver.com",
        "mail_port": 587,
        "mail_from": "charon@yourdomain.com",
        "mail_to": "you@yourdomain.com",
        "mail_user": "",
        "mail_pass": "",
    },
    "ghostbust": {
        "disqualify_threshold": 70,
    },
    "dossier": {
        "save_path": "~/.charon/dossiers/",
    },
    "applications": {
        "ghosted_after_days": 21,
    },
    "inbox": {
        "accounts": [],
    },
    "vault": {
        "url": "",
        "role_id": "",
        "secret_id": "",
        "ca_cert": "",
        "mount": "secret",
        "secret_prefix": "charon",
    },
}

REQUIRED_KEYS = {"values", "dealbreakers", "yellow_flags", "green_flags"}
VALID_VALUE_KEYS = {
    "security_culture",
    "people_treatment",
    "leadership_transparency",
    "work_life_balance",
    "compensation",
}

# Keys that contain sensitive data — never log or display
SENSITIVE_KEYS = {"mail_pass", "mail_user", "imap_pass", "token", "secret_id"}


class ProfileError(Exception):
    """Raised when the profile is invalid."""


def ensure_charon_dir() -> Path:
    """Create ~/.charon directory if it doesn't exist."""
    CHARON_DIR.mkdir(parents=True, exist_ok=True)
    return CHARON_DIR


def create_default_profile() -> Path:
    """Write the default profile template to disk."""
    ensure_charon_dir()

    header = (
        "# Charon User Profile\n"
        "# Edit this file to customize your job search preferences.\n"
        "# Values weights must sum to 1.0\n"
        "# mail_pass: store in CHARON_MAIL_PASS env var for safety\n"
        "\n"
    )

    with open(PROFILE_PATH, "w", encoding="utf-8") as f:
        f.write(header)
        yaml.dump(DEFAULT_PROFILE, f, default_flow_style=False, sort_keys=False)

    return PROFILE_PATH


def load_profile() -> dict[str, Any]:
    """Load and validate the user profile."""
    if not PROFILE_PATH.exists():
        create_default_profile()

    with open(PROFILE_PATH, "r", encoding="utf-8") as f:
        profile = yaml.safe_load(f)

    if profile is None:
        raise ProfileError("Profile is empty. Run 'charon profile --edit' to configure.")

    if not isinstance(profile, dict):
        raise ProfileError("Profile must be a YAML mapping, not a sequence or scalar.")

    validate_profile(profile)

    # Override mail_pass from env if set (prefer env over file)
    mail_pass_env = os.environ.get("CHARON_MAIL_PASS")
    if mail_pass_env and "notifications" in profile:
        profile["notifications"]["mail_pass"] = mail_pass_env

    return profile


def validate_profile(profile: dict[str, Any]) -> None:
    """Validate profile structure and values."""
    # Type guard
    if not isinstance(profile, dict):
        raise ProfileError("Profile must be a YAML mapping, not a sequence or scalar.")

    # Check required top-level keys
    missing = REQUIRED_KEYS - set(profile.keys())
    if missing:
        raise ProfileError(f"Profile missing required keys: {', '.join(missing)}")

    # Validate values weights
    values = profile.get("values", {})
    if not isinstance(values, dict):
        raise ProfileError("'values' must be a mapping of dimension: weight")

    invalid_keys = set(values.keys()) - VALID_VALUE_KEYS
    if invalid_keys:
        raise ProfileError(f"Unknown value dimensions: {', '.join(invalid_keys)}")

    for key, weight in values.items():
        if not isinstance(weight, (int, float)):
            raise ProfileError(f"Value weight for '{key}' must be a number, got {type(weight).__name__}")
        if not 0 <= weight <= 1:
            raise ProfileError(f"Value weight for '{key}' must be between 0 and 1")

    total = sum(values.values())
    if abs(total - 1.0) > 0.01:
        raise ProfileError(f"Values weights must sum to 1.0 (currently {total:.2f})")

    # Validate list fields
    for key in ("dealbreakers", "yellow_flags", "green_flags"):
        items = profile.get(key, [])
        if not isinstance(items, list):
            raise ProfileError(f"'{key}' must be a list")
        for i, item in enumerate(items):
            if not isinstance(item, str):
                raise ProfileError(f"'{key}[{i}]' must be a string")

    # Validate ghostbust threshold
    ghostbust = profile.get("ghostbust", {})
    if isinstance(ghostbust, dict):
        threshold = ghostbust.get("disqualify_threshold")
        if threshold is not None and not isinstance(threshold, (int, float)):
            raise ProfileError("ghostbust.disqualify_threshold must be a number")

    # Validate applications config
    apps_cfg = profile.get("applications", {})
    if isinstance(apps_cfg, dict):
        ghost_days = apps_cfg.get("ghosted_after_days")
        if ghost_days is not None:
            if not isinstance(ghost_days, (int, float)) or ghost_days < 1:
                raise ProfileError("applications.ghosted_after_days must be a positive number")

    # Validate notifications mail_to (string or list)
    notif = profile.get("notifications", {})
    if isinstance(notif, dict):
        mail_to = notif.get("mail_to")
        if mail_to is not None:
            if isinstance(mail_to, list):
                for addr in mail_to:
                    if not isinstance(addr, str):
                        raise ProfileError("notifications.mail_to list entries must be strings")
            elif not isinstance(mail_to, str):
                raise ProfileError("notifications.mail_to must be a string or list of strings")


def get_profile_display(profile: dict[str, Any]) -> dict[str, Any]:
    """Return a sanitized copy of the profile safe for display (no secrets)."""
    import copy
    display = copy.deepcopy(profile)
    notifications = display.get("notifications", {})
    if isinstance(notifications, dict):
        for key in SENSITIVE_KEYS:
            if key in notifications and notifications[key]:
                notifications[key] = "••••••••"
    # Redact IMAP passwords in inbox accounts
    inbox = display.get("inbox", {})
    if isinstance(inbox, dict):
        for account in inbox.get("accounts", []):
            if isinstance(account, dict) and account.get("imap_pass"):
                account["imap_pass"] = "••••••••"
    # Redact vault secrets
    vault = display.get("vault", {})
    if isinstance(vault, dict):
        if vault.get("token"):
            vault["token"] = "••••••••"
        if vault.get("secret_id"):
            vault["secret_id"] = "••••••••"
    return display
