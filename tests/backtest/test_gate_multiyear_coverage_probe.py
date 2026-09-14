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

    assert report["common_available_months"] == ["202301", "202302"]
    assert report["common_longest_contiguous_month_count"] == 2
    assert report["common_longest_contiguous_start"] == "202301"
    assert report["common_longest_contiguous_end"] == "202302"
