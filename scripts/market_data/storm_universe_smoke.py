from __future__ import annotations

from app.universe.market_data_resolution import StormDrivenUniverseResolver


def main() -> None:
    report = StormDrivenUniverseResolver().resolve()
    if report.reference_storm < 1:
        raise RuntimeError(
            "Storm public universe smoke found no type=base settlementToken=USDT markets"
        )
    if report.gateio + report.yfinance + report.no_data != report.reference_storm:
        raise RuntimeError("market-data coverage buckets do not equal Storm reference universe")

    print("Storm-driven public market-data resolution smoke: PASS")
    print(f"(reference) storm: {report.reference_storm}")
    print(f"gate.io: {report.gateio}")
    print(f"yfinance: {report.yfinance}")
    print(f"no data: {report.no_data}")
    print(f"coverage: {report.coverage_percent}%")
    if report.no_data:
        unresolved = ",".join(
            item.base_asset for item in report.assets if item.source.value == "no_data"
        )
        print(f"unresolved: {unresolved}")


if __name__ == "__main__":
    main()
