from decimal import Decimal

from app.backtest.robustness_sampling import (
    SamplingMode,
    maximum_drawdown_percent,
    sample_pnl_path,
)

PNL = tuple(Decimal(value) for value in ("10", "-5", "8", "-12", "4", "6"))


def test_all_required_sampling_modes_are_deterministic():
    for mode in SamplingMode:
        first = sample_pnl_path(PNL, mode=mode, seed=42, block_size=2)
        second = sample_pnl_path(PNL, mode=mode, seed=42, block_size=2)

        assert first == second
        assert len(first) == len(PNL)


def test_permutation_modes_preserve_trade_multiset():
    for mode in (
        SamplingMode.RANDOM_PERMUTATION,
        SamplingMode.REVERSE,
        SamplingMode.WORST_FIRST,
        SamplingMode.LOSS_CLUSTER,
        SamplingMode.WIN_CLUSTER,
    ):
        assert sorted(sample_pnl_path(PNL, mode=mode, seed=7)) == sorted(PNL)


def test_iid_and_block_bootstrap_sample_only_observed_trades():
    for mode in (SamplingMode.IID_BOOTSTRAP, SamplingMode.BLOCK_BOOTSTRAP):
        sampled = sample_pnl_path(PNL, mode=mode, seed=11, block_size=3)

        assert set(sampled) <= set(PNL)


def test_adverse_ordering_exposes_larger_drawdown():
    favorable = (Decimal("30"), Decimal("-10"), Decimal("-10"))
    adverse = sample_pnl_path(
        favorable, mode=SamplingMode.WORST_FIRST, seed=1
    )

    assert maximum_drawdown_percent(
        adverse, initial_equity=Decimal("100")
    ) > maximum_drawdown_percent(
        favorable, initial_equity=Decimal("100")
    )
