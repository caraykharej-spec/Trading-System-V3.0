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
