"""Secret retrieval from HashiCorp Vault with env var fallback."""

import os
from typing import Any


class SecretsError(Exception):
    """Raised when secret retrieval fails."""


def _get_vault_client(vault_config: dict[str, Any]):
    """Build an authenticated hvac client from profile config."""
    try:
        import hvac
    except ImportError:
        raise SecretsError(
            "Vault support requires hvac. Run:\n"
            "  pip install hvac"
        )

    url = vault_config.get("url", "")
    if not url:
        raise SecretsError("vault.url not set in profile.")

    # Support custom CA cert for private PKI
    ca_cert = vault_config.get("ca_cert", "") or os.environ.get("VAULT_CACERT", "")
    if ca_cert:
        ca_cert = os.path.expanduser(ca_cert)
    verify = ca_cert if ca_cert else vault_config.get("verify_ssl", True)

    # Try AppRole auth first (persistent, no manual token management)
    role_id = vault_config.get("role_id", "") or os.environ.get("VAULT_ROLE_ID", "")
    secret_id = vault_config.get("secret_id", "") or os.environ.get("VAULT_SECRET_ID", "")

    if role_id and secret_id:
        client = hvac.Client(url=url, verify=verify)
        try:
            result = client.auth.approle.login(
                role_id=role_id,
                secret_id=secret_id,
            )
            client.token = result["auth"]["client_token"]
            return client
        except Exception as e:
            raise SecretsError(f"Vault AppRole login failed: {e}")

    # Fall back to token auth
    token = vault_config.get("token", "") or os.environ.get("VAULT_TOKEN", "")
    if not token:
        raise SecretsError(
            "No Vault credentials. Set vault.role_id + vault.secret_id (AppRole)\n"
            "  or vault.token / VAULT_TOKEN env var."
        )

    client = hvac.Client(url=url, token=token, verify=verify)

    if not client.is_authenticated():
        raise SecretsError("Vault authentication failed. Check your token.")

    return client


def read_secret(vault_config: dict[str, Any], path: str) -> dict[str, Any]:
    """Read a secret from Vault KV v2. Returns the data dict."""
    client = _get_vault_client(vault_config)

    mount = vault_config.get("mount", "secret")

    try:
        response = client.secrets.kv.v2.read_secret_version(
            path=path,
            mount_point=mount,
        )
        return response["data"]["data"]
    except Exception as e:
        raise SecretsError(f"Failed to read secret at {path}: {e}")


def get_imap_password(profile: dict[str, Any], account_name: str) -> str:
    """Get IMAP password: try Vault first, fall back to env var."""
    vault_config = profile.get("vault", {})
    inbox_config = profile.get("inbox", {})

    # Find the account config
    account = None
    for acct in inbox_config.get("accounts", []):
        if acct.get("name", "").lower() == account_name.lower():
            account = acct
            break

    # 1. Check account-level imap_pass in profile (not recommended but supported)
    if account and account.get("imap_pass"):
        return account["imap_pass"]

    # 2. Try Vault if configured
    if vault_config.get("url"):
        vault_path = vault_config.get("secret_prefix", "charon")
        secret_key = f"imap-{account_name.lower()}"
        try:
            data = read_secret(vault_config, f"{vault_path}/{secret_key}")
            password = data.get("password", "")
            if password:
                return password
        except SecretsError:
            pass  # Fall through to env var

    # 3. Env var fallback
    env_key = f"CHARON_IMAP_PASS_{account_name.upper()}"
    password = os.environ.get(env_key, "")
    if password:
        return password

    raise SecretsError(
        f"No password found for account '{account_name}'.\n"
        f"  Options:\n"
        f"  1. Store in Vault at {vault_config.get('secret_prefix', 'charon')}/imap-{account_name.lower()}\n"
        f"  2. Set {env_key} environment variable\n"
        f"  3. Set imap_pass in profile (not recommended)"
    )
