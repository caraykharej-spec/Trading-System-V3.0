from __future__ import annotations

import csv
import gzip
import json
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

# `python scripts/backtest/<file>.py` puts scripts/backtest, not the repository
# root, on sys.path. Keep the documented direct entrypoint reliable while the
# same module remains importable by tests and `python -m`.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scripts.backtest.sync_gate_universe_history_to_b2 as core  # noqa: E402
from app.data.market_data import Candle  # noqa: E402
from app.data.providers.http import ProviderError  # noqa: E402


_CORE_SYNC_ROUTE = core.sync_route


def archive_month_url(route: core.GateHistoryRoute, value: datetime) -> str:
    """Build Gate's monthly Historical Quotation K-line URL."""

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


def archive_day_url(route: core.GateHistoryRoute, value: datetime) -> str:
    """Build Gate's daily Historical Quotation K-line URL."""

    return core.archive_url(route, value)


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
) -> tuple[list[Candle], int, int, int, int, int]:
    """Resolve Gate history adaptively: monthly, then daily, then recent REST.

    Gate's live public archive currently contains both monthly and daily K-line
    object conventions depending on instrument/history segment. Monthly is
    attempted first because it minimizes requests. If absent, each requested
    UTC day is resolved through the daily K-line convention. REST remains a
    bounded fallback only for a recent unpublished archive tail.

    Returns:
      rows,
      archive_days_found,
      archive_days_missing,
      rest_fallback_days,
      monthly_archive_objects_found,
      daily_archive_objects_found.
    """

    output: dict[datetime, Candle] = {}
    archive_days_found = 0
    archive_days_missing = 0
    rest_fallback_days = 0
    monthly_archive_objects_found = 0
    daily_archive_objects_found = 0
    recent_cutoff = core._utc_day_floor(datetime.now(timezone.utc)) - timedelta(days=30)
    requested_days = list(core.iter_days(start, end))

    with tempfile.TemporaryDirectory(prefix="gate-adaptive-archive-") as temp_dir:
        root = Path(temp_dir)
        month = start.astimezone(timezone.utc).strftime("%Y%m")
        month_path = root / f"{route.provider_symbol}-{month}.csv.gz"
        monthly_found = core._download_archive(archive_month_url(route, start), month_path)

        archive_day_keys: set[str] = set()
        if monthly_found:
            monthly_archive_objects_found = 1
            monthly_rows = _parse_month_archive_5m(month_path, route, start, end)
            for candle in monthly_rows:
                output[candle.timestamp] = candle
                archive_day_keys.add(_day_key(candle.timestamp))
            archive_days_found = len(archive_day_keys)
            archive_days_missing = max(0, len(requested_days) - archive_days_found)

            # A current monthly object can be incomplete. Only fill recent days
            # missing from the archive; never use REST as long-range history.
            for day in requested_days:
                if _day_key(day) in archive_day_keys or day < recent_cutoff:
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
        else:
            # Gate also serves K-line history as daily objects for some markets.
            # This contract is documented by Gate and independently probed by
            # the repository's archive-contract workflow.
            for day in requested_days:
                daily_path = root / f"{route.provider_symbol}-{day.strftime('%Y%m%d')}.csv.gz"
                daily_found = core._download_archive(archive_day_url(route, day), daily_path)
                rows: list[Candle] = []
                if daily_found:
                    daily_archive_objects_found += 1
                    archive_days_found += 1
                    rows = core._parse_archive_5m(daily_path, route, day)
                else:
                    archive_days_missing += 1
                    if day >= recent_cutoff:
                        try:
                            rows = core._fetch_recent_rest_5m(route, day)
                        except ProviderError:
                            rows = []
                        if rows:
                            rest_fallback_days += 1
                for candle in rows:
                    if start <= candle.timestamp < end:
                        output[candle.timestamp] = candle

    return (
        [output[key] for key in sorted(output)],
        archive_days_found,
        archive_days_missing,
        rest_fallback_days,
        monthly_archive_objects_found,
        daily_archive_objects_found,
    )


def route_missing_5m_inside_observed_span(
    first: datetime | None,
    last: datetime | None,
    total_rows: int,
) -> int:
    """Count route-wide missing 5m points, including completely empty months."""

    if first is None or last is None or total_rows <= 0:
        return 0
    expected = int((last - first).total_seconds()) // core._SECONDS["5m"] + 1
    return max(0, expected - total_rows)


def _head_object_state(key: str) -> tuple[bool, str | None]:
    """Return B2 object existence and the normalized stored sha256 metadata."""

    result = core._aws(
        "s3api",
        "head-object",
        "--bucket",
        core._bucket(),
        "--key",
        key,
        check=False,
        quiet=False,
    )
    if core._object_missing(result):
        return False, None
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid head-object response for {key}") from exc
    metadata = payload.get("Metadata") or {}
    value = metadata.get("sha256")
    if value is None:
        return True, None
    return True, str(value).strip().lower() or None


