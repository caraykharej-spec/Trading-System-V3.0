import time

from app.application import budgeted_market_scan
from app.application.budgeted_market_scan import BudgetedMarketScanner
from app.data.providers.http import ProviderError


def test_retryable_market_is_retried_after_first_pass():
    calls = {"BAD": 0}
    events = []

    def load(symbol):
        calls[symbol] += 1
        raise ProviderError("all_sources_failed")

    result = BudgetedMarketScanner(load, max_workers=1).run(
        ["BAD"],
        budget_seconds=10,
        retry_attempts=1,
        progress=events.append,
    )

    assert calls == {"BAD": 2}
    assert result.retried == ("BAD",)
    assert result.rejections[0].symbol == "BAD"
    assert any(item.event == "RETRY_QUEUED" for item in events)


def test_expired_budget_fails_closed_without_calling_loader():
    calls = 0
    ticks = iter((0.0, 2.0, 2.0, 2.0, 2.0, 2.0))

    def clock():
        return next(ticks, 2.0)

    def load(symbol):
        nonlocal calls
        calls += 1
        raise AssertionError(symbol)

    result = BudgetedMarketScanner(load, max_workers=1, clock=clock).run(
        ["LATE"],
        budget_seconds=1,
        retry_attempts=0,
    )

    assert calls == 0
    assert result.budget_exceeded
    assert result.rejections[0].reasons == ("time_budget_exceeded",)


def test_running_loader_does_not_delay_result_past_budget():
    def load(symbol):
        time.sleep(0.25)
        raise ProviderError(symbol)

    started = time.monotonic()
    result = BudgetedMarketScanner(load, max_workers=1).run(
        ["SLOW"], budget_seconds=0.03, retry_attempts=0
    )

    assert time.monotonic() - started < 0.15
    assert result.budget_exceeded
    assert result.rejections[0].reasons == ("time_budget_exceeded",)


def test_strategy_value_error_is_no_trade(monkeypatch):
    snapshots = (object(), object(), object(), object())

    def reject_strategy(*args):
        del args
        raise ValueError("No approved setup")

    monkeypatch.setattr(budgeted_market_scan, "evaluate_strategy", reject_strategy)
    result = BudgetedMarketScanner(lambda symbol: snapshots, max_workers=1).run(
        ["FLAT"], budget_seconds=1, retry_attempts=1
    )

    assert result.retried == ()
    assert result.rejections[0].state == "NO_TRADE"
    assert result.rejections[0].reasons == ("No approved setup",)
