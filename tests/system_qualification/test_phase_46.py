from __future__ import annotations

import json

import pytest

from app.system_qualification.framework import (
    QualificationCase,
    QualificationRunner,
    ScenarioObservation,
)
from app.system_qualification.scenarios import default_cases, run_default_qualification


def test_complete_default_failure_matrix_passes_without_live_execution() -> None:
    report = run_default_qualification()
    assert report.status == "PASS"
    assert report.passed == len(default_cases()) == 9
    assert report.failed == report.critical_failed == 0
    assert report.live_execution_attempted is False
    assert len(report.evidence_digest) == 64
    categories = {case.category for case in report.cases}
    assert categories == {"market_data", "atomicity", "live_safety", "evidence", "recovery", "security"}


def test_report_is_machine_readable_and_contains_expected_observed_controls() -> None:
    first = run_default_qualification()
    second = run_default_qualification()
    payload = json.loads(first.to_json())
    assert payload["scope"] == "CONTROLLED_OFFLINE_SYSTEM_QUALIFICATION"
    assert all(case["expected"] and case["observed"] for case in payload["cases"])
    assert all(case["controls"] for case in payload["cases"])
    assert first.evidence_digest == second.evidence_digest


def test_scenario_failure_fails_report() -> None:
    runner = QualificationRunner(
        (
            QualificationCase(
                "FAIL", "test", True,
                lambda: ScenarioObservation(False, "blocked", "accepted"),
            ),
        )
    )
    report = runner.run()
    assert report.status == "FAIL"
    assert report.critical_failed == 1


def test_exception_is_sanitized_to_type() -> None:
    def explode() -> ScenarioObservation:
        raise RuntimeError("credential=value-that-must-not-appear")

    report = QualificationRunner(
        (QualificationCase("EXCEPTION", "test", True, explode),)
    ).run()
    result = report.cases[0]
    assert result.status == "FAIL"
    assert result.error_type == "RuntimeError"
    assert "credential" not in report.to_json()


@pytest.mark.parametrize(
    "cases",
    [
        (),
        (
            QualificationCase("DUPLICATE", "test", True, lambda: ScenarioObservation(True, "x", "x")),
            QualificationCase("DUPLICATE", "test", True, lambda: ScenarioObservation(True, "x", "x")),
        ),
    ],
)
def test_case_registry_requires_nonempty_unique_ids(cases: tuple[QualificationCase, ...]) -> None:
    with pytest.raises(ValueError):
        QualificationRunner(cases)
