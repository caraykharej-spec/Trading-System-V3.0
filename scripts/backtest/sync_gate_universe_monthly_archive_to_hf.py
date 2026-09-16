from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.data.providers.http import ProviderError  # noqa: E402
from scripts.backtest import sync_gate_universe_history_to_b2 as core  # noqa: E402
from scripts.backtest import sync_gate_universe_monthly_archive_to_b2 as monthly  # noqa: E402


_GATE_SPOT_PAIR_URL = "https://api.gateio.ws/api/v4/spot/currency_pairs/{market}"


def _configure_hf_storage() -> None:
    required = (
        "HF_S3_ENDPOINT",
        "HF_S3_BUCKET",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    )
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError("missing HF storage environment: " + ", ".join(missing))
    # The mature Gate writer accepts an S3-compatible endpoint through these
    # legacy variable names. Credentials remain in the standard AWS variables.
    os.environ["B2_S3_ENDPOINT"] = os.environ["HF_S3_ENDPOINT"].strip()
    os.environ["B2_BUCKET_NAME"] = os.environ["HF_S3_BUCKET"].strip()


def _downloaded_sha256(key: str) -> str:
    with tempfile.TemporaryDirectory(prefix="gate-hf-verify-") as temp_dir:
        target = Path(temp_dir) / "object"
        core._aws(
            "s3api",
            "get-object",
            "--bucket",
            core._bucket(),
            "--key",
            key,
            str(target),
        )
        return core._sha256(target)


def _head_object_state(key: str) -> tuple[bool, str | None]:
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
    if result.returncode != 0:
        raise RuntimeError(f"HF head-object failed for {key}")
    return True, _downloaded_sha256(key)


def _put_file_verified(path: Path, key: str, sha256: str, content_type: str) -> None:
    core._aws(
        "s3api",
        "put-object",
        "--bucket",
        core._bucket(),
        "--key",
        key,
        "--body",
        str(path),
        "--content-type",
        content_type,
    )
    if _downloaded_sha256(key) != sha256:
        raise RuntimeError(f"HF SHA-256 read-back verification failed for {key}")


def _floor_to_5m(value: datetime) -> datetime:
    value = value.astimezone(timezone.utc)
    discard = timedelta(
        minutes=value.minute % 5,
        seconds=value.second,
        microseconds=value.microsecond,
    )
    return value - discard


def _spot_listing_start(provider_symbol: str, timeout_seconds: int = 20) -> datetime | None:
    market = provider_symbol.replace("/", "_").strip().upper()
    if not market:
        raise ProviderError("Gate spot provider symbol is empty")
    url = _GATE_SPOT_PAIR_URL.format(market=urllib.parse.quote(market, safe="_"))
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Trading-System-V3 gate-history-hf/2.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            if getattr(response, "status", 200) != 200:
                raise ProviderError(f"Gate spot pair metadata HTTP {response.status}: {url}")
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ProviderError(f"Gate spot pair metadata HTTP {exc.code}: {url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError(f"Gate spot pair metadata request failed: {url}") from exc

    if not isinstance(payload, dict):
        raise ProviderError(f"Gate spot pair metadata response is not an object: {market}")

    starts: list[int] = []
    for field in ("buy_start", "sell_start"):
        raw = payload.get(field)
        if raw in (None, "", 0, "0"):
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ProviderError(f"Gate spot pair metadata has invalid {field}: {market}") from exc
        if value > 0:
            starts.append(value)

    if not starts:
        return None
    return _floor_to_5m(datetime.fromtimestamp(min(starts), tz=timezone.utc))


def _option_value(argv: list[str], option: str) -> str | None:
    prefix = option + "="
    for index, item in enumerate(argv):
        if item.startswith(prefix):
            return item[len(prefix) :]
        if item == option and index + 1 < len(argv):
            return argv[index + 1]
    return None


def _set_option(argv: list[str], option: str, value: str) -> None:
    prefix = option + "="
    for index, item in enumerate(argv):
        if item.startswith(prefix):
            argv[index] = prefix + value
            return
        if item == option and index + 1 < len(argv):
            argv[index + 1] = value
            return
    argv.extend([option, value])


def _apply_spot_listing_floor(argv: list[str]) -> datetime | None:
    if "--discover-only" in argv:
        return None
    provider = (_option_value(argv, "--provider") or "").strip().lower()
    if provider != "gateio":
        return None
    provider_symbol = _option_value(argv, "--provider-symbol")
    if not provider_symbol:
        return None

    listing_start = _spot_listing_start(provider_symbol)
    if listing_start is None:
        return None

    requested_start_raw = _option_value(argv, "--start")
    requested_start = core._parse_datetime(requested_start_raw, core._ARCHIVE_START)
    effective_start = max(requested_start, core._ARCHIVE_START, listing_start)
    _set_option(argv, "--start", effective_start.isoformat())
    return listing_start


def main() -> int:
    _configure_hf_storage()
    _apply_spot_listing_floor(sys.argv[1:])
    monthly._head_object_state = _head_object_state
    core._put_file = _put_file_verified
    return monthly.main()


if __name__ == "__main__":
    raise SystemExit(main())
