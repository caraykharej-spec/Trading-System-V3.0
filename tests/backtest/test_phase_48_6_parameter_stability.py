from decimal import Decimal

import pytest

from app.backtest.parameter_stability import (
    ParameterSweepSpec,
    PerturbationMode,
    StabilityThresholds,
    qualify_parameter_stability,
)


def _spec(
    name: str = "lookback",
    *,
    baseline: str = "10",
    perturbations: tuple[str, ...] = ("-20", "-10", "10", "20"),
    mode: PerturbationMode = PerturbationMode.RELATIVE_PERCENT,
    lower: str | None = "5",
    upper: str | None = "15",
) -> ParameterSweepSpec:
    return ParameterSweepSpec(
        name=name,
        baseline=Decimal(baseline),
        perturbations=tuple(Decimal(value) for value in perturbations),
        mode=mode,
        lower_bound=Decimal(lower) if lower is not None else None,
        upper_bound=Decimal(upper) if upper is not None else None,
    )


def test_smooth_neighborhood_passes_and_is_reproducible():
    specs = (
        _spec(),
        _spec("threshold", baseline="5", lower="2", upper="8"),
    )

    def evaluator(parameters):
        return (
            Decimal("100")
            - abs(parameters["lookback"] - Decimal("10")) * Decimal("1")
            - abs(parameters["threshold"] - Decimal("5")) * Decimal("1")
        )

    first = qualify_parameter_stability(specs, evaluator=evaluator)
    second = qualify_parameter_stability(tuple(reversed(specs)), evaluator=evaluator)

    assert first.passed is True
    assert first == second
    assert len(first.evidence_fingerprint) == 64
    assert first.scenario_count == 9


def test_cliff_detection_fails_closed():
    thresholds = StabilityThresholds(
        stability_tolerance_percent=Decimal("100"),
        max_degradation_percent=Decimal("100"),
        min_stable_fraction=Decimal("0"),
        max_adjacent_cliff_percent=Decimal("20"),
    )

    def evaluator(parameters):
        return Decimal("40") if parameters["lookback"] >= 11 else Decimal("100")

    report = qualify_parameter_stability(
        (_spec(),), evaluator=evaluator, thresholds=thresholds
    )

    assert report.passed is False
    assert report.parameter_results[0].max_adjacent_cliff_percent == Decimal("60")


def test_degradation_and_stable_fraction_gates_fail_unstable_surface():
    thresholds = StabilityThresholds(
        stability_tolerance_percent=Decimal("5"),
        max_degradation_percent=Decimal("15"),
        min_stable_fraction=Decimal("0.75"),
        max_adjacent_cliff_percent=Decimal("100"),
    )

    def evaluator(parameters):
        distance = abs(parameters["lookback"] - Decimal("10"))
        return Decimal("100") - distance * Decimal("20")

    report = qualify_parameter_stability(
        (_spec(),), evaluator=evaluator, thresholds=thresholds
    )

    result = report.parameter_results[0]
    assert report.passed is False
    assert result.stable_fraction < Decimal("0.75")
    assert result.worst_degradation_percent > Decimal("15")


def test_bounds_are_respected_and_duplicate_bounded_values_are_removed():
    spec = _spec(
        baseline="10",
        perturbations=("-90", "-80", "80", "90"),
        lower="9",
        upper="11",
    )
    report = qualify_parameter_stability(
        (spec,), evaluator=lambda parameters: Decimal("100")
    )

    values = tuple(point.value for point in report.parameter_results[0].points)
    assert values == (Decimal("9"), Decimal("11"))
    assert report.scenario_count == 3


def test_absolute_mode_supports_zero_baseline_parameters():
    spec = _spec(
        "offset",
        baseline="0",
        perturbations=("-2", "-1", "1", "2"),
        mode=PerturbationMode.ABSOLUTE,
        lower="-3",
        upper="3",
    )
    report = qualify_parameter_stability(
        (spec,),
        evaluator=lambda parameters: Decimal("100") - abs(parameters["offset"]),
    )

    assert report.passed is True
    assert tuple(
        point.value for point in report.parameter_results[0].points
    ) == tuple(Decimal(value) for value in ("-2", "-1", "1", "2"))


@pytest.mark.parametrize("invalid", ("NaN", "Infinity", "-Infinity"))
def test_non_finite_parameter_inputs_are_rejected(invalid):
    with pytest.raises(ValueError, match="finite"):
        _spec(baseline=invalid)


def test_invalid_specs_and_duplicate_names_are_rejected():
    with pytest.raises(ValueError, match="below lower_bound"):
        _spec(baseline="4", lower="5")
    with pytest.raises(ValueError, match="exclude zero"):
        _spec(perturbations=("0", "10"))
    with pytest.raises(ValueError, match="unique"):
        qualify_parameter_stability(
            (_spec("same"), _spec("same")),
            evaluator=lambda parameters: Decimal("100"),
        )


@pytest.mark.parametrize("score", ("NaN", "Infinity", "-Infinity"))
def test_non_finite_evaluator_output_is_rejected(score):
    with pytest.raises(ValueError, match="evaluator score must be finite"):
        qualify_parameter_stability(
            (_spec(),),
            evaluator=lambda parameters: Decimal(score),
        )


@pytest.mark.parametrize("score", ("0", "-1"))
def test_non_positive_baseline_score_is_rejected(score):
    with pytest.raises(ValueError, match="baseline evaluator score must be positive"):
        qualify_parameter_stability(
            (_spec(),),
            evaluator=lambda parameters: Decimal(score),
        )


def test_scenario_cardinality_is_bounded():
    spec = _spec(
        perturbations=tuple(str(value) for value in range(1, 20)),
        lower=None,
        upper=None,
    )
    thresholds = StabilityThresholds(max_scenarios=5)

    with pytest.raises(ValueError, match="max_scenarios"):
        qualify_parameter_stability(
            (spec,),
            evaluator=lambda parameters: Decimal("100"),
            thresholds=thresholds,
        )
