from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from threading import Lock
from time import perf_counter

from app.application.strategy_pipeline import StrategyPipeline
from app.market.analysis import MarketSnapshot, analyze_market
from app.universe.market_data_resolution import StormDrivenUniverseResolver


def main() -> None:
    """Run one real, read-only signal scan over every active Storm USDT market."""

    parser = argparse.ArgumentParser(description="Run the full Storm signal smoke scan")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    started = perf_counter()
    resolver = StormDrivenUniverseResolver(max_workers=16)
    report = resolver.resolve()
    resolved_at = perf_counter()
    by_symbol = {item.canonical_symbol: item for item in report.assets}
    market_scores: dict[str, str] = {}
    score_lock = Lock()

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
        market_score = sum(
            (snapshot.score for snapshot in snapshots.values()),
            start=0,
        ) / len(snapshots)
        with score_lock:
            market_scores[symbol] = str(market_score.quantize(Decimal("0.01")))
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
    qualified_by_symbol = {signal.symbol: signal for signal in signals}
    rejected_by_symbol = {item.symbol: item for item in rejections}
    all_evaluated = []
    for symbol, resolution in by_symbol.items():
        signal = qualified_by_symbol.get(symbol)
        rejection = rejected_by_symbol.get(symbol)
        all_evaluated.append({
            "symbol": symbol,
            "status": "QUALIFIED" if signal is not None else (
                rejection.state if rejection is not None else "UNKNOWN"
            ),
            "strategy_score": str(signal.score) if signal is not None else (
                str(rejection.score) if rejection and rejection.score is not None else None
            ),
            "market_score": market_scores.get(symbol),
            "confidence": str(signal.confidence) if signal is not None else (
                str(rejection.confidence)
                if rejection and rejection.confidence is not None else None
            ),
            "configured_source": resolution.market_data_source,
            "provider_symbol": resolution.provider_symbol,
            "reasons": list(rejection.reasons) if rejection is not None else [],
        })
    all_evaluated.sort(
        key=lambda item: (
            item["market_score"] is not None,
            float(item["market_score"]) if item["market_score"] is not None else -1,
        ),
        reverse=True,
    )
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
        "all_evaluated_markets": all_evaluated,
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
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(json.dumps({
            "output": str(args.output),
            "evaluated": evaluated,
            "qualified": len(signals),
            "total_seconds": payload["total_seconds"],
        }))
    else:
        print(rendered)


if __name__ == "__main__":
    main()
