from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.backtest.validate_research_dataset_registry import validate


def test_repository_registry_is_valid() -> None:
    raw = validate(Path("config/research/dataset_registry.json"))
    datasets = raw["datasets"]
    assert isinstance(datasets, dict)
    btc = datasets["btc-usdt-one-year-v1"]
    assert isinstance(btc, dict)
    assert btc["symbol"] == "BTC/USDT"
    assert btc["status"] == "ACTIVE_LOCKED"
    assert btc["dataset_bundle_fingerprint"] == (
        "9c8d4d7712ae49adb0625519c18abac08420c020a8bf0271e51dcd128d7cb94f"
    )


def test_registry_rejects_prefix_mismatch(tmp_path: Path) -> None:
    source = Path("config/research/dataset_registry.json")
    raw = json.loads(source.read_text(encoding="utf-8"))
    raw["datasets"]["btc-usdt-one-year-v1"]["object_prefix"] = "gold/wrong"
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="object prefix mismatch"):
        validate(path)


def test_registry_rejects_duplicate_fingerprint(tmp_path: Path) -> None:
    source = Path("config/research/dataset_registry.json")
    raw = json.loads(source.read_text(encoding="utf-8"))
    raw["datasets"]["btc-usdt-copy-v1"] = dict(
        raw["datasets"]["btc-usdt-one-year-v1"]
    )
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate dataset fingerprint"):
        validate(path)
