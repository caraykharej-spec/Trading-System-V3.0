from __future__ import annotations

import csv
import gzip
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import scripts.backtest.sync_gate_universe_history_to_b2 as core
from app.data.market_data import Candle
from app.data.providers.http import ProviderError


def archive_month_url(route: core.GateHistoryRoute, value: datetime) -> str:
    """Build the production Gate Historical Quotation monthly K-line URL."""

    business = route.archive_business
    if business is None:
        raise ValueError(f"no historical quotation archive for provider: {route.provider}")
    value = value.astimezone(timezone.utc)
    month = value.strftime("%Y%m")
    market = route.provider_symbol.replace("/", "_").upper()
    return (
        f"{core._ARCHIVE_BASE_URL}/{business}/candlesticks_5m/{month}/"
        f"{market}-{month}.csv.gz"
    )


def _parse_month_archive_5m(
    path: Path,
    route: core.GateHistoryRoute,
    start: datetime,
    end: datetime,
) -> list[Candle]:
    multiplier = Decimal(route.price_multiplier)
    rows: dict[datetime, Candle] = {}
    try:
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            for line_number, raw in enumerate(reader, start=1):
                if not raw:
                    continue
                if len(raw) < 6:
                    raise ProviderError(
                        f"Gate historical quotation row {line_number} has fewer than 6 fields"
                    )
                try:
                    timestamp = datetime.fromtimestamp(
                        int(Decimal(raw[0])), tz=timezone.utc
                    )
                    volume = Decimal(raw[1])
                    close = Decimal(raw[2]) * multiplier
                    high = Decimal(raw[3]) * multiplier
                    low = Decimal(raw[4]) * multiplier
                    open_ = Decimal(raw[5]) * multiplier
                except (InvalidOperation, ValueError, OverflowError):
                    if line_number == 1:
                        continue
                    raise ProviderError(
                        f"Gate historical quotation row {line_number} is invalid"
                    )
                if not start <= timestamp < end:
                    continue
                if int(timestamp.timestamp()) % core._SECONDS["5m"]:
                    raise ProviderError(
                        f"Gate archive 5m timestamp is not aligned: {timestamp.isoformat()}"
                    )
                candle = Candle(
                    symbol=route.canonical_symbol,
                    timeframe="5m",
                    timestamp=timestamp,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                )
                if timestamp in rows and rows[timestamp] != candle:
                    raise ProviderError(
                        f"conflicting duplicate Gate archive candle: {timestamp.isoformat()}"
                    )
                rows[timestamp] = candle
    except (OSError, EOFError) as exc:
        raise ProviderError(f"invalid Gate historical quotation gzip: {path}") from exc
    return [rows[key] for key in sorted(rows)]


def _day_key(value: datetime) -> str:
    return value.astimezone(timezone.utc).date().isoformat()


def fetch_month_5m(
    route: core.GateHistoryRoute,
    start: datetime,
    end: datetime,
) -> tuple[list[Candle], int, int, int]:
    """Fetch one monthly archive and use REST only for a recent unpublished tail.

    The return shape intentionally matches the core collector contract:
    rows, archive_days_found, archive_days_missing, rest_fallback_days.
    """

    output: dict[datetime, Candle] = {}
    rest_fallback_days = 0
    recent_cutoff = core._utc_day_floor(datetime.now(timezone.utc)) - timedelta(days=30)

    with tempfile.TemporaryDirectory(prefix="gate-monthly-archive-") as temp_dir:
        month = start.astimezone(timezone.utc).strftime("%Y%m")
        path = Path(temp_dir) / f"{route.provider_symbol}-{month}.csv.gz"
        found = core._download_archive(archive_month_url(route, start), path)
        archive_rows: list[Candle] = []
        if found:
            archive_rows = _parse_month_archive_5m(path, route, start, end)
            for candle in archive_rows:
                output[candle.timestamp] = candle

        archive_day_keys = {_day_key(item.timestamp) for item in archive_rows}
        requested_days = list(core.iter_days(start, end))

        for day in requested_days:
            if day < recent_cutoff or _day_key(day) in archive_day_keys:
                continue
            try:
                recent = core._fetch_recent_rest_5m(route, day)
            except ProviderError:
                recent = []
            if recent:
                rest_fallback_days += 1
                for candle in recent:
                    if start <= candle.timestamp < end:
                        output[candle.timestamp] = candle

    output_rows = [output[key] for key in sorted(output)]
    represented_days = {_day_key(item.timestamp) for item in output_rows}
    requested_day_count = len(list(core.iter_days(start, end)))
    archive_days_found = len(archive_day_keys)
    archive_days_missing = max(0, requested_day_count - len(represented_days))
    return (
        output_rows,
        archive_days_found,
        archive_days_missing,
        rest_fallback_days,
    )


def main() -> int:
    # Core owns universe discovery, deterministic resampling, Parquet schema,
    # checksums, B2 object layout, route manifests and CLI. This module only
    # swaps the archive transport to Gate's production monthly K-line layout.
    core.fetch_month_5m = fetch_month_5m
    return core.main()


if __name__ == "__main__":
    raise SystemExit(main())
