from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.data.market_data import Candle
from app.data.providers.http import ProviderError
from scripts.backtest import hf_s3
from scripts.backtest import sync_gate_universe_history_to_b2 as core
from scripts.backtest import sync_gate_universe_monthly_archive_to_b2 as monthly
from scripts.backtest import sync_gate_universe_monthly_archive_to_hf as hf_gate

_DEFAULT_CONFIG = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "market_data"
    / "historical_symbol_continuity.json"
)
_NATIVE_FETCH_MONTH_5M = monthly.fetch_month_5m


@dataclass(frozen=True)
class ContinuitySegment:
    source_provider_symbol: str
    start: datetime
    end: datetime | None


@dataclass(frozen=True)
class ContinuityRule:
    base_asset: str
    provider: str
    target_provider_symbol: str
    canonical_symbol: str
    asset_class: str
    price_multiplier: str
    reason: str
    identity_evidence: str
    segments: tuple[ContinuitySegment, ...]


def _parse_timestamp(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("continuity timestamps must include timezone")
    return parsed.astimezone(timezone.utc)


def load_rule(base_asset: str, path: Path = _DEFAULT_CONFIG) -> ContinuityRule:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_assets = payload.get("assets") or {}
    base = base_asset.strip().upper()
    raw = raw_assets.get(base)
    if not isinstance(raw, dict):
        raise ValueError(f"no historical symbol continuity rule for {base}")

    raw_segments = raw.get("segments") or []
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError(f"historical symbol continuity segments are empty for {base}")

    segments: list[ContinuitySegment] = []
    for item in raw_segments:
        if not isinstance(item, dict):
            raise ValueError(f"invalid historical symbol continuity segment for {base}")
        source = str(item.get("source_provider_symbol") or "").strip().upper()
        if not source:
            raise ValueError(f"continuity source symbol is empty for {base}")
        start = _parse_timestamp(item.get("start"))
        raw_end = item.get("end")
        end = None if raw_end in (None, "") else _parse_timestamp(raw_end)
        if end is not None and end <= start:
            raise ValueError(f"continuity segment end must be after start for {base}")
        segments.append(ContinuitySegment(source, start, end))

    segments.sort(key=lambda item: item.start)
    for previous, current in zip(segments, segments[1:]):
        if previous.end is None:
            raise ValueError(f"open-ended continuity segment must be last for {base}")
        if previous.end != current.start:
            raise ValueError(
                f"continuity segments must be exactly adjacent for {base}: "
                f"{previous.end.isoformat()} != {current.start.isoformat()}"
            )

    provider = str(raw.get("provider") or "").strip().lower()
    if provider != "gateio":
        raise ValueError(f"unsupported continuity provider for {base}: {provider}")

    return ContinuityRule(
        base_asset=base,
        provider=provider,
        target_provider_symbol=str(raw.get("target_provider_symbol") or "").strip().upper(),
        canonical_symbol=str(raw.get("canonical_symbol") or f"{base}/USDT").strip().upper(),
        asset_class=str(raw.get("asset_class") or "crypto").strip().lower(),
        price_multiplier=str(raw.get("price_multiplier") or "1"),
        reason=str(raw.get("reason") or "").strip(),
        identity_evidence=str(raw.get("identity_evidence") or "").strip(),
        segments=tuple(segments),
    )


def _segment_overlap(
    segment: ContinuitySegment,
    start: datetime,
    end: datetime,
) -> tuple[datetime, datetime] | None:
    overlap_start = max(start, segment.start)
    overlap_end = min(end, segment.end or end)
    if overlap_start >= overlap_end:
        return None
    return overlap_start, overlap_end


def fetch_continuity_month_5m(
    target_route: core.GateHistoryRoute,
    start: datetime,
    end: datetime,
    segments: tuple[ContinuitySegment, ...],
) -> tuple[list[Candle], int, int, int, int, int]:
    rows_by_timestamp: dict[datetime, Candle] = {}
    totals = [0, 0, 0, 0, 0]

    for segment in segments:
        overlap = _segment_overlap(segment, start, end)
        if overlap is None:
            continue
        segment_start, segment_end = overlap
        source_route = replace(
            target_route,
            provider_symbol=segment.source_provider_symbol,
            route_origin="historical_symbol_continuity_source",
        )
        (
            rows,
            archive_days_found,
            archive_days_missing,
            rest_fallback_days,
            monthly_archive_objects_found,
            daily_archive_objects_found,
        ) = _NATIVE_FETCH_MONTH_5M(source_route, segment_start, segment_end)
        for candle in rows:
            normalized = Candle(
                symbol=target_route.canonical_symbol,
                timeframe="5m",
                timestamp=candle.timestamp,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
            )
            existing = rows_by_timestamp.get(normalized.timestamp)
            if existing is not None and existing != normalized:
                raise ProviderError(
                    "conflicting candles across historical symbol continuity boundary: "
                    + normalized.timestamp.isoformat()
                )
            rows_by_timestamp[normalized.timestamp] = normalized
        totals[0] += archive_days_found
        totals[1] += archive_days_missing
        totals[2] += rest_fallback_days
        totals[3] += monthly_archive_objects_found
        totals[4] += daily_archive_objects_found

    return (
        [rows_by_timestamp[key] for key in sorted(rows_by_timestamp)],
        totals[0],
        totals[1],
        totals[2],
        totals[3],
        totals[4],
    )


def _configure_hf() -> None:
    hf_gate._configure_hf_storage()
    core._aws = hf_s3.aws
    monthly._head_object_state = hf_gate._head_object_state
    core._put_file = hf_gate._put_file_verified


def sync_rule(
    rule: ContinuityRule,
    *,
    end: datetime,
    force: bool = False,
) -> dict[str, Any]:
    _configure_hf()
    target_route = core.GateHistoryRoute(
        canonical_symbol=rule.canonical_symbol,
        base_asset=rule.base_asset,
        asset_class=rule.asset_class,
        provider=rule.provider,
        provider_symbol=rule.target_provider_symbol,
        price_multiplier=rule.price_multiplier,
        route_origin="source_registry_historical_symbol_continuity",
    )
    start = max(core._ARCHIVE_START, rule.segments[0].start)
    if end <= start:
        raise ValueError("continuity sync end must be after continuity start")

    original_fetch = monthly.fetch_month_5m
    try:
        monthly.fetch_month_5m = lambda route, month_start, month_end: fetch_continuity_month_5m(
            route, month_start, month_end, rule.segments
        )
        manifest = monthly.sync_route(target_route, start=start, end=end, force=force)
    finally:
        monthly.fetch_month_5m = original_fetch

    manifest["schema_version"] = max(int(manifest.get("schema_version") or 0), 3)
    manifest["historical_symbol_continuity"] = {
        "reason": rule.reason,
        "identity_evidence": rule.identity_evidence,
        "target_provider_symbol": rule.target_provider_symbol,
        "segments": [
            {
                "source_provider_symbol": segment.source_provider_symbol,
                "start": segment.start.isoformat(),
                "end": segment.end.isoformat() if segment.end is not None else None,
            }
            for segment in rule.segments
        ],
        "stitch_policy": "exact_timestamp_union_fail_on_conflict_no_synthetic_rows",
    }
    manifest["route"]["route_origin"] = "source_registry_historical_symbol_continuity"
    core._put_json(manifest, core._route_manifest_key(target_route))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync reviewed Gate ticker-renaming history as one continuous HF dataset"
    )
    parser.add_argument("--base-asset", required=True)
    parser.add_argument("--end")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    rule = load_rule(args.base_asset)
    end = (
        _parse_timestamp(args.end)
        if args.end
        else core._utc_day_floor(datetime.now(timezone.utc))
    )
    payload = sync_rule(rule, end=end, force=args.force)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "base_asset": rule.base_asset,
                "target_provider_symbol": rule.target_provider_symbol,
                "observed_first": payload.get("observed_first"),
                "observed_last": payload.get("observed_last"),
                "total_5m_rows": payload.get("total_5m_rows"),
                "partition_objects_recorded": payload.get("partition_objects_recorded"),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
