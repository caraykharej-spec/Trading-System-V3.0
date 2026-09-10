from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal
from hashlib import sha256
from typing import Callable, Protocol

from app.backtest.models import BacktestResult

from .models import (
    DatasetRole,
    ExperimentResult,
    ExperimentSpec,
    ParameterSensitivity,
    ParameterSet,
    ResearchTrial,
    TrialStatus,
)
from .objectives import better, constraint_failure, objective_value
from .parameter_space import ParameterSpace

ResearchEvaluator = Callable[[ParameterSet, int, DatasetRole], BacktestResult]


class ResearchRegistry(Protocol):
    def save(self, result: ExperimentResult) -> bool: ...


def _parameter_payload(parameters: ParameterSet) -> dict[str, str]:
    return {
        name: f"{type(value).__name__}:{value}"
        for name, value in parameters.values
    }


def _fingerprint(spec: ExperimentSpec, space: ParameterSpace) -> str:
    payload = {
        "experiment_id": spec.experiment_id,
        "strategy_version": spec.strategy_version,
        "data_version": spec.data_version,
        "seed": spec.seed,
        "search_method": spec.search_method.value,
        "max_trials": spec.max_trials,
        "objective_metric": spec.objective_metric.value,
        "objective_direction": spec.objective_direction.value,
        "constraints": {
            "min_trades": spec.constraints.min_trades,
            "max_drawdown_percent": (
                str(spec.constraints.max_drawdown_percent)
                if spec.constraints.max_drawdown_percent is not None
                else None
            ),
            "min_profit_factor": (
                str(spec.constraints.min_profit_factor)
                if spec.constraints.min_profit_factor is not None
                else None
            ),
            "min_total_return_percent": (
                str(spec.constraints.min_total_return_percent)
                if spec.constraints.min_total_return_percent is not None
                else None
            ),
        },
        "parameter_space": space.fingerprint,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _trial_seed(base_seed: int, parameters: ParameterSet) -> int:
    encoded = json.dumps(_parameter_payload(parameters), sort_keys=True, separators=(",", ":"))
    digest = sha256(f"{base_seed}:{encoded}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _sensitivity(
    trials: tuple[ResearchTrial, ...], *, maximize: bool
) -> tuple[ParameterSensitivity, ...]:
    buckets: dict[tuple[str, str], list[Decimal]] = defaultdict(list)
    for trial in trials:
        if trial.status is not TrialStatus.COMPLETED or trial.validation_objective is None:
            continue
        for name, value in trial.parameters.values:
            buckets[(name, f"{type(value).__name__}:{value}")].append(
                trial.validation_objective
            )
    rows: list[ParameterSensitivity] = []
    for (name, value), scores in sorted(buckets.items()):
        best_score = max(scores) if maximize else min(scores)
        rows.append(
            ParameterSensitivity(
                parameter=name,
                value=value,
                observations=len(scores),
                average_validation_objective=sum(scores, Decimal("0")) / Decimal(len(scores)),
                best_validation_objective=best_score,
            )
        )
    return tuple(rows)


class ResearchRunner:
    """Controlled parameter research with a sealed final OOS evaluation.

    Every candidate is evaluated on TRAIN and VALIDATION. Selection uses validation
    objective only, with train objective as a deterministic tie-breaker. OOS is
    evaluated exactly once for the selected candidate and never influences selection.
    """

    def __init__(
        self,
        evaluator: ResearchEvaluator,
        registry: ResearchRegistry | None = None,
    ) -> None:
        self._evaluator = evaluator
        self._registry = registry

    def run(self, spec: ExperimentSpec, space: ParameterSpace) -> ExperimentResult:
        candidates = space.candidates(
            method=spec.search_method,
            seed=spec.seed,
            max_trials=spec.max_trials,
        )
        trials: list[ResearchTrial] = []
        best_trial: ResearchTrial | None = None

        for index, parameters in enumerate(candidates):
            seed = _trial_seed(spec.seed, parameters)
            try:
                train = self._evaluator(parameters, seed, DatasetRole.TRAIN)
                train_failure = constraint_failure(train, spec.constraints)
                train_objective = objective_value(train, spec.objective_metric)
                if train_failure is not None:
                    trials.append(
                        ResearchTrial(
                            index,
                            parameters,
                            seed,
                            TrialStatus.REJECTED,
                            train,
                            None,
                            train_objective,
                            None,
                            f"TRAIN_{train_failure}",
                        )
                    )
                    continue
                if train_objective is None:
                    trials.append(
                        ResearchTrial(
                            index,
                            parameters,
                            seed,
                            TrialStatus.REJECTED,
                            train,
                            None,
                            None,
                            None,
                            "TRAIN_OBJECTIVE_UNDEFINED",
                        )
                    )
                    continue

                validation = self._evaluator(parameters, seed, DatasetRole.VALIDATION)
                validation_failure = constraint_failure(validation, spec.constraints)
                validation_objective = objective_value(validation, spec.objective_metric)
                if validation_failure is not None:
                    trial = ResearchTrial(
                        index,
                        parameters,
                        seed,
                        TrialStatus.REJECTED,
                        train,
                        validation,
                        train_objective,
                        validation_objective,
                        f"VALIDATION_{validation_failure}",
                    )
                elif validation_objective is None:
                    trial = ResearchTrial(
                        index,
                        parameters,
                        seed,
                        TrialStatus.REJECTED,
                        train,
                        validation,
                        train_objective,
                        None,
                        "VALIDATION_OBJECTIVE_UNDEFINED",
                    )
                else:
                    trial = ResearchTrial(
                        index,
                        parameters,
                        seed,
                        TrialStatus.COMPLETED,
                        train,
                        validation,
                        train_objective,
                        validation_objective,
                    )
                trials.append(trial)
            except (ValueError, ArithmeticError, IndexError, KeyError) as exc:
                trials.append(
                    ResearchTrial(
                        index,
                        parameters,
                        seed,
                        TrialStatus.ERROR,
                        None,
                        None,
                        None,
                        None,
                        f"EVALUATION_{type(exc).__name__.upper()}",
                    )
                )
                continue

            if trial.status is not TrialStatus.COMPLETED:
                continue
            if best_trial is None:
                best_trial = trial
                continue
            assert trial.validation_objective is not None
            assert best_trial.validation_objective is not None
            if better(
                trial.validation_objective,
                best_trial.validation_objective,
                spec.objective_direction,
            ):
                best_trial = trial
            elif trial.validation_objective == best_trial.validation_objective:
                assert trial.train_objective is not None
                assert best_trial.train_objective is not None
                if better(
                    trial.train_objective,
                    best_trial.train_objective,
                    spec.objective_direction,
                ):
                    best_trial = trial

        oos_result: BacktestResult | None = None
        oos_objective: Decimal | None = None
        if best_trial is not None:
            oos_result = self._evaluator(
                best_trial.parameters,
                best_trial.seed,
                DatasetRole.OOS,
            )
            oos_objective = objective_value(oos_result, spec.objective_metric)

        trial_tuple = tuple(trials)
        result = ExperimentResult(
            spec=spec,
            fingerprint=_fingerprint(spec, space),
            trials=trial_tuple,
            best_trial=best_trial,
            oos_result=oos_result,
            oos_objective=oos_objective,
            sensitivity=_sensitivity(
                trial_tuple,
                maximize=spec.objective_direction.value == "MAXIMIZE",
            ),
        )
        if self._registry is not None:
            self._registry.save(result)
        return result
