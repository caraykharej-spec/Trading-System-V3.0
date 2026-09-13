from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.backtest.qualification_batch import (
    BatchDecision,
    BatchQualificationReport,
)

REQUIRED_PHASES = (
    "48.1",
    "48.2",
    "48.3",
    "48.4",
    "48.5",
    "48.6",
    "48.7",
    "48.8",
)


class FinalQualificationDecision(str, Enum):
    QUALIFIED = "QUALIFIED"
    INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
    FAILED_PHASE_EVIDENCE = "FAILED_PHASE_EVIDENCE"
    FAILED_STATISTICAL_QUALIFICATION = "FAILED_STATISTICAL_QUALIFICATION"


@dataclass(frozen=True)
class QualificationIdentity:
    dataset_version: str
    strategy_fingerprint: str
    config_fingerprint: str
    code_revision: str

    def __post_init__(self) -> None:
        if not self.dataset_version.strip():
            raise ValueError("dataset_version must be non-empty")
        if not self.strategy_fingerprint.strip():
            raise ValueError("strategy_fingerprint must be non-empty")
        if not self.config_fingerprint.strip():
            raise ValueError("config_fingerprint must be non-empty")
        if not _is_lower_hex(self.code_revision, length=40):
            raise ValueError("code_revision must be a 40-character lowercase Git SHA")


@dataclass(frozen=True)
class PhaseEvidence:
    phase_id: str
    passed: bool
    evidence_fingerprint: str
    evidence_count: int = 1

    def __post_init__(self) -> None:
        if not self.phase_id.strip():
            raise ValueError("phase_id must be non-empty")
        if not _is_lower_hex(self.evidence_fingerprint, length=64):
            raise ValueError(
                "evidence_fingerprint must be a 64-character lowercase SHA-256"
            )
        if self.evidence_count < 1:
            raise ValueError("evidence_count must be positive")


@dataclass(frozen=True)
class FinalQualificationPolicy:
    minimum_runs: int = 1000
    minimum_is_runs: int = 200
    minimum_oos_runs: int = 200
    minimum_total_trades: int = 1000
    minimum_profit_factor: Decimal = Decimal("1.10")
    maximum_p95_drawdown_percent: Decimal = Decimal("25")

    def __post_init__(self) -> None:
        counts = (
            self.minimum_runs,
            self.minimum_is_runs,
            self.minimum_oos_runs,
            self.minimum_total_trades,
        )
        if any(value < 1 for value in counts):
            raise ValueError("final qualification minimum counts must be positive")
        decimals = (
            self.minimum_profit_factor,
            self.maximum_p95_drawdown_percent,
        )
        if any(not value.is_finite() for value in decimals):
            raise ValueError("final qualification thresholds must be finite")
        if self.minimum_profit_factor <= 0:
            raise ValueError("minimum_profit_factor must be positive")
        if self.maximum_p95_drawdown_percent < 0:
            raise ValueError("maximum_p95_drawdown_percent must be non-negative")


@dataclass(frozen=True)
class FinalQualificationReport:
    identity: QualificationIdentity
    decision: FinalQualificationDecision
    phase_evidence: tuple[PhaseEvidence, ...]
    batch_report: BatchQualificationReport
    reasons: tuple[str, ...]
    manifest_fingerprint: str

    @property
    def passed(self) -> bool:
        return self.decision is FinalQualificationDecision.QUALIFIED


