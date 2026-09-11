from app.data.source_policy import MarketDataSourcePolicy, build_market_data_routers


class FakeProvider:
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def get_live_price(self, symbol: str):
        raise AssertionError("network method must not be called by source-policy tests")

    def get_candles(self, request):
        raise AssertionError("network method must not be called by source-policy tests")


def test_default_market_data_roles_are_storm_and_gateio_yahoo() -> None:
    live, candles = build_market_data_routers(
        (FakeProvider("yahoo"), FakeProvider("storm"), FakeProvider("gateio"))
    )

    assert tuple(provider.name for provider in live.providers) == ("storm",)
    assert tuple(provider.name for provider in candles.providers) == ("gateio", "yahoo")


def test_source_policy_fails_closed_when_required_provider_is_missing() -> None:
    try:
        build_market_data_routers((FakeProvider("storm"), FakeProvider("yahoo")))
    except ValueError as exc:
        assert "gateio" in str(exc)
    else:
        raise AssertionError("missing Gate.io OHLCV source must fail closed")


def test_source_policy_rejects_duplicate_roles() -> None:
    try:
        MarketDataSourcePolicy(ohlcv_providers=("gateio", "gateio"))
    except ValueError as exc:
        assert "unique" in str(exc)
    else:
        raise AssertionError("duplicate source roles must be rejected")
