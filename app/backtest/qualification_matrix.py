from __future__ import annotations

import hashlib
import itertools
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class MatrixDimensions:
    dataset_versions: tuple[str, ...]
    splits: tuple[str, ...]
    seeds: tuple[int, ...]
    strategy_fingerprints: tuple[str, ...]
    config_fingerprints: tuple[str, ...]
    cost_scenarios: tuple[str, ...]

    def __post_init__(self) -> None:
        values = (
            self.dataset_versions,
            self.splits,
            self.seeds,
            self.strategy_fingerprints,
            self.config_fingerprints,
            self.cost_scenarios,
        )
        if any(not value for value in values):
            raise ValueError("all matrix dimensions must be non-empty")
        if len(set(self.seeds)) != len(self.seeds) or any(seed < 0 for seed in self.seeds):
            raise ValueError("matrix seeds must be unique and non-negative")


@dataclass(frozen=True)
class MatrixRun:
    index: int
    dataset_version: str
    split: str
    seed: int
    strategy_fingerprint: str
    config_fingerprint: str
    cost_scenario: str
    experiment_sha256: str


@dataclass(frozen=True)
class MatrixRunResult:
    run: MatrixRun
    status: str
    result_sha256: str | None
    error: str | None


@dataclass(frozen=True)
class MatrixExecutionReport:
    expected_runs: int
    completed_runs: int
    successful_runs: int
    failed_runs: int
    matrix_sha256: str
    evidence_sha256: str
    results: tuple[MatrixRunResult, ...]


RunExecutor = Callable[[MatrixRun], bytes]


def _sha(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_matrix(
    dimensions: MatrixDimensions,
    *,
    expected_runs: int = 1000,
) -> tuple[MatrixRun, ...]:
    if expected_runs < 1:
        raise ValueError("expected_runs must be positive")
    combinations = tuple(
        itertools.product(
            dimensions.dataset_versions,
            dimensions.splits,
            dimensions.seeds,
            dimensions.strategy_fingerprints,
            dimensions.config_fingerprints,
            dimensions.cost_scenarios,
        )
    )
    if len(combinations) != expected_runs:
        raise ValueError(
            f"matrix cardinality mismatch:{len(combinations)}!={expected_runs}"
        )
    runs = []
    for index, values in enumerate(combinations):
        dataset, split, seed, strategy, config, cost = values
        identity = {
            "config": config,
            "cost": cost,
            "dataset": dataset,
            "seed": seed,
            "split": split,
            "strategy": strategy,
        }
        runs.append(
            MatrixRun(
                index,
                dataset,
                split,
                seed,
                strategy,
                config,
                cost,
                _sha(identity),
            )
        )
    identities = {item.experiment_sha256 for item in runs}
    if len(identities) != len(runs):
        raise ValueError("matrix contains duplicate experiment identities")
    return tuple(runs)


def execute_matrix(
    runs: tuple[MatrixRun, ...],
    executor: RunExecutor,
    *,
    expected_runs: int = 1000,
    max_workers: int = 8,
) -> MatrixExecutionReport:
    if len(runs) != expected_runs:
        raise ValueError(f"run count mismatch:{len(runs)}!={expected_runs}")
    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    if tuple(item.index for item in runs) != tuple(range(len(runs))):
        raise ValueError("matrix indexes must be contiguous and ordered")
    if len({item.experiment_sha256 for item in runs}) != len(runs):
        raise ValueError("matrix experiment identities must be unique")

    def execute(run: MatrixRun) -> MatrixRunResult:
        try:
            output = executor(run)
            if not isinstance(output, bytes):
                raise TypeError("matrix executor must return canonical bytes")
            return MatrixRunResult(
                run, "SUCCESS", hashlib.sha256(output).hexdigest(), None
            )
        except Exception as exc:
            return MatrixRunResult(
                run,
                "FAILED",
                None,
                f"{exc.__class__.__name__}:{str(exc)}",
            )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = tuple(pool.map(execute, runs))
    successful = sum(item.status == "SUCCESS" for item in results)
    matrix_hash = _sha([item.experiment_sha256 for item in runs])
    evidence_hash = _sha(
        [
            {
                "experiment": item.run.experiment_sha256,
                "result": item.result_sha256,
                "status": item.status,
                "error": item.error,
            }
            for item in results
        ]
    )
    return MatrixExecutionReport(
        expected_runs,
        len(results),
        successful,
        len(results) - successful,
        matrix_hash,
        evidence_hash,
        results,
    )
