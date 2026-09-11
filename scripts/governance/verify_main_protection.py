from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API_ROOT = "https://api.github.com"
DEFAULT_POLICY = Path(".github/governance/main-protection-policy.json")


def _request_json(url: str, token: str | None) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "trading-system-governance-audit",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API returned HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub API request failed: {exc.reason}") from exc


def _targets_main(detail: dict[str, Any], protected_refs: set[str]) -> bool:
    conditions = detail.get("conditions") or {}
    ref_name = conditions.get("ref_name") or {}
    include = set(ref_name.get("include") or [])
    exclude = set(ref_name.get("exclude") or [])
    if include.isdisjoint(protected_refs):
        return False
    return "refs/heads/main" not in exclude and "~DEFAULT_BRANCH" not in exclude


def _rule_map(detail: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for rule in detail.get("rules") or []:
        if isinstance(rule, dict) and isinstance(rule.get("type"), str):
            result[rule["type"]] = rule
    return result


def _status_contexts(rule: dict[str, Any]) -> set[str]:
    parameters = rule.get("parameters") or {}
    checks = parameters.get("required_status_checks") or []
    contexts: set[str] = set()
    for check in checks:
        if isinstance(check, dict) and isinstance(check.get("context"), str):
            contexts.add(check["context"])
    return contexts


def _validate_ruleset(detail: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if detail.get("target") != policy["target"]:
        failures.append("ruleset target is not branch")
    if detail.get("enforcement") != policy["enforcement"]:
        failures.append("ruleset enforcement is not active")

    protected_refs = set(policy["protected_refs"])
    if not _targets_main(detail, protected_refs):
        failures.append("ruleset does not target main/default branch")

    if detail.get("bypass_actors"):
        failures.append("ruleset defines bypass actors")

    rules = _rule_map(detail)
    policy_rules = policy["rules"]

    if policy_rules["pull_request"]["required"] and "pull_request" not in rules:
        failures.append("pull_request rule is missing")

    if policy_rules["non_fast_forward"]["required"] and "non_fast_forward" not in rules:
        failures.append("non_fast_forward rule is missing")

    if policy_rules["deletion"]["required"] and "deletion" not in rules:
        failures.append("deletion rule is missing")

    required_checks = policy_rules["required_status_checks"]
    status_rule = rules.get("required_status_checks")
    if required_checks["required"]:
        if status_rule is None:
            failures.append("required_status_checks rule is missing")
        else:
            parameters = status_rule.get("parameters") or {}
            if required_checks["strict_required_status_checks_policy"] and not parameters.get(
                "strict_required_status_checks_policy"
            ):
                failures.append("required status checks are not strict/up-to-date")
            expected_contexts = set(required_checks["contexts"])
            actual_contexts = _status_contexts(status_rule)
            missing_contexts = sorted(expected_contexts - actual_contexts)
            if missing_contexts:
                failures.append(
                    "required status checks missing contexts: " + ", ".join(missing_contexts)
                )

    return failures


def verify(repository: str, policy_path: Path, token: str | None) -> tuple[bool, list[str]]:
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    rulesets = _request_json(f"{API_ROOT}/repos/{repository}/rulesets", token)
    if not isinstance(rulesets, list) or not rulesets:
        return False, ["repository has no rulesets"]

    candidate_failures: list[str] = []
    for summary in rulesets:
        if not isinstance(summary, dict) or "id" not in summary:
            continue
        detail = _request_json(f"{API_ROOT}/repos/{repository}/rulesets/{summary['id']}", token)
        if not isinstance(detail, dict):
            continue
        failures = _validate_ruleset(detail, policy)
        if not failures:
            return True, [f"validated active ruleset: {detail.get('name', summary['id'])}"]
        candidate_failures.extend(failures)

    if not candidate_failures:
        candidate_failures.append("no readable ruleset matched the governance policy")
    return False, sorted(set(candidate_failures))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Phase 36.1 main-branch governance")
    parser.add_argument("--repository", required=True, help="owner/repository")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args()

    ok, messages = verify(args.repository, args.policy, os.getenv("GITHUB_TOKEN"))
    for message in messages:
        print(("PASS: " if ok else "FAIL: ") + message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
