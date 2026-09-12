from __future__ import annotations

import json
from time import perf_counter

from app.application.strategy_pipeline import StrategyPipeline
from app.market.analysis import MarketSnapshot, analyze_market
from app.universe.market_data_resolution import StormDrivenUniverseResolver


def main() -> None:
    """Run one real, read-only signal scan over every active Storm USDT market."""

    started = perf_counter()
    resolver = StormDrivenUniverseResolver(max_workers=16)
    report = resolver.resolve()
    resolved_at = perf_counter()
    by_symbol = {item.canonical_symbol: item for item in report.assets}

    def load(
        symbol: str,
    ) -> tuple[MarketSnapshot, MarketSnapshot, MarketSnapshot, MarketSnapshot]:
        resolution = by_symbol[symbol]
        snapshots: dict[str, MarketSnapshot] = {}
        for timeframe in ("1d", "4h", "1h", "15m"):
            candles = resolver.get_candles(
                resolution, timeframe=timeframe, limit=260, minimum_history=220
            )
            snapshots[timeframe] = analyze_market(symbol, timeframe, candles)
        return (
            snapshots["1d"],
            snapshots["4h"],
            snapshots["1h"],
            snapshots["15m"],
        )

    evaluated, signals, rejections = StrategyPipeline(
        load, max_workers=16
    ).evaluate_all_with_rejections(by_symbol)
    finished = perf_counter()
    payload = {
        "mode": "PAPER_READ_ONLY",
        "active_storm_markets": report.reference_storm,
        "gateio": report.gateio,
        "gateio_sources": {
            source: sum(
                item.market_data_source == source for item in report.assets
            )
            for source in ("gateio", "gateio_futures", "gateio_tradfi")
        },
        "yfinance": report.yfinance,
        "no_data": report.no_data,
        "coverage_percent": str(report.coverage_percent),
        "mapping_count": len(report.symbol_mappings()),
        "contract_spec_count": len(report.research_contract_specs()),
        "resolution_seconds": round(resolved_at - started, 3),
        "signal_scan_seconds": round(finished - resolved_at, 3),
        "total_seconds": round(finished - started, 3),
        "evaluated": evaluated,
        "qualified": [
            {
                "symbol": signal.symbol,
                "direction": signal.direction,
                "score": str(signal.score),
                "confidence": str(signal.confidence),
                "entry": str(signal.entry),
                "stop_loss": str(signal.stop_loss),
                "target": str(signal.target),
                "rr": str(signal.rr),
            }
            for signal in signals[:10]
        ],
        "rejections": [
            {"symbol": item.symbol, "reasons": list(item.reasons)}
            for item in rejections
        ],
        "gateio_no_market": [
            item.base_asset
            for item in report.assets
            if "gateio_not_found" in item.reason
        ],
        "unresolved": [
            item.base_asset
            for item in report.assets
            if item.source.value == "no_data"
        ],
        "normalized_mappings": [
            {
                "storm": item.base_asset,
                "source": item.market_data_source,
                "provider_symbol": item.provider_symbol,
                "price_multiplier": str(item.price_multiplier),
            }
            for item in report.assets
            if item.price_multiplier != 1
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
