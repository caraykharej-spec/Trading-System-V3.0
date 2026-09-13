from dataclasses import replace\n\nimport pytest

from app.backtest.qualification_matrix import (
    MatrixDimensions,
    build_matrix,
    execute_matrix,
)


def dimensions() -> MatrixDimensions:
    return MatrixDimensions(
        dataset_versions=tuple(f"dataset-{index}" for index in range(5)),
        splits=("OOS", "WALK_FORWARD"),
        seeds=tuple(range(10)),
        strategy_fingerprints=("strategy-sha",),
        config_fingerprints=tuple(f"config-{index}" for index in range(5)),
        cost_scenarios=("baseline", "stress"),
    )


def test_exactly_one_thousand_runs_are_unique_and_reproducible():
    first = build_matrix(dimensions())
    second = build_matrix(dimensions())

    assert len(first) == 1000
    assert first == second
    assert len({item.experiment_sha256 for item in first}) == 1000

    first_report = execute_matrix(
        first,
        lambda item: item.experiment_sha256.encode(),
        max_workers=4,
    )
    second_report = execute_matrix(
        second,
        lambda item: item.experiment_sha256.encode(),
        max_workers=2,
    )

    assert first_report.completed_runs == 1000
    assert first_report.successful_runs == 1000
    assert first_report.matrix_sha256 == second_report.matrix_sha256
    assert first_report.evidence_sha256 == second_report.evidence_sha256


def test_failed_runs_are_retained_in_evidence():
    runs = build_matrix(dimensions())

    def execute(item):
        if item.seed == 0:
            raise RuntimeError("synthetic failure")
        return b"ok"

    report = execute_matrix(runs, execute)

    assert report.completed_runs == 1000
    assert report.successful_runs == 900
    assert report.failed_runs == 100
    assert all(
        item.error == "RuntimeError:synthetic failure"
        for item in report.results
        if item.status == "FAILED"
    )


def test_matrix_cardinality_must_match_locked_run_count():
    with pytest.raises(ValueError, match="cardinality"):
        build_matrix(
            MatrixDimensions(
                ("dataset",),
                ("OOS",),
                (1,),
                ("strategy",),
                ("config",),
                ("baseline",),
            )
        )


def test_executor_must_return_canonical_bytes():
    runs = build_matrix(dimensions())
    report = execute_matrix(runs, lambda item: "not-bytes")

    assert report.failed_runs == 1000
    assert report.results[0].error == (
        "TypeError:matrix executor must return canonical bytes"
    )


def test_forged_experiment_identity_fails_closed():
    runs = build_matrix(dimensions())
    forged = (replace(runs[0], dataset_version="forged"), *runs[1:])

    with pytest.raises(ValueError, match="identity is invalid"):
        execute_matrix(forged, lambda item: b"result")


def test_oversized_cardinality_is_rejected_before_product_materialization():
    huge = tuple(str(index) for index in range(100))

    with pytest.raises(ValueError, match="1000000000000"):
        build_matrix(
            MatrixDimensions(huge, huge, tuple(range(100)), huge, huge, huge)
        )
