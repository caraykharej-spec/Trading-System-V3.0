from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
from threading import Event

import pytest

from app.shadow_operation.repository import ShadowEvidenceRepository
from app.shadow_operation.service import PersistentShadowService
from app.shadow_validation.validation import ShadowReport

NOW = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)


class Validator:
    def __init__(self, report: ShadowReport | None = None, error: Exception | None = None) -> None:
        self.report = report or ShadowReport(
            "PASS", NOW.isoformat(), ("BTC/USDT",),
            ({"kind": "replay", "status": "PASS"},),
            decisions={"qualified": [{"symbol": "BTC/USDT"}]},
        )
        self.error = error
        self.calls = 0

    def run(self, symbols: tuple[str, ...]) -> ShadowReport:
        self.calls += 1
        if self.error:
            raise self.error
        assert symbols == self.report.symbols
        return self.report


def repository() -> ShadowEvidenceRepository:
    return ShadowEvidenceRepository(sqlite3.connect(":memory:"))


def test_append_only_chain_and_longitudinal_summary() -> None:
    repo = repository()
    first = repo.append(Validator().report, run_id="run-1")
    held = ShadowReport("HOLD", (NOW + timedelta(minutes=30)).isoformat(),
                        ("BTC/USDT",), ({"status": "HOLD"},))
    second = repo.append(held, run_id="run-2")
    assert first.previous_chain_hash == "GENESIS"
    assert second.previous_chain_hash == first.chain_hash
    assert repo.verify_chain()
    summary = repo.summary()
    assert (summary.total, summary.passed, summary.held, summary.failed) == (2, 1, 1, 0)
    assert summary.qualified == 1
    assert summary.chain_valid


def test_duplicate_run_id_is_rejected_without_partial_append() -> None:
    repo = repository()
    repo.append(Validator().report, run_id="same")
    with pytest.raises(sqlite3.IntegrityError):
        repo.append(Validator().report, run_id="same")
    assert repo.summary().total == 1


def test_tampering_is_detected() -> None:
    repo = repository()
    stored = repo.append(Validator().report)
    repo.connection.execute(
        "UPDATE shadow_evidence SET report_json = '{}' WHERE sequence = ?",
        (stored.sequence,),
    )
    repo.connection.commit()
    assert not repo.verify_chain()


def test_lease_excludes_overlap_and_can_expire() -> None:
    repo = repository()
    assert repo.acquire_lease("one", NOW, timedelta(minutes=5))
    assert not repo.acquire_lease("two", NOW, timedelta(minutes=5))
    assert repo.acquire_lease("two", NOW + timedelta(minutes=6), timedelta(minutes=5))
    repo.release_lease("one")
    assert not repo.acquire_lease("three", NOW + timedelta(minutes=6), timedelta(minutes=5))
    repo.release_lease("two")
    assert repo.acquire_lease("three", NOW + timedelta(minutes=6), timedelta(minutes=5))


def test_service_persists_pass_hold_and_sanitized_failure() -> None:
    repo = repository()
    service = PersistentShadowService(
        Validator(), repo, ("BTC/USDT",), clock=lambda: NOW
    )
    assert service.run_once().status == "PASS"
    held = ShadowReport("HOLD", NOW.isoformat(), ("BTC/USDT",), ({"status": "HOLD"},))
    service.validator = Validator(held)  # type: ignore[assignment]
    assert service.run_once().status == "HOLD"
    service.validator = Validator(error=RuntimeError("secret detail"))  # type: ignore[assignment]
    assert service.run_once().status == "FAIL"
    row = repo.connection.execute(
        "SELECT report_json FROM shadow_evidence ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    assert "RuntimeError" in row[0]
    assert "secret detail" not in row[0]


def test_service_skips_when_another_worker_holds_lease() -> None:
    repo = repository()
    assert repo.acquire_lease("other", NOW, timedelta(minutes=5))
    validator = Validator()
    service = PersistentShadowService(validator, repo, ("BTC/USDT",), clock=lambda: NOW)
    assert service.run_once() is None
    assert validator.calls == 0


def test_worker_stops_without_an_extra_cycle() -> None:
    stop = Event()
    stop.set()
    validator = Validator()
    PersistentShadowService(
        validator, repository(), ("BTC/USDT",), clock=lambda: NOW
    ).run_forever(stop)
    assert validator.calls == 0


@pytest.mark.parametrize(
    ("interval", "lease"), ((59, 120), (86_401, 100_000), (1800, 1799), (1800, 3601))
)
def test_schedule_bounds(interval: int, lease: int) -> None:
    with pytest.raises(ValueError):
        PersistentShadowService(
            Validator(), repository(), ("BTC/USDT",), interval, lease
        )
