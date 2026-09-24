"""Repair source-limited non-crypto 15m history in the private research store.

US equities use delayed historical Alpaca SIP bars. Forex, metals, Brent and
the reviewed SPX proxy use HistData Generic ASCII BID minute archives,
normalized from fixed EST to UTC and aggregated without forward filling. The
live market-data route order is intentionally unchanged.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import lzma
import math
import os
import random
import re
import struct
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as wall_time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from app.data.historical_15m_registry import Historical15mRegistry, Historical15mRoute
from app.data.providers.http import ProviderError
from scripts.backtest import hf_s3
from scripts.backtest import sync_yahoo_history_to_hf as storage

_ALPACA_BASE = "https://data.alpaca.markets/v2/stocks"
_DUKASCOPY_BASE = "https://datafeed.dukascopy.com/datafeed"
_HISTDATA_REFERER_BASE = (
    "https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes"
)
_HISTDATA_DOWNLOAD_URL = "https://www.histdata.com/get.php"
_HISTDATA_EST = timezone(timedelta(hours=-5), name="EST")
_NAMESPACE = "bronze/historical-15m-repair/v1"
_MANIFEST_NAMESPACE = "manifests/historical-15m-repair/v1"
_SCHEMA_VERSION = 1
_DUKASCOPY_RECORD = struct.Struct(">5If")
_US_EASTERN = ZoneInfo("America/New_York")
_TRANSIENT_HTTP_STATUS = {408, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None


@dataclass(frozen=True)
class Partition:
    timeframe: str
    year: int
    rows: int
    object_key: str
    sha256: str
    first_timestamp: str
    last_timestamp: str
    reused_verified: bool
    month: int | None = None


class DukascopyAcquisitionError(ProviderError):
    """Fail-closed provider error that carries resumability evidence."""

    def __init__(self, message: str, *, evidence: dict[str, object]) -> None:
        super().__init__(message)
        self.evidence = evidence


class DukascopyPermanentError(ProviderError):
    """A request failure that deferred sweeps must not retry."""


class HistDataAcquisitionError(ProviderError):
    """Fail-closed HistData error with archive-level diagnostics."""

    def __init__(self, message: str, *, evidence: dict[str, object]) -> None:
        super().__init__(message)
        self.evidence = evidence


def discover_routes() -> list[Historical15mRoute]:
    return list(Historical15mRegistry.load().all())


def _positive_env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    value = float(raw) if raw else default
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _positive_env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    value = int(raw) if raw else default
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def _retry_after_seconds(exc: urllib.error.HTTPError, *, now: datetime | None = None) -> float:
    value = exc.headers.get("Retry-After") if exc.headers is not None else None
    if not value:
        return 0.0
    text = value.strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return 0.0
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        return max(0.0, (parsed.astimezone(timezone.utc) - current).total_seconds())


def _retry_delay(attempt: int, exc: BaseException | None = None) -> float:
    base = _positive_env_float("DUKASCOPY_RETRY_BASE_SECONDS", 2.0)
    maximum = _positive_env_float("DUKASCOPY_RETRY_MAX_SECONDS", 60.0)
    jitter_cap = _positive_env_float("DUKASCOPY_RETRY_JITTER_SECONDS", 1.0)
    exponential = min(maximum, base * (2 ** (attempt - 1)))
    retry_after = _retry_after_seconds(exc) if isinstance(exc, urllib.error.HTTPError) else 0.0
    return max(exponential, retry_after) + random.uniform(0.0, jitter_cap)


def _request_bytes(
    url: str,
    *,
    attempts: int | None = None,
    transport_attempts: int | None = None,
) -> bytes:
    http_budget = attempts or _positive_env_int("DUKASCOPY_HTTP_ATTEMPTS", 7)
    transport_budget = transport_attempts or (
        attempts or _positive_env_int("DUKASCOPY_TRANSPORT_ATTEMPTS", 10)
    )
    http_failures = 0
    transport_failures = 0
    while True:
        failure: BaseException | None = None
        retry_number = 0
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Trading-System-V3 historical-15m-repair/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                if response.status != 200:
                    raise ProviderError(f"historical data HTTP {response.status}")
                return response.read()
        except urllib.error.HTTPError as exc:
            failure = exc
            if exc.code == 404:
                return b""
            retryable = exc.code in _TRANSIENT_HTTP_STATUS
            http_failures += 1
            if not retryable:
                raise DukascopyPermanentError(f"historical data HTTP {exc.code}") from exc
            if http_failures >= http_budget:
                raise ProviderError(f"historical data HTTP {exc.code}") from exc
            retry_number = http_failures
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            failure = exc
            transport_failures += 1
            if transport_failures >= transport_budget:
                raise ProviderError("historical data request failed") from exc
            retry_number = transport_failures
        time.sleep(_retry_delay(retry_number, failure))


def _pace_dukascopy_request() -> None:
    delay = _positive_env_float("DUKASCOPY_REQUEST_INTERVAL_SECONDS", 0.2)
    if delay:
        time.sleep(delay)


def _histdata_archive_scope(
    year: int, month: int, *, current_year: int | None = None
) -> tuple[str, str]:
    active_year = current_year or datetime.now(timezone.utc).year
    if year > active_year:
        raise ValueError("HistData archive year cannot be in the future")
    if year < active_year:
        return str(year), str(year)
    return f"{year:04d}-{month:02d}", f"{year:04d}{month:02d}"


def _histdata_referer(symbol: str, year: int, month: int) -> str:
    scope, _ = _histdata_archive_scope(year, month)
    suffix = str(year) if len(scope) == 4 else f"{year}/{month}"
    return f"{_HISTDATA_REFERER_BASE}/{symbol.lower()}/{suffix}"


def _histdata_token(page: bytes) -> str:
    text = page.decode("utf-8", errors="replace")
    match = re.search(r"<input\b[^>]*\bid=[\"']tk[\"'][^>]*>", text, re.IGNORECASE)
    if match is None:
        raise ProviderError("HistData download token is missing")
    value = re.search(r"\bvalue=[\"']([^\"']+)[\"']", match.group(0), re.IGNORECASE)
    if value is None or not value.group(1).strip():
        raise ProviderError("HistData download token is empty")
    return value.group(1).strip()


def _histdata_http_bytes(request: urllib.request.Request, *, attempts: int) -> bytes:
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 200:
                    raise ProviderError(f"HistData HTTP {response.status}")
                return response.read()
        except urllib.error.HTTPError as exc:
            retryable = exc.code in _TRANSIENT_HTTP_STATUS
            if not retryable or attempt == attempts:
                raise ProviderError(f"HistData HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == attempts:
                raise ProviderError("HistData request failed") from exc
        delay = min(
            _positive_env_float("HISTDATA_RETRY_MAX_SECONDS", 30.0),
            _positive_env_float("HISTDATA_RETRY_BASE_SECONDS", 2.0) * (2 ** (attempt - 1)),
        )
        time.sleep(delay)
    raise AssertionError("unreachable")


def _request_histdata_archive(
    route: Historical15mRoute,
    *,
    year: int,
    month: int,
) -> tuple[bytes, str]:
    attempts = _positive_env_int("HISTDATA_HTTP_ATTEMPTS", 5)
    archive_scope, datemonth = _histdata_archive_scope(year, month)
    referer = _histdata_referer(route.symbol, year, month)
    common_headers = {
        "User-Agent": "Trading-System-V3 historical-15m-repair/1.0",
        "Accept": "text/html,application/xhtml+xml,application/zip,*/*;q=0.8",
    }
    try:
        page = _histdata_http_bytes(
            urllib.request.Request(referer, headers=common_headers), attempts=attempts
        )
        token = _histdata_token(page)
        form = urllib.parse.urlencode(
            {
                "tk": token,
                "date": str(year),
                "datemonth": datemonth,
                "platform": "ASCII",
                "timeframe": "M1",
                "fxpair": route.symbol,
            }
        ).encode("ascii")
        archive = _histdata_http_bytes(
            urllib.request.Request(
                _HISTDATA_DOWNLOAD_URL,
                data=form,
                headers={
                    **common_headers,
                    "Origin": "https://www.histdata.com",
                    "Referer": referer,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                method="POST",
            ),
            attempts=attempts,
        )
    except ProviderError as exc:
        raise HistDataAcquisitionError(
            f"HistData {route.base_asset}/{route.symbol} archive {archive_scope} failed: {exc}",
            evidence={
                "archive_scope": archive_scope,
                "provider_symbol": route.symbol,
                "request_kind": "annual" if len(archive_scope) == 4 else "monthly",
            },
        ) from exc
    if not zipfile.is_zipfile(io.BytesIO(archive)):
        raise HistDataAcquisitionError(
            f"HistData {route.base_asset}/{route.symbol} archive {archive_scope} is not ZIP",
            evidence={
                "archive_scope": archive_scope,
                "provider_symbol": route.symbol,
                "response_bytes": len(archive),
            },
        )
    return archive, archive_scope


def parse_histdata_archive(
    archive: bytes,
    route: Historical15mRoute,
    *,
    quality: dict[str, int],
) -> list[Candle]:
    output: dict[datetime, Candle] = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        csv_names = [name for name in bundle.namelist() if name.lower().endswith(".csv")]
        if len(csv_names) != 1:
            raise ProviderError(
                f"HistData archive must contain exactly one CSV; found {len(csv_names)}"
            )
        with bundle.open(csv_names[0]) as raw:
            text = io.TextIOWrapper(raw, encoding="ascii", errors="strict", newline="")
            for fields in csv.reader(text, delimiter=";"):
                if not fields or all(not item.strip() for item in fields):
                    continue
                if len(fields) < 5:
                    quality["invalid_rows_dropped"] += 1
                    continue
                try:
                    naive = datetime.strptime(fields[0].strip(), "%Y%m%d %H%M%S")
                    timestamp = naive.replace(tzinfo=_HISTDATA_EST).astimezone(timezone.utc)
                    scale = route.price_multiplier / route.price_divisor
                    candle = Candle(
                        timestamp=timestamp,
                        open=_parse_decimal(fields[1], "open") * scale,
                        high=_parse_decimal(fields[2], "high") * scale,
                        low=_parse_decimal(fields[3], "low") * scale,
                        close=_parse_decimal(fields[4], "close") * scale,
                        volume=(
                            _parse_decimal(fields[5], "volume")
                            if len(fields) > 5 and fields[5].strip()
                            else None
                        ),
                    )
                except (ProviderError, ValueError):
                    quality["invalid_rows_dropped"] += 1
                    continue
                if not _valid_candle(candle):
                    quality["ohlc_invariant_rows_dropped"] += 1
                    continue
                prior = output.get(timestamp)
                if prior is not None and prior != candle:
                    raise ProviderError(
                        f"HistData conflicting duplicate at {timestamp.isoformat()}"
                    )
                output[timestamp] = candle
    return [output[key] for key in sorted(output)]


def fetch_histdata_15m(
    route: Historical15mRoute,
    *,
    start: datetime,
    end: datetime,
    quality: dict[str, int],
    archive_cache: dict[str, list[Candle]],
) -> tuple[list[Candle], list[str]]:
    local_start = start.astimezone(_HISTDATA_EST)
    local_end = (end - timedelta(microseconds=1)).astimezone(_HISTDATA_EST)
    cursor = date(local_start.year, local_start.month, 1)
    final = date(local_end.year, local_end.month, 1)
    requested: list[tuple[int, int]] = []
    while cursor <= final:
        requested.append((cursor.year, cursor.month))
        cursor = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )

    scopes: list[str] = []
    combined: dict[datetime, Candle] = {}
    for year, month in requested:
        archive_scope, _ = _histdata_archive_scope(year, month)
        source = archive_cache.get(archive_scope)
        if source is None:
            archive, archive_scope = _request_histdata_archive(route, year=year, month=month)
            source = parse_histdata_archive(archive, route, quality=quality)
            archive_cache[archive_scope] = source
        if archive_scope not in scopes:
            scopes.append(archive_scope)
        for row in source:
            if start <= row.timestamp < end:
                prior = combined.get(row.timestamp)
                if prior is not None and prior != row:
                    raise ProviderError(
                        f"HistData conflicting archive overlap at {row.timestamp.isoformat()}"
                    )
                combined[row.timestamp] = row
    selected = [combined[key] for key in sorted(combined)]
    return aggregate_candles(selected, "15m", session="utc"), scopes


def _request_alpaca_json(url: str, *, attempts: int = 6) -> dict[str, object]:
    key = os.environ.get("ALPACA_API_KEY_ID", "").strip()
    secret = os.environ.get("ALPACA_API_SECRET_KEY", "").strip()
    if not key or not secret:
        raise RuntimeError("ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY are required")
    delay = 1.0
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "APCA-API-KEY-ID": key,
                "APCA-API-SECRET-KEY": secret,
                "User-Agent": "Trading-System-V3 historical-15m-repair/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise ProviderError("Alpaca response is not an object")
            return payload
        except urllib.error.HTTPError as exc:
            retryable = exc.code in {408, 429} or 500 <= exc.code < 600
            if not retryable or attempt == attempts:
                raise ProviderError(f"Alpaca HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            if attempt == attempts:
                raise ProviderError("Alpaca request or response failed") from exc
        time.sleep(delay)
        delay = min(delay * 2, 30.0)
    raise AssertionError("unreachable")


def _parse_decimal(value: object, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ProviderError(f"invalid {field} value") from exc
    if not parsed.is_finite():
        raise ProviderError(f"non-finite {field} value")
    return parsed


def _valid_candle(candle: Candle) -> bool:
    return (
        candle.low <= candle.high
        and candle.low <= candle.open <= candle.high
        and candle.low <= candle.close <= candle.high
    )


def _is_us_rth(timestamp: datetime) -> bool:
    local = timestamp.astimezone(_US_EASTERN)
    value = local.timetz().replace(tzinfo=None)
    return local.weekday() < 5 and wall_time(9, 30) <= value < wall_time(16, 0)


def fetch_alpaca_15m(
    route: Historical15mRoute,
    *,
    start: datetime,
    end: datetime,
    quality: dict[str, int],
) -> list[Candle]:
    effective_end = min(end, datetime.now(timezone.utc) - timedelta(minutes=16))
    if effective_end <= start:
        raise ProviderError("Alpaca effective end must be later than start")
    rows: dict[datetime, Candle] = {}
    token: str | None = None
    while True:
        query: dict[str, str] = {
            "timeframe": "15Min",
            "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "end": effective_end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "adjustment": "all",
            "feed": "sip",
            "sort": "asc",
            "limit": "10000",
        }
        if token:
            query["page_token"] = token
        url = f"{_ALPACA_BASE}/{urllib.parse.quote(route.symbol, safe='')}/bars?{urllib.parse.urlencode(query)}"
        payload = _request_alpaca_json(url)
        raw_bars = payload.get("bars") or []
        if not isinstance(raw_bars, list):
            raise ProviderError("Alpaca bars field is not a list")
        for raw in raw_bars:
            if not isinstance(raw, dict):
                quality["invalid_rows_dropped"] += 1
                continue
            try:
                timestamp = datetime.fromisoformat(str(raw["t"]).replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    raise ValueError("naive timestamp")
                timestamp = timestamp.astimezone(timezone.utc)
                if route.session == "us_rth" and not _is_us_rth(timestamp):
                    quality["out_of_session_rows_dropped"] += 1
                    continue
                multiplier = route.price_multiplier
                candle = Candle(
                    timestamp=timestamp,
                    open=_parse_decimal(raw["o"], "open") * multiplier,
                    high=_parse_decimal(raw["h"], "high") * multiplier,
                    low=_parse_decimal(raw["l"], "low") * multiplier,
                    close=_parse_decimal(raw["c"], "close") * multiplier,
                    volume=_parse_decimal(raw["v"], "volume") if raw.get("v") is not None else None,
                )
            except (KeyError, TypeError, ValueError, ProviderError):
                quality["invalid_rows_dropped"] += 1
                continue
            if not _valid_candle(candle):
                quality["ohlc_invariant_rows_dropped"] += 1
                continue
            prior = rows.get(timestamp)
            if prior is not None and prior != candle:
                raise ProviderError(f"Alpaca conflicting duplicate at {timestamp.isoformat()}")
            rows[timestamp] = candle
        next_token = payload.get("next_page_token")
        if not next_token:
            break
        token = str(next_token)
    return [rows[key] for key in sorted(rows)]


def _dukascopy_url(route: Historical15mRoute, day: date) -> str:
    # Dukascopy uses zero-based month directories.
    return (
        f"{_DUKASCOPY_BASE}/{route.symbol}/{day.year:04d}/{day.month - 1:02d}/"
        f"{day.day:02d}/BID_candles_min_1.bi5"
    )


def parse_dukascopy_day(
    compressed: bytes,
    route: Historical15mRoute,
    day: date,
    *,
    quality: dict[str, int],
) -> list[Candle]:
    if not compressed:
        return []
    try:
        raw = lzma.decompress(compressed)
    except lzma.LZMAError as exc:
        raise ProviderError(f"invalid Dukascopy BI5 payload for {day.isoformat()}") from exc
    if len(raw) % _DUKASCOPY_RECORD.size:
        raise ProviderError(f"invalid Dukascopy record length for {day.isoformat()}")
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    output: list[Candle] = []
    for offset in range(0, len(raw), _DUKASCOPY_RECORD.size):
        seconds, open_raw, high_raw, low_raw, close_raw, volume_raw = _DUKASCOPY_RECORD.unpack_from(
            raw, offset
        )
        if seconds >= 86_400 or not math.isfinite(volume_raw):
            quality["invalid_rows_dropped"] += 1
            continue
        scale = route.price_multiplier / route.price_divisor
        candle = Candle(
            timestamp=start + timedelta(seconds=seconds),
            open=Decimal(open_raw) * scale,
            high=Decimal(high_raw) * scale,
            low=Decimal(low_raw) * scale,
            close=Decimal(close_raw) * scale,
            volume=Decimal(str(volume_raw)),
        )
        if not _valid_candle(candle):
            quality["ohlc_invariant_rows_dropped"] += 1
            continue
        output.append(candle)
    return output


def _date_range(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def fetch_dukascopy_15m(
    route: Historical15mRoute,
    *,
    start: datetime,
    end: datetime,
    quality: dict[str, int],
) -> list[Candle]:
    minutes: dict[datetime, Candle] = {}
    final_day = (end - timedelta(microseconds=1)).date()
    pending = list(_date_range(start.date(), final_day))
    failures: dict[date, str] = {}
    sweeps = _positive_env_int("DUKASCOPY_DEFERRED_RETRY_SWEEPS", 3)
    cooldown = _positive_env_float("DUKASCOPY_DEFERRED_RETRY_COOLDOWN_SECONDS", 60.0)
    recovered = 0

    for sweep in range(1, sweeps + 1):
        if sweep > 1 and cooldown:
            time.sleep(cooldown)
        retry_days: list[date] = []
        for day in pending:
            try:
                compressed = _request_bytes(_dukascopy_url(route, day))
            except DukascopyPermanentError as exc:
                raise DukascopyAcquisitionError(
                    f"Dukascopy {route.base_asset}/{route.symbol} failed on "
                    f"{day.isoformat()}: {exc}",
                    evidence={
                        "failed_date": day.isoformat(),
                        "pending_days": [day.isoformat()],
                        "pending_day_errors": {day.isoformat(): str(exc)},
                        "deferred_retry_sweeps": sweep,
                        "pending_days_recovered": recovered,
                        "failure_class": "non_retryable_http",
                    },
                ) from exc
            except ProviderError as exc:
                failures[day] = str(exc)
                retry_days.append(day)
                continue
            _pace_dukascopy_request()
            daily = parse_dukascopy_day(compressed, route, day, quality=quality)
            if not daily:
                quality["source_days_without_rows"] += 1
            if day in failures:
                recovered += 1
                failures.pop(day, None)
            for candle in daily:
                if candle.timestamp < start or candle.timestamp >= end:
                    continue
                prior = minutes.get(candle.timestamp)
                if prior is not None and prior != candle:
                    raise ProviderError(
                        f"Dukascopy conflicting duplicate at {candle.timestamp.isoformat()}"
                    )
                minutes[candle.timestamp] = candle
        pending = retry_days
        if not pending:
            break

    if pending:
        failed_days = [item.isoformat() for item in pending]
        first = pending[0]
        message = (
            f"Dukascopy {route.base_asset}/{route.symbol} failed on {first.isoformat()}: "
            f"{failures[first]}"
        )
        raise DukascopyAcquisitionError(
            message,
            evidence={
                "failed_date": first.isoformat(),
                "pending_days": failed_days,
                "pending_day_errors": {item.isoformat(): failures[item] for item in pending},
                "deferred_retry_sweeps": sweeps,
                "pending_days_recovered": recovered,
            },
        )
    quality["pending_days_recovered"] = quality.get("pending_days_recovered", 0) + recovered
    return aggregate_candles(list(minutes.values()), "15m", session="utc")


def _bucket_start(timestamp: datetime, timeframe: str, session: str) -> datetime:
    if session == "us_rth":
        local = timestamp.astimezone(_US_EASTERN)
        session_open = local.replace(hour=9, minute=30, second=0, microsecond=0)
        elapsed = int((local - session_open).total_seconds())
        if timeframe == "1d":
            return session_open.astimezone(timezone.utc)
        seconds = 3_600 if timeframe == "1h" else 14_400
        return (session_open + timedelta(seconds=(elapsed // seconds) * seconds)).astimezone(
            timezone.utc
        )
    epoch = int(timestamp.timestamp())
    seconds = {"15m": 900, "1h": 3_600, "4h": 14_400, "1d": 86_400}[timeframe]
    return datetime.fromtimestamp(epoch - epoch % seconds, tz=timezone.utc)


def aggregate_candles(rows: list[Candle], timeframe: str, *, session: str) -> list[Candle]:
    buckets: dict[datetime, list[Candle]] = {}
    for row in rows:
        buckets.setdefault(_bucket_start(row.timestamp, timeframe, session), []).append(row)
    output: list[Candle] = []
    for bucket, group in sorted(buckets.items()):
        ordered = sorted(group, key=lambda item: item.timestamp)
        volumes = [item.volume for item in ordered if item.volume is not None]
        output.append(
            Candle(
                timestamp=bucket,
                open=ordered[0].open,
                high=max(item.high for item in ordered),
                low=min(item.low for item in ordered),
                close=ordered[-1].close,
                volume=sum(volumes, Decimal("0")) if volumes else None,
            )
        )
    return output


def _year_groups(rows: list[Candle]) -> Iterable[tuple[int, list[Candle]]]:
    groups: dict[int, list[Candle]] = {}
    for row in rows:
        groups.setdefault(row.timestamp.year, []).append(row)
    for year in sorted(groups):
        yield year, sorted(groups[year], key=lambda item: item.timestamp)


def _source_kind(route: Historical15mRoute) -> str:
    if route.provider == "alpaca_sip":
        return "alpaca_historical_sip_adjusted_all_us_rth"
    if route.provider == "histdata":
        return "histdata_generic_ascii_bid_m1_aggregated_no_fill"
    return "dukascopy_public_bid_m1_aggregated_no_fill"


def _write_parquet(
    path: Path,
    route: Historical15mRoute,
    timeframe: str,
    rows: list[Candle],
) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("pyarrow is required; install the research-data extra") from exc
    table = pa.table(
        {
            "canonical_symbol": [route.base_asset] * len(rows),
            "provider": [route.provider] * len(rows),
            "provider_symbol": [route.symbol] * len(rows),
            "asset_class": [route.asset_class] * len(rows),
            "timeframe": [timeframe] * len(rows),
            "timestamp": [item.timestamp for item in rows],
            "open": [str(item.open) for item in rows],
            "high": [str(item.high) for item in rows],
            "low": [str(item.low) for item in rows],
            "close": [str(item.close) for item in rows],
            "adjusted_close": [str(item.close) for item in rows],
            "volume": [str(item.volume) if item.volume is not None else None for item in rows],
            "price_multiplier": [str(route.price_multiplier)] * len(rows),
            "source_kind": [_source_kind(route)] * len(rows),
        }
    )
    pq.write_table(table, path, compression="zstd", version="2.6")


def _partition_key(
    route: Historical15mRoute,
    timeframe: str,
    year: int,
    month: int | None = None,
) -> str:
    prefix = (
        f"{_NAMESPACE}/provider={storage._slug(route.provider)}/"
        f"canonical={storage._slug(route.base_asset)}/market={storage._slug(route.symbol)}/"
        f"timeframe={timeframe}/year={year:04d}/"
    )
    return (
        f"{prefix}month={month:02d}/part-000.parquet"
        if month is not None
        else f"{prefix}part-000.parquet"
    )


def _store_partition(
    route: Historical15mRoute,
    timeframe: str,
    year: int,
    rows: list[Candle],
    *,
    force: bool,
    month: int | None = None,
) -> Partition:
    key = _partition_key(route, timeframe, year, month)
    with tempfile.TemporaryDirectory(prefix="historical-15m-repair-") as temp_dir:
        path = Path(temp_dir) / "part-000.parquet"
        _write_parquet(path, route, timeframe, rows)
        digest = storage._sha256(path)
        existing = storage._remote_sha256(key)
        reused = existing == digest and not force
        if not reused:
            storage._put_verified(path, key, digest, "application/vnd.apache.parquet")
    return Partition(
        timeframe=timeframe,
        year=year,
        rows=len(rows),
        object_key=key,
        sha256=digest,
        first_timestamp=rows[0].timestamp.isoformat(),
        last_timestamp=rows[-1].timestamp.isoformat(),
        reused_verified=reused,
        month=month,
    )


def _route_identity(route: Historical15mRoute) -> dict[str, object]:
    return {
        "canonical_symbol": route.base_asset,
        "base_asset": route.base_asset,
        "asset_class": route.asset_class,
        "provider": route.provider,
        "provider_symbol": route.symbol,
        "price_multiplier": str(route.price_multiplier),
        "requires_volume": route.asset_class == "equity",
        "route_origin": "historical_15m_repair_registry",
    }


def _checkpoint_key(route: Historical15mRoute, year: int) -> str:
    return (
        f"{_MANIFEST_NAMESPACE}/checkpoints/provider={storage._slug(route.provider)}/"
        f"canonical={storage._slug(route.base_asset)}/market={storage._slug(route.symbol)}/"
        f"year={year:04d}.json"
    )


def _month_checkpoint_key(route: Historical15mRoute, year: int, month: int) -> str:
    return (
        f"{_MANIFEST_NAMESPACE}/checkpoints/provider={storage._slug(route.provider)}/"
        f"canonical={storage._slug(route.base_asset)}/market={storage._slug(route.symbol)}/"
        f"year={year:04d}/month={month:02d}.json"
    )


def _load_remote_json(key: str) -> dict[str, object] | None:
    with tempfile.TemporaryDirectory(prefix="historical-15m-checkpoint-") as temp_dir:
        target = Path(temp_dir) / "checkpoint.json"
        result = storage._aws(
            "s3api",
            "get-object",
            "--bucket",
            storage._bucket(),
            "--key",
            key,
            str(target),
            check=False,
        )
        if storage._missing(result):
            return None
        payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ProviderError(f"checkpoint is not a JSON object: {key}")
    return payload


def _partition_from_checkpoint(raw: object) -> Partition:
    if not isinstance(raw, dict):
        raise ValueError("checkpoint partition must be an object")
    return Partition(
        timeframe=str(raw["timeframe"]),
        year=int(raw["year"]),
        rows=int(raw["rows"]),
        object_key=str(raw["object_key"]),
        sha256=str(raw["sha256"]),
        first_timestamp=str(raw["first_timestamp"]),
        last_timestamp=str(raw["last_timestamp"]),
        reused_verified=True,
        month=int(raw["month"]) if raw.get("month") is not None else None,
    )


def _load_valid_year_checkpoint(
    route: Historical15mRoute,
    *,
    year: int,
    start: datetime,
    end: datetime,
    force: bool,
) -> tuple[list[Partition], dict[str, int]] | None:
    if force:
        return None
    key = _checkpoint_key(route, year)
    checkpoint = _load_remote_json(key)
    if checkpoint is None:
        return None
    expected = _route_identity(route)
    actual_route = checkpoint.get("route")
    if (
        checkpoint.get("status") != "COMPLETE_YEAR_CHECKPOINT"
        or actual_route != expected
        or checkpoint.get("range_start") != start.isoformat()
        or checkpoint.get("range_end") != end.isoformat()
    ):
        return None
    try:
        partitions = [_partition_from_checkpoint(item) for item in checkpoint.get("partitions", [])]
    except (KeyError, TypeError, ValueError):
        return None
    if (
        len(partitions) != 4
        or {item.timeframe for item in partitions} != {"15m", "1h", "4h", "1d"}
        or any(item.year != year or item.rows <= 0 for item in partitions)
    ):
        return None
    for partition in partitions:
        if len(partition.sha256) != 64:
            return None
        if storage._remote_sha256(partition.object_key) != partition.sha256:
            return None
    raw_quality = checkpoint.get("quality")
    if not isinstance(raw_quality, dict):
        return None
    quality = {
        name: int(raw_quality.get(name) or 0)
        for name in (
            "invalid_rows_dropped",
            "ohlc_invariant_rows_dropped",
            "out_of_session_rows_dropped",
            "source_days_without_rows",
        )
    }
    return partitions, quality


def _write_year_checkpoint(
    route: Historical15mRoute,
    *,
    year: int,
    start: datetime,
    end: datetime,
    quality: dict[str, int],
    partitions: list[Partition],
) -> str:
    key = _checkpoint_key(route, year)
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "status": "COMPLETE_YEAR_CHECKPOINT",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "route": _route_identity(route),
        "year": year,
        "range_start": start.isoformat(),
        "range_end": end.isoformat(),
        "quality": quality,
        "integrity_policy": "all_partition_sha256_read_back_verified_before_checkpoint",
        "partitions": [asdict(item) for item in partitions],
    }
    storage._put_json(payload, key)
    return key


def _load_valid_month_checkpoint(
    route: Historical15mRoute,
    *,
    year: int,
    month: int,
    start: datetime,
    end: datetime,
    force: bool,
) -> tuple[list[Partition], dict[str, int]] | None:
    if force:
        return None
    checkpoint = _load_remote_json(_month_checkpoint_key(route, year, month))
    if checkpoint is None:
        return None
    if (
        checkpoint.get("status") != "COMPLETE_MONTH_CHECKPOINT"
        or checkpoint.get("route") != _route_identity(route)
        or checkpoint.get("range_start") != start.isoformat()
        or checkpoint.get("range_end") != end.isoformat()
        or checkpoint.get("year") != year
        or checkpoint.get("month") != month
    ):
        return None
    try:
        partitions = [_partition_from_checkpoint(item) for item in checkpoint.get("partitions", [])]
    except (KeyError, TypeError, ValueError):
        return None
    if (
        len(partitions) != 4
        or {item.timeframe for item in partitions} != {"15m", "1h", "4h", "1d"}
        or any(item.year != year or item.month != month or item.rows <= 0 for item in partitions)
    ):
        return None
    for partition in partitions:
        if len(partition.sha256) != 64:
            return None
        if storage._remote_sha256(partition.object_key) != partition.sha256:
            return None
    raw_quality = checkpoint.get("quality")
    if not isinstance(raw_quality, dict):
        return None
    quality = {name: int(raw_quality.get(name) or 0) for name in _empty_quality()}
    return partitions, quality


def _write_month_checkpoint(
    route: Historical15mRoute,
    *,
    year: int,
    month: int,
    start: datetime,
    end: datetime,
    quality: dict[str, int],
    partitions: list[Partition],
) -> str:
    key = _month_checkpoint_key(route, year, month)
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "status": "COMPLETE_MONTH_CHECKPOINT",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "route": _route_identity(route),
        "year": year,
        "month": month,
        "range_start": start.isoformat(),
        "range_end": end.isoformat(),
        "quality": quality,
        "integrity_policy": "all_partition_sha256_read_back_verified_before_checkpoint",
        "partitions": [asdict(item) for item in partitions],
    }
    storage._put_json(payload, key)
    return key


def _empty_quality() -> dict[str, int]:
    return {
        "invalid_rows_dropped": 0,
        "ohlc_invariant_rows_dropped": 0,
        "out_of_session_rows_dropped": 0,
        "source_days_without_rows": 0,
        "pending_days_recovered": 0,
    }


def _add_quality(target: dict[str, int], source: dict[str, int]) -> None:
    for name in target:
        target[name] += int(source.get(name, 0))


def _coverage_from_partitions(partitions: list[Partition]) -> dict[str, object]:
    coverage: dict[str, object] = {}
    for timeframe in ("15m", "1h", "4h", "1d"):
        selected = [item for item in partitions if item.timeframe == timeframe]
        if not selected:
            continue
        coverage[timeframe] = {
            "rows": sum(item.rows for item in selected),
            "first_timestamp": min(item.first_timestamp for item in selected),
            "last_timestamp": max(item.last_timestamp for item in selected),
        }
    return coverage


def _year_ranges(start: datetime, end: datetime) -> Iterable[tuple[int, datetime, datetime]]:
    year = start.year
    while year <= (end - timedelta(microseconds=1)).year:
        year_start = datetime(year, 1, 1, tzinfo=timezone.utc)
        next_year = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        chunk_start = max(start, year_start)
        chunk_end = min(end, next_year)
        if chunk_start < chunk_end:
            yield year, chunk_start, chunk_end
        year += 1


def _month_ranges(start: datetime, end: datetime) -> Iterable[tuple[int, int, datetime, datetime]]:
    cursor = datetime(start.year, start.month, 1, tzinfo=timezone.utc)
    while cursor < end:
        next_month = (
            datetime(cursor.year + 1, 1, 1, tzinfo=timezone.utc)
            if cursor.month == 12
            else datetime(cursor.year, cursor.month + 1, 1, tzinfo=timezone.utc)
        )
        chunk_start = max(start, cursor)
        chunk_end = min(end, next_month)
        if chunk_start < chunk_end:
            yield cursor.year, cursor.month, chunk_start, chunk_end
        cursor = next_month


def _validate_coverage(
    route: Historical15mRoute,
    rows: list[Candle],
    *,
    start: datetime,
) -> None:
    if not rows:
        raise ProviderError("source returned no valid 15m history")
    if route.listing_limited:
        return
    span_days = (rows[-1].timestamp - rows[0].timestamp).days
    if span_days < route.minimum_history_days:
        raise ProviderError(
            f"15m history span is {span_days} days; required {route.minimum_history_days}"
        )
    if rows[0].timestamp > start + timedelta(days=14):
        raise ProviderError("15m history begins materially after the reviewed requested start")


def _datasets_from_fifteen(
    route: Historical15mRoute, fifteen: list[Candle]
) -> dict[str, list[Candle]]:
    datasets = {
        "15m": fifteen,
        "1h": aggregate_candles(fifteen, "1h", session=route.session),
        "4h": aggregate_candles(fifteen, "4h", session=route.session),
        "1d": aggregate_candles(fifteen, "1d", session=route.session),
    }
    missing = [timeframe for timeframe, rows in datasets.items() if not rows]
    if missing:
        raise ProviderError(f"derived history is empty for: {','.join(missing)}")
    return datasets


def _validate_partition_coverage(
    route: Historical15mRoute, partitions: list[Partition], *, start: datetime
) -> None:
    fifteen = sorted(
        (item for item in partitions if item.timeframe == "15m"),
        key=lambda item: item.first_timestamp,
    )
    if not fifteen:
        raise ProviderError("source returned no valid 15m history")
    if route.listing_limited:
        return
    first = datetime.fromisoformat(fifteen[0].first_timestamp)
    last = datetime.fromisoformat(fifteen[-1].last_timestamp)
    span_days = (last - first).days
    if span_days < route.minimum_history_days:
        raise ProviderError(
            f"15m history span is {span_days} days; required {route.minimum_history_days}"
        )
    if first > start + timedelta(days=14):
        raise ProviderError("15m history begins materially after the reviewed requested start")


def _sync_dukascopy_incremental(
    route: Historical15mRoute,
    *,
    start: datetime,
    end: datetime,
    force: bool,
) -> dict[str, object]:
    quality = _empty_quality()
    partitions: list[Partition] = []
    checkpoint_keys: list[str] = []
    legacy_years_reused: list[int] = []
    months_reused: list[str] = []
    months_written: list[str] = []

    for year, chunk_start, chunk_end in _year_ranges(start, end):
        cached = _load_valid_year_checkpoint(
            route, year=year, start=chunk_start, end=chunk_end, force=force
        )
        if cached is not None:
            year_partitions, year_quality = cached
            partitions.extend(year_partitions)
            _add_quality(quality, year_quality)
            checkpoint_keys.append(_checkpoint_key(route, year))
            legacy_years_reused.append(year)
            continue

        for month_year, month, month_start, month_end in _month_ranges(chunk_start, chunk_end):
            month_label = f"{month_year:04d}-{month:02d}"
            cached_month = _load_valid_month_checkpoint(
                route,
                year=month_year,
                month=month,
                start=month_start,
                end=month_end,
                force=force,
            )
            if cached_month is not None:
                month_partitions, month_quality = cached_month
                partitions.extend(month_partitions)
                _add_quality(quality, month_quality)
                checkpoint_keys.append(_month_checkpoint_key(route, month_year, month))
                months_reused.append(month_label)
                continue

            month_quality = _empty_quality()
            try:
                fifteen = fetch_dukascopy_15m(
                    route,
                    start=month_start,
                    end=month_end,
                    quality=month_quality,
                )
            except DukascopyAcquisitionError as exc:
                evidence = {
                    "checkpoint_policy": "legacy_year_then_month_sha256_verified_resume",
                    "legacy_years_reused": legacy_years_reused,
                    "months_reused": months_reused,
                    "months_written": months_written,
                    "failed_month": month_label,
                    **exc.evidence,
                }
                raise DukascopyAcquisitionError(str(exc), evidence=evidence) from exc
            if not fifteen:
                evidence = {
                    "checkpoint_policy": "legacy_year_then_month_sha256_verified_resume",
                    "legacy_years_reused": legacy_years_reused,
                    "months_reused": months_reused,
                    "months_written": months_written,
                    "failed_month": month_label,
                    "pending_days": [],
                }
                raise DukascopyAcquisitionError(
                    f"Dukascopy {route.base_asset}/{route.symbol} returned no valid rows "
                    f"for {month_start.date()}..{month_end.date()}",
                    evidence=evidence,
                )
            datasets = _datasets_from_fifteen(route, fifteen)
            month_partitions = [
                _store_partition(
                    route,
                    timeframe,
                    month_year,
                    rows,
                    force=force,
                    month=month,
                )
                for timeframe, rows in datasets.items()
            ]
            checkpoint_keys.append(
                _write_month_checkpoint(
                    route,
                    year=month_year,
                    month=month,
                    start=month_start,
                    end=month_end,
                    quality=month_quality,
                    partitions=month_partitions,
                )
            )
            months_written.append(month_label)
            partitions.extend(month_partitions)
            _add_quality(quality, month_quality)

    _validate_partition_coverage(route, partitions, start=start)
    manifest: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "status": "COMPLETE",
        "route": _route_identity(route),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "source_kind": _source_kind(route),
        "qualification_scope": "research_backtest_only_live_route_order_unchanged",
        "history_policy": "provider_backed_15m_with_1h_4h_1d_deterministically_derived",
        "session_policy": route.session,
        "adjustment_policy": "dukascopy_bid_m1_source_no_forward_fill",
        "proxy_for": route.proxy_for,
        "listing_limited": route.listing_limited,
        "gap_policy": "preserve_source_market_sessions_no_fill",
        "invalid_source_row_policy": "drop_and_record_never_clamp",
        "quality": quality,
        "source_ohlc_invariant_rows_dropped": quality["ohlc_invariant_rows_dropped"],
        "coverage": _coverage_from_partitions(partitions),
        "total_rows": sum(item.rows for item in partitions),
        "partition_objects_recorded": len(partitions),
        "reused_verified_partition_objects": sum(item.reused_verified for item in partitions),
        "uploaded_or_replaced_partition_objects": sum(
            not item.reused_verified for item in partitions
        ),
        "integrity_policy": "sha256_manifest_compare_upload_verify_downloaded_bytes",
        "checkpoint_policy": "legacy_year_then_month_sha256_verified_resume",
        "legacy_years_reused": legacy_years_reused,
        "months_reused": months_reused,
        "months_written": months_written,
        "checkpoint_years_reused": len(legacy_years_reused),
        "checkpoint_months_reused": len(months_reused),
        "checkpoint_months_written": len(months_written),
        "checkpoint_manifest_keys": checkpoint_keys,
        "partitions": [asdict(item) for item in partitions],
    }
    manifest_key = (
        f"{_MANIFEST_NAMESPACE}/routes/provider={storage._slug(route.provider)}/"
        f"canonical={storage._slug(route.base_asset)}/market={storage._slug(route.symbol)}.json"
    )
    storage._put_json(manifest, manifest_key)
    manifest["manifest_object_key"] = manifest_key
    return manifest


def _progress_event(event: str, **fields: object) -> None:
    print(
        json.dumps(
            {
                "event": event,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **fields,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def _sync_histdata_incremental(
    route: Historical15mRoute,
    *,
    start: datetime,
    end: datetime,
    force: bool,
) -> dict[str, object]:
    quality = _empty_quality()
    partitions: list[Partition] = []
    checkpoint_keys: list[str] = []
    months_reused: list[str] = []
    months_written: list[str] = []
    archive_scopes: set[str] = set()
    archive_cache: dict[str, list[Candle]] = {}
    route_started = time.monotonic()

    for year, chunk_start, chunk_end in _year_ranges(start, end):
        for month_year, month, month_start, month_end in _month_ranges(chunk_start, chunk_end):
            month_started = time.monotonic()
            month_label = f"{month_year:04d}-{month:02d}"
            _progress_event(
                "histdata_month_start",
                base_asset=route.base_asset,
                month=month_label,
                range_start=month_start.isoformat(),
                range_end=month_end.isoformat(),
            )
            cached = _load_valid_month_checkpoint(
                route,
                year=month_year,
                month=month,
                start=month_start,
                end=month_end,
                force=force,
            )
            if cached is not None:
                month_partitions, month_quality = cached
                partitions.extend(month_partitions)
                _add_quality(quality, month_quality)
                checkpoint_keys.append(_month_checkpoint_key(route, month_year, month))
                months_reused.append(month_label)
                _progress_event(
                    "histdata_month_reused",
                    base_asset=route.base_asset,
                    month=month_label,
                    elapsed_seconds=round(time.monotonic() - month_started, 3),
                    rows=sum(item.rows for item in month_partitions),
                )
                continue

            month_quality = _empty_quality()
            try:
                fifteen, used_scopes = fetch_histdata_15m(
                    route,
                    start=month_start,
                    end=month_end,
                    quality=month_quality,
                    archive_cache=archive_cache,
                )
            except HistDataAcquisitionError as exc:
                evidence = {
                    "checkpoint_policy": "histdata_month_sha256_verified_resume",
                    "months_reused": months_reused,
                    "months_written": months_written,
                    "failed_month": month_label,
                    "archive_scopes_downloaded": sorted(archive_scopes),
                    **exc.evidence,
                }
                raise HistDataAcquisitionError(str(exc), evidence=evidence) from exc
            archive_scopes.update(used_scopes)
            if not fifteen:
                raise HistDataAcquisitionError(
                    f"HistData {route.base_asset}/{route.symbol} returned no valid rows "
                    f"for {month_start.date()}..{month_end.date()}",
                    evidence={
                        "checkpoint_policy": "histdata_month_sha256_verified_resume",
                        "months_reused": months_reused,
                        "months_written": months_written,
                        "failed_month": month_label,
                        "archive_scopes": used_scopes,
                    },
                )
            datasets = _datasets_from_fifteen(route, fifteen)
            month_partitions = [
                _store_partition(
                    route,
                    timeframe,
                    month_year,
                    rows,
                    force=force,
                    month=month,
                )
                for timeframe, rows in datasets.items()
            ]
            checkpoint_keys.append(
                _write_month_checkpoint(
                    route,
                    year=month_year,
                    month=month,
                    start=month_start,
                    end=month_end,
                    quality=month_quality,
                    partitions=month_partitions,
                )
            )
            months_written.append(month_label)
            partitions.extend(month_partitions)
            _add_quality(quality, month_quality)
            _progress_event(
                "histdata_month_complete",
                base_asset=route.base_asset,
                month=month_label,
                elapsed_seconds=round(time.monotonic() - month_started, 3),
                archive_scopes=used_scopes,
                rows_15m=len(fifteen),
                rows_total=sum(len(rows) for rows in datasets.values()),
            )
        keep_prefix = f"{year:04d}"
        archive_cache = {
            scope: rows
            for scope, rows in archive_cache.items()
            if scope == keep_prefix or scope.startswith(f"{keep_prefix}-")
        }

    _validate_partition_coverage(route, partitions, start=start)
    manifest: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "status": "COMPLETE",
        "route": _route_identity(route),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "source_kind": _source_kind(route),
        "qualification_scope": "research_backtest_only_live_route_order_unchanged",
        "history_policy": "provider_backed_15m_with_1h_4h_1d_deterministically_derived",
        "session_policy": route.session,
        "adjustment_policy": "histdata_bid_m1_fixed_est_to_utc_no_forward_fill",
        "proxy_for": route.proxy_for,
        "listing_limited": route.listing_limited,
        "gap_policy": "preserve_source_market_sessions_no_fill",
        "invalid_source_row_policy": "drop_and_record_never_clamp",
        "quality": quality,
        "source_ohlc_invariant_rows_dropped": quality["ohlc_invariant_rows_dropped"],
        "coverage": _coverage_from_partitions(partitions),
        "total_rows": sum(item.rows for item in partitions),
        "partition_objects_recorded": len(partitions),
        "reused_verified_partition_objects": sum(item.reused_verified for item in partitions),
        "uploaded_or_replaced_partition_objects": sum(
            not item.reused_verified for item in partitions
        ),
        "integrity_policy": "sha256_manifest_compare_upload_verify_downloaded_bytes",
        "checkpoint_policy": "histdata_month_sha256_verified_resume",
        "provider_migration_policy": "clean_histdata_namespace_no_cross_provider_reuse",
        "months_reused": months_reused,
        "months_written": months_written,
        "checkpoint_months_reused": len(months_reused),
        "checkpoint_months_written": len(months_written),
        "checkpoint_manifest_keys": checkpoint_keys,
        "archive_scopes_downloaded": sorted(archive_scopes),
        "elapsed_seconds": round(time.monotonic() - route_started, 3),
        "partitions": [asdict(item) for item in partitions],
    }
    manifest_key = (
        f"{_MANIFEST_NAMESPACE}/routes/provider={storage._slug(route.provider)}/"
        f"canonical={storage._slug(route.base_asset)}/market={storage._slug(route.symbol)}.json"
    )
    storage._put_json(manifest, manifest_key)
    manifest["manifest_object_key"] = manifest_key
    return manifest


def sync_route(
    route: Historical15mRoute,
    *,
    start: datetime,
    end: datetime,
    force: bool = False,
) -> dict[str, object]:
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise ValueError("start/end must be timezone-aware and end must be later than start")
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    if route.provider == "dukascopy":
        return _sync_dukascopy_incremental(route, start=start, end=end, force=force)
    if route.provider == "histdata":
        return _sync_histdata_incremental(route, start=start, end=end, force=force)

    quality = _empty_quality()
    if route.provider == "alpaca_sip":
        fifteen = fetch_alpaca_15m(route, start=start, end=end, quality=quality)
    else:
        raise ValueError(f"unsupported provider: {route.provider}")
    _validate_coverage(route, fifteen, start=start)
    datasets = _datasets_from_fifteen(route, fifteen)

    partitions: list[Partition] = []
    coverage: dict[str, object] = {}
    for timeframe, rows in datasets.items():
        coverage[timeframe] = {
            "rows": len(rows),
            "first_timestamp": rows[0].timestamp.isoformat(),
            "last_timestamp": rows[-1].timestamp.isoformat(),
        }
        for year, year_rows in _year_groups(rows):
            partitions.append(_store_partition(route, timeframe, year, year_rows, force=force))

    manifest: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "status": "COMPLETE",
        "route": _route_identity(route),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "source_kind": _source_kind(route),
        "qualification_scope": "research_backtest_only_live_route_order_unchanged",
        "history_policy": "provider_backed_15m_with_1h_4h_1d_deterministically_derived",
        "session_policy": route.session,
        "adjustment_policy": (
            "alpaca_adjustment_all_feed_sip_regular_trading_hours_only"
            if route.provider == "alpaca_sip"
            else "dukascopy_bid_m1_source_no_forward_fill"
        ),
        "proxy_for": route.proxy_for,
        "listing_limited": route.listing_limited,
        "gap_policy": "preserve_source_market_sessions_no_fill",
        "invalid_source_row_policy": "drop_and_record_never_clamp",
        "quality": quality,
        "source_ohlc_invariant_rows_dropped": quality["ohlc_invariant_rows_dropped"],
        "coverage": coverage,
        "total_rows": sum(len(rows) for rows in datasets.values()),
        "partition_objects_recorded": len(partitions),
        "reused_verified_partition_objects": sum(item.reused_verified for item in partitions),
        "uploaded_or_replaced_partition_objects": sum(
            not item.reused_verified for item in partitions
        ),
        "integrity_policy": "sha256_manifest_compare_upload_verify_downloaded_bytes",
        "partitions": [asdict(item) for item in partitions],
    }
    manifest_key = (
        f"{_MANIFEST_NAMESPACE}/routes/provider={storage._slug(route.provider)}/"
        f"canonical={storage._slug(route.base_asset)}/market={storage._slug(route.symbol)}.json"
    )
    storage._put_json(manifest, manifest_key)
    manifest["manifest_object_key"] = manifest_key
    return manifest


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SystemExit("timestamps must include timezone")
    return parsed.astimezone(timezone.utc)


def main() -> int:
    storage._aws = hf_s3.aws
    parser = argparse.ArgumentParser(
        description="Repair non-crypto 15m backtest history using Alpaca SIP and Dukascopy"
    )
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--base-asset")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    registry = Historical15mRegistry.load()
    if args.discover_only:
        routes = registry.all()
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "route_count": len(routes),
            "routes": [asdict(route) for route in routes],
        }
        output.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        return 0
    if not args.base_asset:
        raise SystemExit("route mode requires --base-asset")
    route = registry.get(args.base_asset)
    if route is None:
        raise SystemExit(f"historical 15m repair route not found: {args.base_asset}")
    start = _parse_datetime(args.start) if args.start else route.start
    end = _parse_datetime(args.end) if args.end else datetime.now(timezone.utc)
    try:
        payload = sync_route(route, start=start, end=end, force=args.force)
    except Exception as exc:
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "status": "ERROR",
            "route": {
                "base_asset": route.base_asset,
                "asset_class": route.asset_class,
                "provider": route.provider,
                "provider_symbol": route.symbol,
                "price_multiplier": str(route.price_multiplier),
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "partitions": [],
        }
        evidence = getattr(exc, "evidence", None)
        if isinstance(evidence, dict):
            payload["resume_evidence"] = evidence
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        raise
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
