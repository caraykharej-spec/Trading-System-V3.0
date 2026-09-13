from decimal import Decimal

import pytest

from app.backtest.final_qualification import (
    FinalQualificationDecision,
    PhaseEvidence,
    QualificationIdentity,
    qualify_phase_48,
    render_statistical_report,
)
from app.backtest.qualification_batch import (
    BatchDecision,
    BatchQualificationReport,
)


def _identity() -> QualificationIdentity:
    return QualificationIdentity(
        dataset_version="dataset-v1",
        strategy_fingerprint="strategy-sha256",
        config_fingerprint="config-sha256",
        code_revision="a" * 40,
    )


def _fingerprint(index: int) -> str:
    return f"{index:064x}"


def _evidence(*, failed_phase: str | None = None) -> tuple[PhaseEvidence, ...]:
    return tuple(
        PhaseEvidence(
            phase_id=f"48.{index}",
            passed=f"48.{index}" != failed_phase,
            evidence_fingerprint=_fingerprint(index),
            evidence_count=index,
        )
        for index in range(1, 9)
    )


def _batch(
    *,
    decision: BatchDecision = BatchDecision.QUALIFIED,
    ci_low: str = "1",
) -> BatchQualificationReport:
    return BatchQualificationReport(
        decision=decision,
        run_count=1000,
        is_run_count=500,
        oos_run_count=500,
        total_trades=5000,
        win_rate_percent=Decimal("60"),
        profit_factor=Decimal("1.6"),
        mean_expectancy=Decimal("2"),
        aggregate_expectancy=Decimal("2"),
        expectancy_ci95_low=Decimal(ci_low),
        expectancy_ci95_high=Decimal("3"),
        p95_drawdown_percent=Decimal("10"),
        reasons=(),
    )


def test_complete_phase_evidence_and_statistics_qualify_reproducibly():
    first = qualify_phase_48(_identity(), _evidence(), _batch())
    second = qualify_phase_48(
        _identity(), tuple(reversed(_evidence())), _batch()
    )

    assert first.decision is FinalQualificationDecision.QUALIFIED
    assert first.passed is True
    assert first == second
    assert tuple(item.phase_id for item in first.phase_evidence) == tuple(
        f"48.{index}" for index in range(1, 9)
    )
    assert len(first.manifest_fingerprint) == 64


def test_missing_phase_evidence_fails_closed():
    report = qualify_phase_48(_identity(), _evidence()[:-1], _batch())

    assert report.decision is FinalQualificationDecision.INCOMPLETE_EVIDENCE
    assert "48.8" in report.reasons[0]


def test_failed_phase_evidence_blocks_final_qualification():
    report = qualify_phase_48(
        _identity(), _evidence(failed_phase="48.6"), _batch()
    )

    assert report.decision is FinalQualificationDecision.FAILED_PHASE_EVIDENCE
    assert "48.6" in report.reasons[0]


def test_nonqualified_batch_blocks_final_qualification():
    report = qualify_phase_48(
        _identity(),
        _evidence(),
        _batch(decision=BatchDecision.OVERFIT_SUSPECTED),
    )

    assert (
        report.decision
        is FinalQualificationDecision.FAILED_STATISTICAL_QUALIFICATION
    )
    assert "OVERFIT_SUSPECTED" in report.reasons[0]


def test_inconsistent_forged_qualified_batch_is_rejected_by_final_gates():
    report = qualify_phase_48(_identity(), _evidence(), _batch(ci_low="-1"))

    assert (
        report.decision
        is FinalQualificationDecision.FAILED_STATISTICAL_QUALIFICATION
    )
    assert any("confidence lower bound" in reason for reason in report.reasons)


def test_duplicate_and_unknown_phase_ids_are_rejected():
    duplicate = (*_evidence()[:-1], _evidence()[0])
    with pytest.raises(ValueError, match="must be unique"):
        qualify_phase_48(_identity(), duplicate, _batch())

    unknown = (*_evidence(), PhaseEvidence("48.10", True, "f" * 64))
    with pytest.raises(ValueError, match="unknown Phase 48"):
        qualify_phase_48(_identity(), unknown, _batch())


def test_evidence_fingerprint_must_be_canonical_sha256():
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        PhaseEvidence("48.1", True, "ABC")


def test_git_revision_must_be_full_lowercase_sha():
    with pytest.raises(ValueError, match="40-character lowercase Git SHA"):
        QualificationIdentity(
            dataset_version="v1",
            strategy_fingerprint="strategy",
            config_fingerprint="config",
            code_revision="ABC",
        )


def test_manifest_changes_when_identity_or_evidence_changes():
    baseline = qualify_phase_48(_identity(), _evidence(), _batch())
    changed_identity = QualificationIdentity(
        dataset_version="dataset-v2",
        strategy_fingerprint="strategy-sha256",
        config_fingerprint="config-sha256",
        code_revision="a" * 40,
    )
    changed = qualify_phase_48(changed_identity, _evidence(), _batch())

    assert baseline.manifest_fingerprint != changed.manifest_fingerprint


def test_markdown_report_contains_identity_statistics_and_phase_manifest():
    report = qualify_phase_48(_identity(), _evidence(), _batch())
    rendered = render_statistical_report(report)

    assert "# Phase 48 Final Statistical Qualification" in rendered
    assert "**Decision:** QUALIFIED" in rendered
    assert "Runs: 1000" in rendered
    assert "| 48.8 | YES |" in rendered
    assert report.manifest_fingerprint in rendered


def test_non_finite_batch_metrics_are_rejected():
    invalid = BatchQualificationReport(
        **{**_batch().__dict__, "aggregate_expectancy": Decimal("Infinity")}
    )
    with pytest.raises(ValueError, match="must be finite"):
        qualify_phase_48(_identity(), _evidence(), invalid)
