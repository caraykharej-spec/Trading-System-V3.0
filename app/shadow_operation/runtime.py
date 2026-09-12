from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import signal
import sqlite3
from threading import Event
from typing import Mapping

from app.shadow_operation.repository import ShadowEvidenceRepository
from app.shadow_operation.service import PersistentShadowService
from app.shadow_validation.venue import build_shadow_validator


def build_service(env: Mapping[str, str]) -> tuple[PersistentShadowService, sqlite3.Connection]:
    database = Path(env.get("TRADING_SHADOW_DB_PATH", "data/shadow_evidence.sqlite3"))
    universe = Path(env.get("TRADING_UNIVERSE_PATH", "config/universe.json"))
    symbols = tuple(
        item.strip() for item in env.get("TRADING_SHADOW_SYMBOLS", "BTC/USDT").split(",")
        if item.strip()
    )
    try:
        interval = int(env.get("TRADING_SHADOW_INTERVAL_SECONDS", "1800"))
        lease = int(env.get("TRADING_SHADOW_LEASE_SECONDS", "3600"))
    except ValueError as exc:
        raise ValueError("shadow interval and lease must be integers") from exc
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    repository = ShadowEvidenceRepository(connection)
    return (
        PersistentShadowService(
            build_shadow_validator(universe), repository, symbols, interval, lease
        ),
        connection,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Persistent read-only shadow operation")
    parser.add_argument("command", choices=("once", "worker", "verify", "summary"))
    args = parser.parse_args()
    service, connection = build_service(os.environ)
    try:
        if args.command == "once":
            stored = service.run_once()
            print(json.dumps(asdict(stored) if stored else {"status": "SKIPPED_LEASED"}))
        elif args.command == "verify":
            valid = service.repository.verify_chain()
            print(json.dumps({"chain_valid": valid}))
            if not valid:
                raise SystemExit(1)
        elif args.command == "summary":
            print(json.dumps(asdict(service.repository.summary())))
        else:
            stop = Event()

            def request_stop(signum: int, frame: object) -> None:
                del signum, frame
                stop.set()

            signal.signal(signal.SIGTERM, request_stop)
            signal.signal(signal.SIGINT, request_stop)
            service.run_forever(stop)
    finally:
        connection.close()
