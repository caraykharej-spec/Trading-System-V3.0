from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from scripts.backtest import sync_gate_universe_monthly_archive_to_hf as subject


def test_configure_hf_storage_maps_only_endpoint_and_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_S3_ENDPOINT", " https://storage.hf.example ")
    monkeypatch.setenv("HF_S3_BUCKET", " private-bucket ")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "access")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")

    subject._configure_hf_storage()

    assert subject.os.environ["B2_S3_ENDPOINT"] == "https://storage.hf.example"
    assert subject.os.environ["B2_BUCKET_NAME"] == "private-bucket"


def test_configure_hf_storage_fails_closed_when_secret_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "HF_S3_ENDPOINT",
        "HF_S3_BUCKET",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="missing HF storage environment"):
        subject._configure_hf_storage()


def test_put_file_verifies_downloaded_bytes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    source.write_bytes(b"deterministic parquet bytes")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    calls: list[tuple[str, ...]] = []

    def fake_aws(*args: str, **_: object) -> CompletedProcess[str]:
        calls.append(args)
        if args[1] == "get-object":
            Path(args[-1]).write_bytes(source.read_bytes())
        return CompletedProcess(args, 0, "{}", "")

    monkeypatch.setattr(subject.core, "_aws", fake_aws)
    monkeypatch.setattr(subject.core, "_bucket", lambda: "bucket")

    subject._put_file_verified(source, "prefix/object", expected, "application/x-parquet")

    assert [args[1] for args in calls] == ["put-object", "get-object"]
    assert "--metadata" not in calls[0]


def test_head_returns_downloaded_hash_not_custom_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = "a" * 64
    monkeypatch.setattr(
        subject.core,
        "_aws",
        lambda *args, **kwargs: CompletedProcess(args, 0, '{"Metadata": {}}', ""),
    )
    monkeypatch.setattr(subject.core, "_bucket", lambda: "bucket")
    monkeypatch.setattr(subject, "_downloaded_sha256", lambda key: expected)

    assert subject._head_object_state("prefix/object") == (True, expected)


class _FakeResponse:
    status = 200

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def test_spot_listing_start_uses_earliest_positive_gate_start_and_floors_to_5m(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b'{"buy_start": 1737281237, "sell_start": 1737281299}'
    monkeypatch.setattr(
        subject.urllib.request,
        "urlopen",
        lambda request, timeout: _FakeResponse(payload),
    )

    result = subject._spot_listing_start("TRUMP_USDT")

    assert result == datetime.fromtimestamp(1737281100, tz=timezone.utc)


def test_apply_spot_listing_floor_replaces_default_archive_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listing = datetime(2025, 1, 19, 8, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(subject, "_spot_listing_start", lambda symbol: listing)
    argv = [
        "--canonical",
        "TRUMP/USDT",
        "--provider",
        "gateio",
        "--provider-symbol",
        "TRUMP_USDT",
    ]

    result = subject._apply_spot_listing_floor(argv)

    assert result == listing
    assert subject._option_value(argv, "--start") == listing.isoformat()


def test_apply_spot_listing_floor_preserves_later_explicit_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listing = datetime(2025, 1, 19, 8, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(subject, "_spot_listing_start", lambda symbol: listing)
    argv = [
        "--provider",
        "gateio",
        "--provider-symbol",
        "TRUMP_USDT",
        "--start",
        "2025-02-01T00:00:00+00:00",
    ]

    subject._apply_spot_listing_floor(argv)

    assert subject._option_value(argv, "--start") == "2025-02-01T00:00:00+00:00"


def test_apply_spot_listing_floor_does_not_touch_futures_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subject,
        "_spot_listing_start",
        lambda symbol: pytest.fail("spot listing lookup should not run for futures"),
    )
    argv = [
        "--provider",
        "gateio_futures",
        "--provider-symbol",
        "BTC_USDT",
    ]

    assert subject._apply_spot_listing_floor(argv) is None
    assert subject._option_value(argv, "--start") is None
