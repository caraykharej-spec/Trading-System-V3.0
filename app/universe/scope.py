"""Project-wide market-universe inclusion policy."""

from __future__ import annotations


# These Storm markets are intentionally outside the trading, historical-data,
# qualification, and backtest universe. Keep this policy centralized so a live
# Storm refresh cannot silently reintroduce them.
EXCLUDED_PROJECT_BASE_ASSETS = frozenset(
    {"BTCDEGEN", "ETHDEGEN", "SOLDEGEN", "XMR"}
)


def is_project_base_asset(base_asset: str) -> bool:
    """Return whether a normalized base asset belongs to the project universe."""

    return base_asset.strip().upper() not in EXCLUDED_PROJECT_BASE_ASSETS
