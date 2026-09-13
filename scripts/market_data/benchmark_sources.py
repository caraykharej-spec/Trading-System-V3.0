from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.data.providers.gateio import GateIOProvider
from app.data.providers.gateio_futures import GateIOFuturesProvider
from app.data.providers.gateio_tradfi import GateIOTradFiProvider
from app.data.providers.yahoo import YahooFinanceProvider
from app.data.source_benchmark import SourceBenchmark
from app.data.source_registry import SourceMappingRegistry
from app.universe.storm_discovery import StormReferenceUniverseProvider


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark qualified market-data routes")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--assets", nargs="*", default=None)
    args = parser.parse_args()

    references = StormReferenceUniverseProvider().discover()
    storm_prices = {item.base_asset: item.reference_price for item in references}
    providers = (
        GateIOProvider(), GateIOFuturesProvider(), GateIOTradFiProvider(),
        YahooFinanceProvider(),
    )
    results = SourceBenchmark(
        SourceMappingRegistry.load(),
        {provider.name: provider for provider in providers},
    ).run(
        storm_prices,
        assets=set(args.assets) if args.assets else None,
    )
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY_SOURCE_BENCHMARK",
        "routes": [item.to_dict() for item in results],
        "qualified": sum(item.qualified for item in results),
        "failed": sum(not item.success for item in results),
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
