from __future__ import annotations

from scripts.backtest import merge_yahoo_repair_manifest as subject


def _summary(base: str, symbol: str, status: str, rows: int) -> dict[str, object]:
    return {
        "status": status,
        "route": {
            "base_asset": base,
            "provider_symbol": symbol,
            "price_multiplier": "1",
        },
        "total_rows": rows,
        "partition_objects_recorded": 4 if status == "COMPLETE" else 0,
    }


def test_repair_replaces_exact_failed_route_and_revalidates_full_manifest() -> None:
    base = {
        "expected_routes": 3,
        "route_summaries": [
            _summary("AAPL", "AAPL", "COMPLETE", 100),
            _summary("TON", "TON11419-USD", "ERROR", 0),
            _summary("SPX", "^GSPC", "COMPLETE", 200),
        ],
    }
    repair = _summary("TON", "TON11419-USD", "COMPLETE", 150)

    payload = subject.merge_repair(
        base,
        [repair],
        github_run_id="200",
        github_sha="abc",
        base_run_id="100",
        sync_result="success",
    )

    assert payload["status"] == "PASS_COMPLETE_YAHOO_TRANSFER"
    assert payload["expected_routes"] == 3
    assert payload["completed_routes"] == 3
    assert payload["error_routes"] == 0
    assert payload["missing_route_summaries"] == 0
    assert payload["total_rows"] == 450
    assert payload["repair_base_run_id"] == "100"
    assert payload["repaired_routes"] == [
        {
            "base_asset": "TON",
            "provider_symbol": "TON11419-USD",
            "price_multiplier": "1",
        }
    ]


def test_repair_rejects_route_not_present_in_base_manifest() -> None:
    base = {
        "expected_routes": 1,
        "route_summaries": [_summary("AAPL", "AAPL", "COMPLETE", 100)],
    }
    repair = _summary("TON", "TON11419-USD", "COMPLETE", 150)

    try:
        subject.merge_repair(
            base,
            [repair],
            github_run_id="200",
            github_sha="abc",
            base_run_id="100",
            sync_result="success",
        )
    except ValueError as exc:
        assert "match exactly one base summary" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_repair_does_not_pass_when_repair_sync_failed() -> None:
    base = {
        "expected_routes": 1,
        "route_summaries": [_summary("TON", "TON11419-USD", "ERROR", 0)],
    }
    repair = _summary("TON", "TON11419-USD", "COMPLETE", 150)

    payload = subject.merge_repair(
        base,
        [repair],
        github_run_id="200",
        github_sha="abc",
        base_run_id="100",
        sync_result="failure",
    )

    assert payload["status"] == "FAIL_INCOMPLETE_YAHOO_TRANSFER"