def _is_lower_hex(value: str, *, length: int) -> bool:
    return (
        len(value) == length
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _validate_batch_metrics(report: BatchQualificationReport) -> None:
    decimal_metrics = (
        report.win_rate_percent,
        report.profit_factor,
        report.mean_expectancy,
        report.aggregate_expectancy,
        report.expectancy_ci95_low,
        report.expectancy_ci95_high,
        report.p95_drawdown_percent,
    )
    if any(value is not None and not value.is_finite() for value in decimal_metrics):
        raise ValueError("batch qualification metrics must be finite")
    counts = (
        report.run_count,
        report.is_run_count,
        report.oos_run_count,
        report.total_trades,
    )
    if any(value < 0 for value in counts):
        raise ValueError("batch qualification counts must be non-negative")


def _statistical_gate_reasons(
    report: BatchQualificationReport,
    policy: FinalQualificationPolicy,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if report.decision is not BatchDecision.QUALIFIED:
        reasons.append(f"batch decision is {report.decision.value}, not QUALIFIED")
    if report.run_count < policy.minimum_runs:
        reasons.append("minimum 1000-run qualification evidence not met")
    if report.is_run_count < policy.minimum_is_runs:
        reasons.append("minimum in-sample run count not met")
    if report.oos_run_count < policy.minimum_oos_runs:
        reasons.append("minimum OOS/walk-forward run count not met")
    if report.total_trades < policy.minimum_total_trades:
        reasons.append("minimum OOS trade sample not met")
    if (
        report.profit_factor is None
        or report.profit_factor < policy.minimum_profit_factor
    ):
        reasons.append("profit factor is below final qualification policy")
    if report.aggregate_expectancy is None or report.aggregate_expectancy <= 0:
        reasons.append("aggregate OOS expectancy is not positive")
    if report.expectancy_ci95_low is None or report.expectancy_ci95_low <= 0:
        reasons.append("95% expectancy confidence lower bound is not positive")
    if report.p95_drawdown_percent > policy.maximum_p95_drawdown_percent:
        reasons.append("p95 drawdown exceeds final qualification policy")
    return tuple(reasons)


def _manifest_fingerprint(
    *,
    identity: QualificationIdentity,
    decision: FinalQualificationDecision,
    evidence: tuple[PhaseEvidence, ...],
    batch_report: BatchQualificationReport,
    policy: FinalQualificationPolicy,
    reasons: tuple[str, ...],
) -> str:
    payload = {
        "schema": "phase-48.9-final-qualification-v1",
        "identity": {
            "dataset_version": identity.dataset_version,
            "strategy_fingerprint": identity.strategy_fingerprint,
            "config_fingerprint": identity.config_fingerprint,
            "code_revision": identity.code_revision,
        },
        "decision": decision.value,
        "required_phases": list(REQUIRED_PHASES),
        "phase_evidence": [
            {
                "phase_id": item.phase_id,
                "passed": item.passed,
                "evidence_fingerprint": item.evidence_fingerprint,
                "evidence_count": item.evidence_count,
            }
            for item in evidence
        ],
        "batch_report": {
            "decision": batch_report.decision.value,
            "run_count": batch_report.run_count,
            "is_run_count": batch_report.is_run_count,
            "oos_run_count": batch_report.oos_run_count,
            "total_trades": batch_report.total_trades,
            "win_rate_percent": _decimal_text(batch_report.win_rate_percent),
            "profit_factor": _decimal_text(batch_report.profit_factor),
            "mean_expectancy": _decimal_text(batch_report.mean_expectancy),
            "aggregate_expectancy": _decimal_text(
                batch_report.aggregate_expectancy
            ),
            "expectancy_ci95_low": _decimal_text(batch_report.expectancy_ci95_low),
            "expectancy_ci95_high": _decimal_text(
                batch_report.expectancy_ci95_high
            ),
            "p95_drawdown_percent": _decimal_text(
                batch_report.p95_drawdown_percent
            ),
            "reasons": list(batch_report.reasons),
        },
        "policy": {
            "minimum_runs": policy.minimum_runs,
            "minimum_is_runs": policy.minimum_is_runs,
            "minimum_oos_runs": policy.minimum_oos_runs,
            "minimum_total_trades": policy.minimum_total_trades,
            "minimum_profit_factor": _decimal_text(policy.minimum_profit_factor),
            "maximum_p95_drawdown_percent": _decimal_text(
                policy.maximum_p95_drawdown_percent
            ),
        },
        "reasons": list(reasons),
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def qualify_phase_48(
    identity: QualificationIdentity,
    phase_evidence: tuple[PhaseEvidence, ...],
    batch_report: BatchQualificationReport,
    *,
    policy: FinalQualificationPolicy = FinalQualificationPolicy(),
) -> FinalQualificationReport:
    _validate_batch_metrics(batch_report)
    phase_ids = [item.phase_id for item in phase_evidence]
    if len(set(phase_ids)) != len(phase_ids):
        raise ValueError("phase evidence IDs must be unique")
    unknown = sorted(set(phase_ids) - set(REQUIRED_PHASES))
    if unknown:
        raise ValueError(f"unknown Phase 48 evidence IDs: {', '.join(unknown)}")

    by_phase = {item.phase_id: item for item in phase_evidence}
    ordered = tuple(by_phase[phase] for phase in REQUIRED_PHASES if phase in by_phase)
    missing = tuple(phase for phase in REQUIRED_PHASES if phase not in by_phase)
    failed = tuple(item.phase_id for item in ordered if not item.passed)
    statistical_reasons = _statistical_gate_reasons(batch_report, policy)

    reasons: list[str] = []
    if missing:
        decision = FinalQualificationDecision.INCOMPLETE_EVIDENCE
        reasons.append(f"missing phase evidence: {', '.join(missing)}")
    elif failed:
        decision = FinalQualificationDecision.FAILED_PHASE_EVIDENCE
        reasons.append(f"failed phase evidence: {', '.join(failed)}")
    elif statistical_reasons:
        decision = FinalQualificationDecision.FAILED_STATISTICAL_QUALIFICATION
        reasons.extend(statistical_reasons)
    else:
        decision = FinalQualificationDecision.QUALIFIED

    reason_tuple = tuple(reasons)
    fingerprint = _manifest_fingerprint(
        identity=identity,
        decision=decision,
        evidence=ordered,
        batch_report=batch_report,
        policy=policy,
        reasons=reason_tuple,
    )
    return FinalQualificationReport(
        identity=identity,
        decision=decision,
        phase_evidence=ordered,
        batch_report=batch_report,
        reasons=reason_tuple,
        manifest_fingerprint=fingerprint,
    )


def render_statistical_report(report: FinalQualificationReport) -> str:
    batch = report.batch_report
    lines = [
        "# Phase 48 Final Statistical Qualification",
        "",
        f"**Decision:** {report.decision.value}",
        f"**Manifest fingerprint:** `{report.manifest_fingerprint}`",
        "",
        "## Qualification Identity",
        "",
        f"- Dataset version: `{report.identity.dataset_version}`",
        f"- Strategy fingerprint: `{report.identity.strategy_fingerprint}`",
        f"- Config fingerprint: `{report.identity.config_fingerprint}`",
        f"- Code revision: `{report.identity.code_revision}`",
        "",
        "## Statistical Summary",
        "",
        f"- Batch decision: `{batch.decision.value}`",
        f"- Runs: {batch.run_count} (IS {batch.is_run_count}, OOS/WF {batch.oos_run_count})",
        f"- OOS trades: {batch.total_trades}",
        f"- Profit factor: {_decimal_text(batch.profit_factor)}",
        f"- Aggregate expectancy: {_decimal_text(batch.aggregate_expectancy)}",
        (
            "- Expectancy 95% CI: "
            f"[{_decimal_text(batch.expectancy_ci95_low)}, "
            f"{_decimal_text(batch.expectancy_ci95_high)}]"
        ),
        f"- P95 drawdown: {_decimal_text(batch.p95_drawdown_percent)}%",
        "",
        "## Phase Evidence",
        "",
        "| Phase | PASS | Evidence Count | Fingerprint |",
        "| --- | --- | ---: | --- |",
    ]
    lines.extend(
        f"| {item.phase_id} | {'YES' if item.passed else 'NO'} | "
        f"{item.evidence_count} | `{item.evidence_fingerprint}` |"
        for item in report.phase_evidence
    )
    lines.extend(("", "## Reasons", ""))
    if report.reasons:
        lines.extend(f"- {reason}" for reason in report.reasons)
    else:
        lines.append("- All required Phase 48 evidence and statistical gates passed.")
    return "\n".join(lines) + "\n"
