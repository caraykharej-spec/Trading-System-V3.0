from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

from interfaces.api.config import FastApiSettings


@dataclass(frozen=True)
class PreflightReport:
    ready: bool
    checks: tuple[str, ...]


def production_preflight(env: Mapping[str, str]) -> PreflightReport:
    """Validate deploy-time invariants without starting the application."""

    settings = FastApiSettings.from_env(env)
    if settings.environment != "production":
        raise ValueError("production preflight requires TRADING_API_ENV=production")
    checks = ["api_policy", "explicit_hosts", "api_key"]
    key = env.get("TRADING_API_KEY", "")
    forbidden = {"changeme", "replace-me", "example", "secret", "password"}
    if key.strip().lower() in forbidden or len(set(key)) < 8:
        raise ValueError("TRADING_API_KEY appears to be a placeholder or low-entropy secret")
    if env.get("TRADING_TLS_TERMINATED", "").strip().lower() not in {"1", "true", "yes"}:
        raise ValueError("production requires acknowledged TLS termination")
    checks.append("tls_termination")

    database = Path(env.get("TRADING_DB_PATH", ""))
    universe = Path(env.get("TRADING_UNIVERSE_PATH", ""))
    backup = Path(env.get("TRADING_BACKUP_PATH", ""))
    if not database.is_absolute() or not universe.is_absolute() or not backup.is_absolute():
        raise ValueError("database, universe and backup paths must be absolute")
    if not universe.is_file():
        raise ValueError("TRADING_UNIVERSE_PATH must reference a readable file")
    data_parent = database.parent
    if not data_parent.is_dir() or not os.access(data_parent, os.W_OK):
        raise ValueError("database parent directory is unavailable")
    if not backup.is_dir() or not os.access(backup, os.W_OK) or backup == data_parent:
        raise ValueError("backup path must exist and be separate from the database directory")
    checks.extend(("persistent_database", "universe_config", "separate_backup_target"))
    return PreflightReport(True, tuple(checks))


def main() -> None:
    report = production_preflight(os.environ)
    print("Production infrastructure preflight: PASS")
    for check in report.checks:
        print(f"- {check}: PASS")
