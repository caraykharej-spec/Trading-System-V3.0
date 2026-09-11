# Phase 36.1 — Main Protection & Governance Closure

## Status

**IMPLEMENTED IN REPOSITORY; GITHUB ADMIN ACTIVATION REQUIRED**

Phase 36.1 closes the remaining governance gap from Phase 36. The code repository now contains a machine-readable expected policy, a verification tool, a manual GitHub Actions audit, and a regression test. The GitHub-hosted ruleset itself must still be activated through repository administration because the connected GitHub App does not expose ruleset/branch-protection write operations.

## Required policy

The authoritative expected state is `.github/governance/main-protection-policy.json`.

The active GitHub ruleset must:

- target `main` / the default branch;
- use active enforcement;
- require changes through pull requests;
- require the `CI / quality` check;
- require the branch to be up to date before merge;
- block non-fast-forward updates / force pushes;
- block branch deletion;
- define no normal bypass actors.

The policy intentionally sets the minimum approving-review count to zero because this repository can be maintained by a single owner. The pull-request path is still mandatory. A review-count requirement can be increased later when an independent reviewer is available.

## Repository controls added

### Declarative policy

`.github/governance/main-protection-policy.json`

This file is the repository-side source of truth for the expected GitHub governance state.

### Verification tool

`scripts/governance/verify_main_protection.py`

The verifier queries the GitHub repository ruleset API and fails unless it finds an active ruleset satisfying the policy. It validates the target ref, bypass actors, pull-request rule, strict required status check, force-push protection and deletion protection.

Example:

```bash
python scripts/governance/verify_main_protection.py \
  --repository caraykharej-spec/Trading-System-V3.0
```

`GITHUB_TOKEN` is optional for public reads and may be supplied by GitHub Actions.

### Manual audit workflow

`.github/workflows/governance-audit.yml`

`Governance Audit` is intentionally `workflow_dispatch` only. It does not make `main` red while the administrative setting is still pending. After the GitHub ruleset is activated, run this workflow once and require a PASS before closing Phase 36.1.

### CI protection of governance tooling

The global `CI / quality` workflow now compiles and lints `scripts/`, and the pytest suite contains a regression test for the expected policy contract.

## GitHub UI activation

Repository administrator action:

1. Open **Settings → Rules → Rulesets**.
2. Create a **Branch ruleset** named `main-protection`.
3. Set **Enforcement status = Active**.
4. Target the repository default branch / `main` only.
5. Do not add bypass actors.
6. Enable **Require a pull request before merging**.
7. Enable **Require status checks to pass** and select `CI / quality`.
8. Enable **Require branches to be up to date before merging** / strict status checks.
9. Enable protection against **force pushes / non-fast-forward updates**.
10. Enable protection against **branch deletion**.
11. Save the ruleset.
12. Run **Actions → Governance Audit → Run workflow**.

If the repository UI exposes classic Branch Protection instead of Repository Rulesets, equivalent controls can protect `main`, but the Phase 36.1 verifier is intentionally ruleset-based so the desired state is inspectable through the public repository rules API.

## Acceptance criteria

Phase 36.1 is complete only when all of the following are true:

- the repository ruleset API returns an active ruleset targeting `main`;
- `Governance Audit` passes;
- `CI / quality` is a required strict check;
- a normal change to `main` must use a pull request;
- force pushes are blocked;
- deletion of `main` is blocked;
- no normal bypass actor is configured;
- Issue #10 and the Phase 36.1 tracking issue can be closed with the passing audit evidence.

## Current evidence before activation

At Phase 36.1 start, repository inspection returned no repository rulesets. The latest `main` global CI remained green. This phase does not weaken CI, strategy, risk, or execution controls and does not enable live trading.
