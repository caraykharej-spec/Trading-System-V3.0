from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
from typing import Protocol

from .models import (
    ExperimentResult,
    ExperimentSpec,
    ParameterSet,
    ResearchEvaluation,
    TrialResult,
)
from .objectives import (
    constraint_violations,
    objective_value,
    validation_degradation_percent,
)
from .parameter_space import StrategyRuleParameterPolicy, enumerate_parameter_sets


class ResearchEvaluator(Protocol):
    def __call__(self, parameters: ParameterSet) -> ResearchEvaluation:
        ...


class ExperimentRegistry(Protocol):
    def save(self, result: ExperimentResult) -> bool:
        ...


class ExperimentRunner:
    """Run bounded, reproducible parameter research without touching holdout data."""

    def __init__(
        self,
        *,
        policy: StrategyRuleParameterPolicy | None = None,
        registry: ExperimentRegistry | None = None,
    ) -> None:
        self.policy = policy or StrategyRuleParameterPolicy()
        self.registry = registry

    def run(
        self,
        spec: ExperimentSpec,
        *,
        training_evaluator: ResearchEvaluator,
        validation_evaluator: ResearchEvaluator | None = None,
        created_at: datetime | None = None,
    ) -> ExperimentResult:
        self.policy.validate_space(spec.parameter_space)
        has_validation = spec.datasets.validation_fingerprint is not None
        if has_validation != (validation_evaluator is not None):
            raise ValueError(
                "validation evaluator presence must match validation_fingerprint"
            )

        parameter_sets = enumerate_parameter_sets(
            spec.parameter_space,
            method=spec.search_method,
            max_trials=spec.max_trials,
            seed=spec.seed,
        )
        trials: list[TrialResult] = []
        for parameters in parameter_sets:
            self.policy.validate_set(parameters)
            training = training_evaluator(parameters)
            training_objective = objective_value(training.summary, spec.objective)
            violations = list(
                constraint_violations(
                    training.summary,
                    spec.constraints,
                    prefix="training",
                )
            )
            validation: ResearchEvaluation | None = None
            degradation: Decimal | None = None
            selection_objective = training_objective
            if validation_evaluator is not None:
                validation = validation_evaluator(parameters)
                validation_objective = objective_value(validation.summary, spec.objective)
                selection_objective = validation_objective
                violations.extend(
                    constraint_violations(
                        validation.summary,
                        spec.constraints,
                        prefix="validation",
                    )
                )
                degradation = validation_degradation_percent(
                    training_objective, validation_objective
                )
                degradation_limit = spec.constraints.max_validation_degradation_percent
                if degradation_limit is not None and degradation > degradation_limit:
                    violations.append("validation: objective degradation above limit")

            trial_id = self._trial_id(spec.experiment_id, parameters)
            trials.append(
                TrialResult(
                    trial_id=trial_id,
                    parameters=parameters,
                    training=training,
                    validation=validation,
                    training_objective=training_objective,
                    selection_objective=selection_objective,
                    validation_degradation_percent=degradation,
                    feasible=not violations,
                    violations=tuple(violations),
                )
            )

        best_trial = self._best_trial(trials)
        timestamp = created_at or datetime.now(timezone.utc)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        result = ExperimentResult(
            spec=spec,
            trials=tuple(trials),
            best_trial=best_trial,
            created_at=timestamp,
        )
        if self.registry is not None:
            self.registry.save(result)
        return result

    @staticmethod
    def _trial_id(experiment_id: str, parameters: ParameterSet) -> str:
        text = f"{experiment_id}:{parameters.stable_key}"
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _best_trial(trials: list[TrialResult]) -> TrialResult | None:
        feasible = [trial for trial in trials if trial.feasible]
        if not feasible:
            return None
        return sorted(
            feasible,
            key=lambda trial: (
                -trial.selection_objective,
                trial.selection_summary.max_drawdown_percent,
                -trial.selection_summary.trade_count,
                trial.parameters.stable_key,
            ),
        )[0]
