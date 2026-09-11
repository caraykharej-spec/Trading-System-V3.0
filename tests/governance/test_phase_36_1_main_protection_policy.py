from __future__ import annotations

import json
from pathlib import Path


POLICY_PATH = Path(".github/governance/main-protection-policy.json")


def test_main_protection_policy_is_fail_closed() -> None:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    assert policy["target"] == "branch"
    assert policy["enforcement"] == "active"
    assert "refs/heads/main" in policy["protected_refs"]
    assert policy["bypass_actors"] == []

    rules = policy["rules"]
    assert rules["pull_request"]["required"] is True
    assert rules["required_status_checks"]["required"] is True
    assert rules["required_status_checks"]["strict_required_status_checks_policy"] is True
    assert rules["required_status_checks"]["contexts"] == ["CI / quality"]
    assert rules["non_fast_forward"]["required"] is True
    assert rules["deletion"]["required"] is True
