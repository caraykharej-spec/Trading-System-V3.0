from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from threading import Lock
from time import perf_counter

from app.application.budgeted_market_scan import BudgetedMarketScanner, ScanProgressEvent
from app.data.historical_store import SQLiteCandleStore
from app.data.incremental_candle_cache import IncrementalCandleService
from app.market.analysis import MarketSnapshot, analyze_market
from app.universe.market_data_resolution import StormDrivenUniverseResolver


def main() -> None:
    """Run one real, read-only signal scan over every active Storm USDT market."""

    parser = argparse.ArgumentParser(description="Run the full Storm signal smoke scan")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--cache-db", type=Path, default=Path("data/market_data_cache.db"))
    parser.add_argument("--cycle-budget-seconds", type=float, default=300.0)
    parser.add_argument("--retry-failed", type=int, default=1)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()

    started = perf_counter()
    resolver = StormDrivenUniverseResolver(max_workers=args.workers)
    report = resolver.resolve()
    resolved_at = perf_counter()
    by_symbol = {item.canonical_symbol: item for item in report.assets}
    market_scores: dict[str, str] = {}
    candle_provenance: dict[str, list[dict[str, object]]] = {}
    score_lock = Lock()
    candle_service = IncrementalCandleService(
        resolver, SQLiteCandleStore(args.cache_db), refresh_tail=2
    )

    def load(
        symbol: str,
    ) -> tuple[MarketSnapshot, MarketSnapshot, MarketSnapshot, MarketSnapshot]:
        resolution = by_symbol[symbol]
        snapshots: dict[str, MarketSnapshot] = {}
        for timeframe in ("1d", "4h", "1h", "15m"):
            batch = candle_service.load(
                resolution, timeframe=timeframe, limit=260, minimum_history=220
            )
            snapshots[timeframe] = analyze_market(
                symbol, timeframe, list(batch.candles)
            )
            with score_lock:
                candle_provenance.setdefault(symbol, []).append({
                    "timeframe": timeframe,
                    "configured_provider": batch.configured_provider,
                    "actual_provider": batch.actual_provider,
                    "provider_symbol": batch.provider_symbol,
                    "fallback_used": batch.fallback_used,
                    "cache_candles": batch.cache_candles,
                    "downloaded_candles": batch.downloaded_candles,
                    "fetch_seconds": round(batch.fetch_seconds, 3),
                })
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

    def report_progress(event: ScanProgressEvent) -> None:
        print(json.dumps({
            "event": event.event,
            "symbol": event.symbol,
            "completed": event.completed,
            "total": event.total,
            "attempt": event.attempt,
            "elapsed_seconds": round(event.elapsed_seconds, 3),
        }), flush=True)

    scan = BudgetedMarketScanner(load, max_workers=args.workers).run(
        by_symbol,
        budget_seconds=args.cycle_budget_seconds,
        retry_attempts=args.retry_failed,
        progress=report_progress,
    )
    evaluated, signals, rejections = scan.evaluated, scan.signals, scan.rejections
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
            "candle_provenance": candle_provenance.get(symbol, []),
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
        "cache_db": str(args.cache_db),
        "cycle_budget_seconds": args.cycle_budget_seconds,
        "budget_exceeded": scan.budget_exceeded,
        "retried_markets": list(scan.retried),
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
        "symbol_decisions": {
            base: {
                "status": (
                    "NOT_IN_ACTIVE_STORM_UNIVERSE"
                    if not any(item.base_asset.upper() == base for item in report.assets)
                    else "RESOLVED"
                    if any(
                        item.base_asset.upper() == base
                        and item.provider_symbol is not None
                        for item in report.assets
                    )
                    else "UNRESOLVED"
                )
            }
            for base in ("AMD", "COIN", "CRCL", "SPX", "SPCX", "SPXC", "SUI")
        },
        "degen_markets": [
            {
                "symbol": item.canonical_symbol,
                "base_asset": item.base_asset,
                "status": (
                    "RESEARCH_ONLY_RESOLVED"
                    if item.provider_symbol is not None
                    else "RESEARCH_ONLY_UNRESOLVED"
                ),
                "source": item.market_data_source,
                "provider_symbol": item.provider_symbol,
                "reason": item.reason,
            }
            for item in report.assets
            if "DEGEN" in item.base_asset.upper()
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
