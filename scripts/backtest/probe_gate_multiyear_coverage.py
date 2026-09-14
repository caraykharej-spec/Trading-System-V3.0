from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://download.gatedata.org"
DEFAULT_MARKETS = ("BTC_USDT", "ETH_USDT", "SOL_USDT")
DEFAULT_START_MONTH = "202101"
DEFAULT_END_MONTH = "202609"


@dataclass(frozen=True)
class ProbeResult:
    market: str
    month: str
    status: int
    content_type: str | None
    size: str | None

    @property
    def available(self) -> bool:
        return self.status in {200, 206}


def _month_key(value: str) -> tuple[int, int]:
    if len(value) != 6 or not value.isdigit():
        raise ValueError(f"month must be YYYYMM, got {value!r}")
    year = int(value[:4])
    month = int(value[4:])
    if month < 1 or month > 12:
        raise ValueError(f"invalid month {value!r}")
    return year, month


def iter_months(start_month: str, end_month: str) -> tuple[str, ...]:
    year, month = _month_key(start_month)
    end_year, end_month_number = _month_key(end_month)
    if (year, month) > (end_year, end_month_number):
        raise ValueError("start month must not be after end month")

    values: list[str] = []
    while (year, month) <= (end_year, end_month_number):
        values.append(f"{year:04d}{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return tuple(values)


def archive_url(market: str, month: str) -> str:
    _month_key(month)
    return f"{BASE_URL}/spot/deals/{month}/{market}-{month}.csv.gz"


def _request(url: str, *, method: str) -> urllib.request.Request:
    headers = {"User-Agent": "Trading-System-V3 multiyear-coverage-probe/1.0"}
    if method == "GET":
        headers["Range"] = "bytes=0-0"
    return urllib.request.Request(url, headers=headers, method=method)


def probe_archive(market: str, month: str, timeout_seconds: int) -> ProbeResult:
    url = archive_url(market, month)
    try:
        with urllib.request.urlopen(
            _request(url, method="HEAD"), timeout=timeout_seconds
        ) as response:
            return ProbeResult(
                market=market,
                month=month,
                status=response.status,
                content_type=response.headers.get("Content-Type"),
                size=response.headers.get("Content-Length"),
            )
    except urllib.error.HTTPError as exc:
        if exc.code not in {405, 501}:
            return ProbeResult(market, month, exc.code, None, None)
    except urllib.error.URLError:
        return ProbeResult(market, month, 0, None, None)

    try:
        with urllib.request.urlopen(
            _request(url, method="GET"), timeout=timeout_seconds
        ) as response:
            return ProbeResult(
                market=market,
                month=month,
                status=response.status,
                content_type=response.headers.get("Content-Type"),
                size=response.headers.get("Content-Range")
                or response.headers.get("Content-Length"),
            )
    except urllib.error.HTTPError as exc:
        return ProbeResult(market, month, exc.code, None, None)
    except urllib.error.URLError:
        return ProbeResult(market, month, 0, None, None)


def contiguous_ranges(months: list[str]) -> list[list[str]]:
    if not months:
        return []
    ordered = sorted(months)
    ranges: list[list[str]] = [[ordered[0]]]
    for month in ordered[1:]:
        previous = ranges[-1][-1]
        expected_next = iter_months(previous, month)
        if len(expected_next) == 2:
            ranges[-1].append(month)
        else:
            ranges.append([month])
    return ranges


def build_report(results: list[ProbeResult]) -> dict[str, object]:
    markets = sorted({result.market for result in results})
    by_market: dict[str, object] = {}
    available_sets: list[set[str]] = []

    for market in markets:
        market_results = sorted(
            (result for result in results if result.market == market),
            key=lambda result: result.month,
        )
        available = [result.month for result in market_results if result.available]
        unavailable = [result.month for result in market_results if not result.available]
        ranges = contiguous_ranges(available)
        longest = max(ranges, key=len) if ranges else []
        available_sets.append(set(available))
        by_market[market] = {
            "available_month_count": len(available),
            "first_available_month": available[0] if available else None,
            "last_available_month": available[-1] if available else None,
            "longest_contiguous_month_count": len(longest),
            "longest_contiguous_start": longest[0] if longest else None,
            "longest_contiguous_end": longest[-1] if longest else None,
            "unavailable_month_count": len(unavailable),
            "available_months": available,
            "unavailable_months": unavailable,
        }

    common = sorted(set.intersection(*available_sets)) if available_sets else []
    common_ranges = contiguous_ranges(common)
    common_longest = max(common_ranges, key=len) if common_ranges else []
    return {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "Gate official monthly spot deals archives",
        "base_url": BASE_URL,
        "markets": by_market,
        "common_available_month_count": len(common),
        "common_longest_contiguous_month_count": len(common_longest),
        "common_longest_contiguous_start": common_longest[0] if common_longest else None,
        "common_longest_contiguous_end": common_longest[-1] if common_longest else None,
        "common_available_months": common,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Probe official Gate monthly spot deals archive coverage for a multi-year "
            "research horizon without downloading archive bodies."
        )
    )
    parser.add_argument("--markets", nargs="+", default=list(DEFAULT_MARKETS))
    parser.add_argument("--start-month", default=DEFAULT_START_MONTH)
    parser.add_argument("--end-month", default=DEFAULT_END_MONTH)
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--timeout-seconds", type=int, default=12)
    parser.add_argument("--output", type=Path, default=Path("gate_multiyear_coverage.json"))
    args = parser.parse_args()

    if args.max_workers < 1 or args.max_workers > 16:
        raise ValueError("max-workers must be between 1 and 16")
    if args.timeout_seconds < 1:
        raise ValueError("timeout-seconds must be positive")

    months = iter_months(args.start_month, args.end_month)
    jobs = [(market, month) for market in args.markets for month in months]
    results: list[ProbeResult] = []

    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {
            executor.submit(probe_archive, market, month, args.timeout_seconds): (
                market,
                month,
            )
            for market, month in jobs
        }
        for future in as_completed(futures):
            market, month = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # pragma: no cover - defensive network boundary
                print(f"market={market} month={month} error={exc!r}")
                result = ProbeResult(market, month, 0, None, None)
            results.append(result)
            print(
                f"market={result.market} month={result.month} status={result.status} "
                f"available={result.available} size={result.size}"
            )

    report = build_report(results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print("GATE MULTI-YEAR COVERAGE PROBE COMPLETE")
    print(f"output={args.output}")
    print(
        "common_longest_contiguous_month_count="
        f"{report['common_longest_contiguous_month_count']}"
    )
    print(
        "common_longest_contiguous_start="
        f"{report['common_longest_contiguous_start']}"
    )
    print(
        "common_longest_contiguous_end="
        f"{report['common_longest_contiguous_end']}"
    )

    if int(report["common_available_month_count"]) == 0:
        raise RuntimeError("no common Gate deals archive month is available across markets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
