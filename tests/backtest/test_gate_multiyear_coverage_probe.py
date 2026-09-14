from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "backtest"
    / "probe_gate_multiyear_coverage.py"
)
MODULE_NAME = "probe_gate_multiyear_coverage"
SPEC = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
sys.modules[MODULE_NAME] = probe
SPEC.loader.exec_module(probe)


def test_iter_months_crosses_year_boundary() -> None:
    assert probe.iter_months("202312", "202402") == (
        "202312",
        "202401",
        "202402",
    )


def test_iter_months_rejects_invalid_or_reverse_range() -> None:
    with pytest.raises(ValueError):
        probe.iter_months("202313", "202401")
    with pytest.raises(ValueError):
        probe.iter_months("202402", "202401")


def test_archive_url_uses_official_deals_layout() -> None:
    assert probe.archive_url("BTC_USDT", "202304") == (
        "https://download.gatedata.org/spot/deals/202304/BTC_USDT-202304.csv.gz"
    )


def test_contiguous_ranges_detects_gaps() -> None:
    assert probe.contiguous_ranges(["202301", "202302", "202304", "202305"]) == [
        ["202301", "202302"],
        ["202304", "202305"],
    ]


def test_probe_result_distinguishes_unavailable_from_unknown() -> None:
    missing = probe.ProbeResult("BTC_USDT", "202301", 404, None, None)
    timeout = probe.ProbeResult("BTC_USDT", "202302", 0, None, None, 3)
    throttled = probe.ProbeResult("BTC_USDT", "202303", 429, None, None, 3)
    server_error = probe.ProbeResult("BTC_USDT", "202304", 503, None, None, 3)

    assert missing.unavailable is True
    assert missing.unknown is False
    for result in (timeout, throttled, server_error):
        assert result.unknown is True
        assert result.unavailable is False


def test_build_report_finds_common_longest_contiguous_range() -> None:
    result = probe.ProbeResult
    rows = [
        result("BTC_USDT", "202301", 200, "application/gzip", "1"),
        result("BTC_USDT", "202302", 200, "application/gzip", "1"),
        result("BTC_USDT", "202303", 404, None, None),
        result("ETH_USDT", "202301", 200, "application/gzip", "1"),
        result("ETH_USDT", "202302", 206, "application/gzip", "1"),
        result("ETH_USDT", "202303", 200, "application/gzip", "1"),
    ]

    report = probe.build_report(rows)

    assert report["qualification_complete"] is True
    assert report["unknown_probe_count"] == 0
    assert report["common_available_months"] == ["202301", "202302"]
    assert report["common_longest_contiguous_month_count"] == 2
    assert report["common_longest_contiguous_start"] == "202301"
    assert report["common_longest_contiguous_end"] == "202302"


def test_build_report_preserves_unknown_probe_status() -> None:
    result = probe.ProbeResult
    rows = [
        result("BTC_USDT", "202301", 200, "application/gzip", "1"),
        result("BTC_USDT", "202302", 0, None, None, 3),
        result("ETH_USDT", "202301", 200, "application/gzip", "1"),
        result("ETH_USDT", "202302", 200, "application/gzip", "1"),
    ]

    report = probe.build_report(rows)
    btc = report["markets"]["BTC_USDT"]

    assert report["qualification_complete"] is False
    assert report["unknown_probe_count"] == 1
    assert btc["unknown_months"] == ["202302"]
    assert btc["unavailable_months"] == []
    assert btc["probe_results"][1] == {
        "month": "202302",
        "status": 0,
        "classification": "unknown",
        "attempts": 3,
    }
