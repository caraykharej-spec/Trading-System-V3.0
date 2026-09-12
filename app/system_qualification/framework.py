from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from time import monotonic
from typing import Callable


@dataclass(frozen=True)
class ScenarioObservation:
    passed: bool
    expected: str
    observed: str
    controls: tuple[str, ...] = ()


Scenario = Callable[[], ScenarioObservation]


@dataclass(frozen=True)
class QualificationCase:
    case_id: str
    category: str
    critical: bool
    scenario: Scenario


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    category: str
    critical: bool
    status: str
    expected: str
    observed: str
    controls: tuple[str, ...]
    duration_ms: int
    error_type: str | None = None


@dataclass(frozen=True)
class QualificationReport:
    status: str
    started_at: str
    finished_at: str
    cases: tuple[CaseResult, ...]
    passed: int
    failed: int
    critical_failed: int
    evidence_digest: str
    schema_version: int = 1
    scope: str = "CONTROLLED_OFFLINE_SYSTEM_QUALIFICATION"
    live_execution_attempted: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, indent=2)


class QualificationRunner:
    def __init__(self, cases: tuple[QualificationCase, ...]) -> None:
        ids = tuple(case.case_id for case in cases)
        if not cases or len(ids) != len(set(ids)):
            raise ValueError("qualification cases must be nonempty and uniquely identified")
        self.cases = cases

    def run(self) -> QualificationReport:
        started = datetime.now(timezone.utc)
        results: list[CaseResult] = []
        for case in self.cases:
            timer = monotonic()
            try:
                observation = case.scenario()
                result = CaseResult(
                    case.case_id,
                    case.category,
                    case.critical,
                    "PASS" if observation.passed else "FAIL",
                    observation.expected,
                    observation.observed,
                    observation.controls,
                    round((monotonic() - timer) * 1000),
                )
            except Exception as exc:
                result = CaseResult(
                    case.case_id,
                    case.category,
                    case.critical,
                    "FAIL",
                    "scenario completes with its safety invariant satisfied",
                    "scenario raised a sanitized exception",
                    (),
                    round((monotonic() - timer) * 1000),
                    type(exc).__name__,
                )
            results.append(result)
        finished = datetime.now(timezone.utc)
        passed = sum(result.status == "PASS" for result in results)
        failed = len(results) - passed
        critical_failed = sum(
            result.status == "FAIL" and result.critical for result in results
        )
        evidence_rows = []
        for result in results:
            row = asdict(result)
            row.pop("duration_ms")
            evidence_rows.append(row)
        evidence = json.dumps(evidence_rows, sort_keys=True, separators=(",", ":"))
        return QualificationReport(
            "PASS" if failed == 0 else "FAIL",
            started.isoformat(),
            finished.isoformat(),
            tuple(results),
            passed,
            failed,
            critical_failed,
            hashlib.sha256(evidence.encode()).hexdigest(),
        )
