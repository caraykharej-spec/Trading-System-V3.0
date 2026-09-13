from decimal import Decimal

import pytest

from app.backtest.synthetic_robustness import (
    SyntheticPathConfig,
    SyntheticPathModel,
    corrupt_series_for_quality_test,
    generate_price_path,
    inject_relative_noise,
)


def test_all_synthetic_models_are_positive_and_reproducible():
    config = SyntheticPathConfig(steps=100, seed=42)

    for model in SyntheticPathModel:
        first = generate_price_path(Decimal("100"), model=model, config=config)
        second = generate_price_path(Decimal("100"), model=model, config=config)

        assert first == second
        assert len(first) == 101
        assert all(value > 0 and value.is_finite() for value in first)


def test_noise_is_seeded_and_strictly_bounded():
    prices = (Decimal("100"),) * 50
    first = inject_relative_noise(
        prices, maximum_absolute_percent=Decimal("1"), seed=7
    )
    second = inject_relative_noise(
        prices, maximum_absolute_percent=Decimal("1"), seed=7
    )

    assert first == second
    assert all(Decimal("99") <= value <= Decimal("101") for value in first)


def test_duplicate_and_missing_data_scenarios_are_explicit():
    values = (Decimal("1"), Decimal("2"), Decimal("3"))

    duplicate = corrupt_series_for_quality_test(values, duplicate_index=1)
    missing = corrupt_series_for_quality_test(values, remove_index=1)

    assert duplicate == (Decimal("1"), Decimal("2"), Decimal("2"), Decimal("3"))
    assert missing == (Decimal("1"), Decimal("3"))


def test_non_finite_or_destructive_inputs_fail_closed():
    with pytest.raises(ValueError, match="finite"):
        generate_price_path(
            Decimal("NaN"),
            model=SyntheticPathModel.GBM,
            config=SyntheticPathConfig(steps=10, seed=1),
        )
    with pytest.raises(ValueError, match="invalid"):
        inject_relative_noise(
            (Decimal("1"),),
            maximum_absolute_percent=Decimal("200"),
            seed=1,
        )