def sync_route(
    route: core.GateHistoryRoute,
    *,
    start: datetime,
    end: datetime,
    force: bool = False,
) -> dict[str, object]:
    """Sync and verify one route using Gate's adaptive archive contracts."""

    if not route.full_history_supported:
        return _CORE_SYNC_ROUTE(route, start=start, end=end, force=force)

    generated_at = datetime.now(timezone.utc)
    effective_start = max(start, core._ARCHIVE_START)
    partitions: list[core.PartitionResult] = []
    observed_first: datetime | None = None
    observed_last: datetime | None = None
    total_5m_rows = 0
    total_archive_days_found = 0
    total_archive_days_missing = 0
    total_rest_fallback_days = 0
    total_monthly_archive_objects_found = 0
    total_daily_archive_objects_found = 0
    source_months_requested = 0
    source_months_with_rows = 0
    source_months_without_rows: list[str] = []
    source_months_using_monthly_archive = 0
    source_months_using_daily_archive = 0
    uploaded_new_partition_objects = 0
    replaced_partition_objects = 0
    reused_verified_partition_objects = 0
    forced_partition_objects = 0

    for month_start, month_end in core.iter_month_ranges(effective_start, end):
        source_months_requested += 1
        month_label = month_start.strftime("%Y-%m")
        (
            five,
            archive_days_found,
            archive_days_missing,
            rest_fallback_days,
            monthly_archive_objects_found,
            daily_archive_objects_found,
        ) = fetch_month_5m(route, month_start, month_end)

        total_archive_days_found += archive_days_found
        total_archive_days_missing += archive_days_missing
        total_rest_fallback_days += rest_fallback_days
        total_monthly_archive_objects_found += monthly_archive_objects_found
        total_daily_archive_objects_found += daily_archive_objects_found
        if monthly_archive_objects_found:
            source_months_using_monthly_archive += 1
        if daily_archive_objects_found:
            source_months_using_daily_archive += 1

        # Count source availability even when a whole month has no rows. This
        # prevents a missing source month from disappearing from evidence.
        if not five:
            source_months_without_rows.append(month_label)
            continue

        source_months_with_rows += 1
        total_5m_rows += len(five)
        observed_first = min(observed_first or five[0].timestamp, five[0].timestamp)
        observed_last = max(observed_last or five[-1].timestamp, five[-1].timestamp)
        month_missing_inside_span = core._missing_inside_span(five)

        for timeframe in core._TIMEFRAMES:
            rows = core.resample(five, timeframe)
            if not rows:
                continue
            key = core._partition_key(route, timeframe, month_start, month_end, end)

            # Rebuild deterministic Parquet bytes first, then compare their
            # digest to B2 metadata. Mere object existence is not sufficient
            # qualification evidence.
            with tempfile.TemporaryDirectory(prefix="gate-history-") as temp_dir:
                path = Path(temp_dir) / f"{timeframe}.parquet"
                core._write_parquet(path, route, timeframe, rows)
                digest = core._sha256(path)
                existed, remote_digest = _head_object_state(key)
                reusable = existed and remote_digest == digest and not force
                if reusable:
                    reused_verified_partition_objects += 1
                else:
                    core._put_file(
                        path,
                        key,
                        digest,
                        "application/vnd.apache.parquet",
                    )
                    if force:
                        forced_partition_objects += 1
                    elif existed:
                        replaced_partition_objects += 1
                    else:
                        uploaded_new_partition_objects += 1

            partitions.append(
                core.PartitionResult(
                    timeframe=timeframe,
                    year=month_start.year,
                    month=month_start.month,
                    rows=len(rows),
                    object_key=key,
                    sha256=digest,
                    first_timestamp=rows[0].timestamp.isoformat(),
                    last_timestamp=rows[-1].timestamp.isoformat(),
                    missing_5m_inside_observed_span=month_missing_inside_span,
                    archive_days_found=archive_days_found,
                    archive_days_missing=archive_days_missing,
                    rest_fallback_days=rest_fallback_days,
                    reused=reusable,
                )
            )

    route_missing = route_missing_5m_inside_observed_span(
        observed_first,
        observed_last,
        total_5m_rows,
    )
    status = "COMPLETE" if total_5m_rows > 0 else "NO_HISTORY_RETURNED"
    if status == "COMPLETE" and route_missing > 0:
        status = "COMPLETE_WITH_RECORDED_GAPS"

    manifest: dict[str, object] = {
        "schema_version": core._SCHEMA_VERSION,
        "status": status,
        "route": asdict(route),
        "requested_start": start.isoformat(),
        "effective_archive_start": effective_start.isoformat(),
        "requested_end": end.isoformat(),
        "generated_at": generated_at.isoformat(),
        "source_kind": "gate_historical_quotation",
        "source_archive_contract": "adaptive_monthly_then_daily",
        "source_timeframe": "5m",
        "derived_timeframes": list(core._TIMEFRAMES),
        "observed_first": observed_first.isoformat() if observed_first else None,
        "observed_last": observed_last.isoformat() if observed_last else None,
        "total_5m_rows": total_5m_rows,
        "missing_5m_inside_observed_span": route_missing,
        "archive_days_found": total_archive_days_found,
        "archive_days_missing": total_archive_days_missing,
        "rest_fallback_days": total_rest_fallback_days,
        "monthly_archive_objects_found": total_monthly_archive_objects_found,
        "daily_archive_objects_found": total_daily_archive_objects_found,
        "source_months_requested": source_months_requested,
        "source_months_with_rows": source_months_with_rows,
        "source_months_without_rows": source_months_without_rows,
        "source_months_using_monthly_archive": source_months_using_monthly_archive,
        "source_months_using_daily_archive": source_months_using_daily_archive,
        "partition_objects_recorded": len(partitions),
        "uploaded_new_partition_objects": uploaded_new_partition_objects,
        "replaced_partition_objects": replaced_partition_objects,
        "reused_verified_partition_objects": reused_verified_partition_objects,
        "forced_partition_objects": forced_partition_objects,
        "integrity_policy": "sha256_rebuild_compare_or_replace",
        "partitions": [asdict(item) for item in partitions],
    }
    core._put_json(manifest, core._route_manifest_key(route))
    return manifest


def main() -> int:
    # Core owns universe discovery, deterministic resampling, Parquet schema,
    # B2 object layout, route manifests and CLI. This module installs Gate's
    # adaptive archive transport plus checksum-aware qualification.
    core.fetch_month_5m = fetch_month_5m
    core.sync_route = sync_route
    return core.main()


if __name__ == "__main__":
    raise SystemExit(main())
