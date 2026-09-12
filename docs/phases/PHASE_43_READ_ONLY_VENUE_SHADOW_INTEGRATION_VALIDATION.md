# Phase 43 — Read-only Venue + Shadow Integration Validation

## Entry gate: Phase 42 closed within its stated scope

Phase 42 dashboard and native Android client were merged at
`774c0e9186659439e6267dff93a15199094bb519`.

- Main Python CI: https://github.com/caraykharej-spec/Trading-System-V3.0/actions/runs/34671448240
  — 378 tests passed; 79.62% branch-aware coverage; strict mypy clean in 301 files.
- Main Android CI: https://github.com/caraykharej-spec/Trading-System-V3.0/actions/runs/34671448256
  — unit tests and debug APK assembly passed; debug artifact uploaded.
- Signed release distribution, device qualification, background scheduling and push
  transport were explicitly deferred by Phase 42, not missing entry criteria.

## Purpose and scope

Validate public venue data flowing through the existing deterministic
Strategy → Context → Risk → Portfolio pipeline in an isolated shadow experiment.
There is no execution connector, order queue, runtime cycle, database, wallet,
authenticated venue account, or execution method in this composition.

The runner reads public GET endpoints using the existing mapped providers:

- Storm only for current price, with a required source timestamp;
- Gate.io primary and Yahoo fallback for OHLCV;
- canonical symbols from the existing universe configuration;
- 260 closed candles for each of 1d, 4h, 1h and 15m.

Storm source freshness cannot be established using HTTP retrieval time. This
runner deliberately requires a source timestamp instead of the general adapter's
retrieval-time fallback. It also checks freshness again after the full capture.
Unknown mappings, insufficient history, invalid identity/OHLCV, stale or future
observations, and provider outages prevent a PASS. Active candles are excluded.
Yahoo session gaps remain explicitly labelled warnings under the existing policy.

## Shadow experiment

The runner captures each series once, hashes the canonical data and invokes the
existing pipeline twice using those same closed candles. It compares complete
serialized gate results, including rejections and qualified candidates.
A fresh synthetic 10,000-unit account with no positions and leverage 1 is used
for each risk evaluation. Existing risk and portfolio policies are unchanged.

Context uses the deterministic empty-news/empty-events baseline at a fixed time.
The report explicitly labels this limitation: live context feeds are not validated.
The Storm quote is validated as a separate source check; it does not replace
candle-derived strategy levels, simulate fills, or prove venue execution parity.
A technical PASS with zero qualified opportunities is valid; no trade is forced.

## Status semantics

| Status | Meaning | CLI exit |
|---|---|---|
| PASS | All requested data checks and same-capture replay passed | 0 |
| HOLD | External evidence missing, unsupported, stale or invalid | 2 |
| FAIL | Pipeline failed or deterministic replay differed | 1 |

PASS applies only to the listed symbols and observation window. It never grants
live activation or proves profitability, account reconciliation, long-duration
shadow performance, all-universe coverage or production release readiness.
Reports include source/fallback provenance, quality warnings, observation time,
data and decision fingerprints, full gate results, scope and execution-disabled flag.
Fingerprints identify captures; the report is not a historical candle archive.

## Run

From the repository root after `python -m pip install -e '.[dev]'`:

```bash
python -m pytest -q tests/shadow_validation
python -m scripts.validation.read_only_shadow \
  --symbols BTC/USDT \
  --output evidence/phase43.json
```

Requests are bounded to 1–10 unique symbols; the default is BTC/USDT. The command
writes only the requested evidence file and never opens the trading database.
Use distinct output paths to retain consecutive observations.

The `Read-only Venue Shadow Validation` workflow runs public capture on the
Phase 43 feature branch and supports manual dispatch after merge. It has read-only
repository permissions, no secrets, a five-minute deadline and always attempts
to upload `phase43-read-only-shadow-evidence`. External HOLD is intentionally not
greenwashed into success. The global Python CI remains a separate offline gate.

## Validation and closure

Offline tests cover capture/replay, closed candle filtering, source policy,
fallback provenance, missing timestamps, stale/future/mixed-symbol inputs,
bounded requests, qualified signals, retained risk rejections and replay drift.

Implementation is not operational closure by itself. Closure requires:

1. global Python CI on the feature/PR head;
2. inspectable public capture evidence (PASS, or explicitly retained HOLD);
3. reviewed merge and successful main CI;
4. an honest final status: public HOLD leaves the external validation gate open.

Signed Android release and real order execution remain outside this phase.

## Initial implementation evidence

Local full-suite validation: 392 tests passed; coverage 79.98%; Ruff clean;
strict mypy clean in 304 source files (Python 3.12 environment).

`docs/validation_evidence/phase43_btc_public_capture.json` records the initial
public BTC/USDT capture: timestamped Storm price plus 260 closed Gate.io candles
per timeframe, all data checks PASS and deterministic replay PASS. Strategy
returned NO_TRADE due to unaligned higher-timeframe direction. The observation
is historical evidence only; it is not a current signal or all-market validation.
GitHub CI on the committed head remains the authoritative Python 3.11 gate.
