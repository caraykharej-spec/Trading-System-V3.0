from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from uuid import uuid4

from app.shadow_validation.validation import ShadowReport, fingerprint


@dataclass(frozen=True)
class StoredEvidence:
    sequence: int
    run_id: str
    observed_at: str
    status: str
    report_digest: str
    previous_chain_hash: str
    chain_hash: str


@dataclass(frozen=True)
class EvidenceSummary:
    total: int
    passed: int
    held: int
    failed: int
    qualified: int
    first_observed_at: str | None
    last_observed_at: str | None
    chain_valid: bool


class ShadowEvidenceRepository:
    """Append-only evidence ledger with a tamper-evident hash chain."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self.connection.execute("PRAGMA synchronous = FULL")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS shadow_evidence (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL UNIQUE,
                observed_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('PASS', 'HOLD', 'FAIL')),
                symbols_json TEXT NOT NULL,
                report_json TEXT NOT NULL,
                report_digest TEXT NOT NULL,
                previous_chain_hash TEXT NOT NULL,
                chain_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS shadow_worker_lease (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                owner TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def append(self, report: ShadowReport, *, run_id: str | None = None) -> StoredEvidence:
        identifier = run_id or uuid4().hex
        report_json = report.to_json()
        report_digest = fingerprint(json.loads(report_json))
        created_at = datetime.now(timezone.utc).isoformat()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT chain_hash FROM shadow_evidence ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous = str(row[0]) if row else "GENESIS"
            chain_hash = fingerprint(
                {
                    "run_id": identifier,
                    "observed_at": report.observed_at,
                    "report_digest": report_digest,
                    "previous_chain_hash": previous,
                }
            )
            cursor = self.connection.execute(
                """
                INSERT INTO shadow_evidence(
                    run_id, observed_at, status, symbols_json, report_json,
                    report_digest, previous_chain_hash, chain_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    report.observed_at,
                    report.status,
                    json.dumps(report.symbols),
                    report_json,
                    report_digest,
                    previous,
                    chain_hash,
                    created_at,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return an evidence sequence")
            self.connection.commit()
            return StoredEvidence(
                int(cursor.lastrowid), identifier, report.observed_at, report.status,
                report_digest, previous, chain_hash,
            )
        except Exception:
            self.connection.rollback()
            raise

    def acquire_lease(self, owner: str, now: datetime, ttl: timedelta) -> bool:
        if not owner or now.tzinfo is None or ttl.total_seconds() <= 0:
            raise ValueError("lease requires owner, aware time and positive TTL")
        current = now.astimezone(timezone.utc)
        expires = (current + ttl).isoformat()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT owner, expires_at FROM shadow_worker_lease WHERE singleton = 1"
            ).fetchone()
            available = row is None or datetime.fromisoformat(str(row[1])) <= current
            if available:
                self.connection.execute(
                    """
                    INSERT INTO shadow_worker_lease(singleton, owner, expires_at)
                    VALUES (1, ?, ?)
                    ON CONFLICT(singleton) DO UPDATE SET owner=excluded.owner,
                        expires_at=excluded.expires_at
                    """,
                    (owner, expires),
                )
            self.connection.commit()
            return available
        except Exception:
            self.connection.rollback()
            raise

    def release_lease(self, owner: str) -> None:
        self.connection.execute(
            "DELETE FROM shadow_worker_lease WHERE singleton = 1 AND owner = ?", (owner,)
        )
        self.connection.commit()

    def verify_chain(self) -> bool:
        previous = "GENESIS"
        rows = self.connection.execute(
            """SELECT run_id, observed_at, report_json, report_digest,
                      previous_chain_hash, chain_hash
               FROM shadow_evidence ORDER BY sequence"""
        ).fetchall()
        for run_id, observed_at, report_json, stored_digest, stored_previous, chain_hash in rows:
            digest = fingerprint(json.loads(str(report_json)))
            expected = fingerprint(
                {
                    "run_id": str(run_id),
                    "observed_at": str(observed_at),
                    "report_digest": digest,
                    "previous_chain_hash": previous,
                }
            )
            if digest != stored_digest or stored_previous != previous or chain_hash != expected:
                return False
            previous = str(chain_hash)
        return True

    def summary(self) -> EvidenceSummary:
        rows = self.connection.execute(
            "SELECT status, observed_at, report_json FROM shadow_evidence ORDER BY sequence"
        ).fetchall()
        counts = {"PASS": 0, "HOLD": 0, "FAIL": 0}
        qualified = 0
        for status, _, report_json in rows:
            counts[str(status)] += 1
            report = json.loads(str(report_json))
            decisions = report.get("decisions") or {}
            qualified += len(decisions.get("qualified") or [])
        return EvidenceSummary(
            len(rows), counts["PASS"], counts["HOLD"], counts["FAIL"], qualified,
            str(rows[0][1]) if rows else None,
            str(rows[-1][1]) if rows else None,
            self.verify_chain(),
        )
