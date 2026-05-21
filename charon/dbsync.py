"""Pull the live charon.db down from the deployed portal.

ONE-WAY ONLY: portal -> local. Fetches a snapshot of the live DB (which
lives on the port53 VM) to this machine for local development and
testing. It NEVER pushes local changes back up — pushing local data to
the portal is how you'd clobber real applications. Sending local
changes up, if ever needed, is a deliberate reviewed operation, not
this command.

Connection details live in ~/.charon/sync.yaml (gitignored — infra
specifics stay out of the public repo):

    remote_host: port53.empire12.net
    remote_user: charon
    remote_db_path: /home/charon/.charon/charon.db
    jump_host: ops                       # optional — ssh -J
    ssh_key: ~/.ssh/id_ed25519           # optional
    local_db_path: ~/.charon/charon.db   # optional, defaults to DB_PATH

Binary-safe transfer: base64-over-SSH. Windows OpenSSH SCP truncates
binary files (per the project's infra notes), so the remote
base64-encodes the DB and we decode locally. The decoded bytes are
validated against the SQLite magic header before anything is written,
and the existing local DB is backed up to a timestamped file first.
"""

from __future__ import annotations

import base64
import shlex
import sqlite3
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


SQLITE_MAGIC = b"SQLite format 3\x00"


class SyncError(Exception):
    pass


def _config_path() -> Path:
    from charon.profile import ensure_charon_dir
    return ensure_charon_dir() / "sync.yaml"


def load_sync_config() -> dict[str, Any]:
    import yaml

    path = _config_path()
    if not path.exists():
        raise SyncError(
            f"No sync config at {path}.\n"
            f"Create it with at least:\n"
            f"  remote_host: <portal host>\n"
            f"  remote_user: <ssh user>\n"
            f"  remote_db_path: /home/charon/.charon/charon.db\n"
            f"Optional: jump_host, ssh_key, local_db_path."
        )
    with path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        raise SyncError(f"{path} is not a valid YAML mapping.")
    for required in ("remote_host", "remote_user", "remote_db_path"):
        if not cfg.get(required):
            raise SyncError(f"{path} is missing required key: {required}")
    return cfg


def _build_ssh_cmd(cfg: dict[str, Any]) -> list[str]:
    """Build the ssh argv. No shell=True — args are a list, and the
    remote command quotes the remote path with shlex for the remote
    POSIX shell."""
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
    jump = cfg.get("jump_host")
    if jump:
        cmd += ["-J", str(jump)]
    key = cfg.get("ssh_key")
    if key:
        cmd += ["-i", str(Path(key).expanduser())]
    cmd.append(f"{cfg['remote_user']}@{cfg['remote_host']}")
    # Remote: base64 the DB with no line wrapping. shlex.quote guards
    # the remote path against spaces / shell metacharacters.
    cmd.append(f"base64 -w0 {shlex.quote(str(cfg['remote_db_path']))}")
    return cmd


def _count_rows(db_bytes: bytes) -> dict[str, int]:
    """Write bytes to a temp file and count the rows that matter so the
    caller can show a meaningful before/after."""
    counts: dict[str, int] = {}
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        tf.write(db_bytes)
        tmp_path = tf.name
    try:
        conn = sqlite3.connect(tmp_path)
        try:
            for table in ("discoveries", "applications"):
                try:
                    counts[table] = conn.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                except sqlite3.Error:
                    counts[table] = -1
        finally:
            conn.close()
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return counts


def _local_counts(local_path: Path) -> dict[str, int]:
    if not local_path.exists():
        return {}
    try:
        return _count_rows(local_path.read_bytes())
    except (OSError, sqlite3.Error):
        return {}


def pull_db(*, dry_run: bool = False) -> dict[str, Any]:
    """Pull the live DB from the portal to the local path.

    Returns a summary dict. Raises SyncError on any failure — the local
    DB is never touched unless the pull succeeds and validates.
    """
    cfg = load_sync_config()

    from charon.db import DB_PATH
    local_path = Path(cfg.get("local_db_path") or DB_PATH).expanduser()

    before = _local_counts(local_path)

    ssh_cmd = _build_ssh_cmd(cfg)
    try:
        result = subprocess.run(  # noqa: S603 — argv list, no shell
            ssh_cmd, capture_output=True, timeout=120, check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        raise SyncError(f"SSH transfer failed: {e}") from e
    if result.returncode != 0:
        err = result.stderr.decode("utf-8", "replace").strip()
        raise SyncError(f"SSH returned {result.returncode}: {err[:400]}")

    try:
        raw = base64.b64decode(result.stdout, validate=True)
    except Exception as e:  # noqa: BLE001
        raise SyncError(f"Couldn't decode the transferred data: {e}") from e

    if not raw.startswith(SQLITE_MAGIC):
        raise SyncError(
            "Transferred file is not a valid SQLite database "
            "(magic header missing). Aborting — local DB untouched."
        )

    after = _count_rows(raw)

    summary: dict[str, Any] = {
        "remote_host": cfg["remote_host"],
        "remote_db_path": cfg["remote_db_path"],
        "local_db_path": str(local_path),
        "bytes": len(raw),
        "before": before,
        "after": after,
        "backup": None,
        "dry_run": dry_run,
    }

    if dry_run:
        return summary

    # Back up the existing local DB before overwriting.
    if local_path.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = local_path.with_name(
            f"{local_path.stem}.bak-{ts}{local_path.suffix}"
        )
        backup.write_bytes(local_path.read_bytes())
        summary["backup"] = str(backup)

    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(raw)
    return summary


__all__ = ["SyncError", "pull_db", "load_sync_config"]
