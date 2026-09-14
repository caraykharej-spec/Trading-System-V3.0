# Persistent Historical Research Data Store — Backblaze B2

Status: **RESEARCH / PAPER ONLY**

This document defines the persistent historical-data architecture used by the research and backtesting pipeline. It does not authorize live trading or change strategy/risk thresholds.

## Objectives

The store avoids repeatedly downloading and reconstructing the same historical market data for walk-forward, OOS, Monte Carlo, sensitivity, regime and statistical-qualification workloads.

The design goals are:

- content-addressed research datasets;
- deterministic dataset fingerprints that bind source data, Git revision and writer version;
- fail-closed quality and integrity validation;
- explicit source lineage and Git revision;
- Parquet storage with ZSTD compression;
- SHA-256 verification before and after B2 upload;
- no credentials in source control;
- idempotent exact-byte retries for interrupted publications.

## Storage Roles

The runtime `SQLiteCandleStore` remains a local durable/cache store. Backblaze B2 is a separate bulk research object store and is not a replacement for runtime state.

Logical tiers:

```text
bronze/
  raw-source-evidence/

silver/
  canonical-candles/

gold/
  locked-research-datasets/
```

The first implementation publishes **GOLD locked research datasets** because these datasets have already passed the existing locked-dataset checksum, manifest-fingerprint and candle-quality validation pipeline.

## Canonical GOLD Object Layout

```text
gold/locked-research-datasets/v1/
  <symbol>/
    <dataset_fingerprint>/
      parquet/
        15m.parquet
        1h.parquet
        4h.parquet
        1d.parquet
      checksums.json
      manifest.json
```

`dataset_fingerprint` is SHA-256 over the stable research identity, including source fingerprints, Git revision, Parquet writer identity and the SHA-256 of every Parquet partition. The object prefix is recomputed from that fingerprint during verification and is never trusted from arbitrary manifest input.

## Publication and Retry Semantics

Publishing is fail-closed and uses the following order:

1. verify the existing locked source dataset;
2. build Parquet+ZSTD partitions;
3. verify local Parquet checksums and `checksums.json` consistency;
4. upload/reuse each data object only when its bytes match the expected SHA-256 exactly;
5. download and verify every B2 object;
6. publish `checksums.json` with the same exact-byte retry policy;
7. publish `manifest.json` **last** with the same exact-byte retry policy.

`manifest.json` is the commit marker. A prefix without a valid manifest is incomplete and must not be consumed by research jobs.

Backblaze's documented S3 Put Object headers do not advertise a conditional-create header. The implementation therefore makes retry safety content-addressed: all lineage that can change the manifest is bound into the dataset fingerprint, and an existing key is accepted only after read-back SHA-256 matches the expected bytes. A mismatched object fails closed.

## Path Safety

Parquet paths are not arbitrary manifest paths. For each timeframe, the only permitted relative path is exactly:

```text
parquet/<timeframe>.parquet
```

Absolute paths, `..`, backslashes and paths escaping the bundle root are rejected before publication.

## Credentials and Region

The application never accepts B2 credentials as command-line arguments and never writes them to files.

Expected execution-environment values:

```text
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
B2_S3_ENDPOINT
B2_BUCKET_NAME
B2_S3_REGION          # preferred
```

`AWS_DEFAULT_REGION` may be used instead of `B2_S3_REGION`. The region is passed explicitly to every AWS CLI S3 API invocation for Signature V4 signing.

For GitHub Actions these values are supplied from GitHub Secrets/environment configuration. The B2 connectivity workflow is trusted/manual only (`workflow_dispatch`); pull-request code must not receive storage credentials.

## Build Only

```bash
python scripts/backtest/publish_locked_dataset_to_b2.py \
  --dataset-dir artifacts/locked-dataset \
  --bundle-dir artifacts/research-bundle \
  --git-revision "$GITHUB_SHA" \
  --build-only
```

This performs source verification and creates the Parquet research bundle without accessing B2.

## Publish and Verify

With the required environment values present:

```bash
python scripts/backtest/publish_locked_dataset_to_b2.py \
  --dataset-dir artifacts/locked-dataset \
  --bundle-dir artifacts/research-bundle \
  --git-revision "$GITHUB_SHA"
```

A successful run prints `PUBLISHED_AND_VERIFIED` together with the dataset fingerprint and content-addressed object prefix.

## Data Quality Policy

Missing source candles are not forward-filled, interpolated or silently synthesized. If the existing locked-dataset pipeline reports a gap, the dataset remains rejected until the gap is resolved through a documented authoritative-source repair process.

Example: BTC/USDT March 2021 currently exposes a three-bucket 5-minute gap during reconstruction. That month must not be promoted to GOLD until the source-quality issue is resolved and provenance is recorded.

## Future Extensions

The same object-store contract will be extended to:

- BRONZE raw Gate archive evidence where retention is justified;
- SILVER canonical 15-minute candles and deterministically derived 1h/4h/1d candles;
- monthly incremental ingestion for newly completed months;
- B2-first backtest restore/cache so historical reconstruction is not repeated;
- separate read-only research-consumer credentials from ingestion read/write credentials.
