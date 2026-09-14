# Persistent Historical Research Data Store — Backblaze B2

Status: **RESEARCH / PAPER ONLY**

This document defines the persistent historical-data architecture used by the research and backtesting pipeline. It does not authorize live trading or change strategy/risk thresholds.

## Objectives

The store exists to avoid repeatedly downloading and reconstructing the same historical market data for walk-forward, OOS, Monte Carlo, sensitivity, regime and statistical-qualification workloads.

The design goals are:

- immutable, content-addressed research datasets;
- deterministic dataset fingerprints;
- fail-closed quality and integrity validation;
- explicit source lineage and Git revision;
- Parquet storage with ZSTD compression;
- SHA-256 verification before and after B2 upload;
- no credentials in source control;
- no overwrite of published research objects.

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

`dataset_fingerprint` is SHA-256 over the stable research identity, including source dataset fingerprints and the SHA-256 of every Parquet partition. Published paths are therefore content-addressed.

## Commit Protocol

Publishing is fail-closed and uses the following order:

1. verify the existing locked source dataset;
2. build Parquet+ZSTD partitions;
3. verify local Parquet checksums;
4. upload Parquet objects without overwrite;
5. download each uploaded object and verify SHA-256;
6. upload `checksums.json` and verify it;
7. upload `manifest.json` **last** and verify it.

`manifest.json` is the commit marker. A prefix without a valid manifest is incomplete and must not be consumed by research jobs.

## Credentials

The application never accepts B2 credentials as command-line arguments and never writes them to files.

Expected execution-environment variables:

```text
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
B2_S3_ENDPOINT
B2_BUCKET_NAME
```

For GitHub Actions these values are supplied from GitHub Secrets. The B2 workflow is trusted/manual only (`workflow_dispatch`); pull-request code must not receive storage credentials.

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

With the four required environment variables present:

```bash
python scripts/backtest/publish_locked_dataset_to_b2.py \
  --dataset-dir artifacts/locked-dataset \
  --bundle-dir artifacts/research-bundle \
  --git-revision "$GITHUB_SHA"
```

A successful run prints `PUBLISHED_AND_VERIFIED` together with the dataset fingerprint and immutable object prefix.

## Data Quality Policy

Missing source candles are not forward-filled, interpolated or silently synthesized. If the existing locked-dataset pipeline reports a gap, the dataset remains rejected until the gap is resolved through a documented authoritative-source repair process.

Example: the BTC/USDT March 2021 archive currently exposes a three-bucket 5-minute gap during reconstruction. That month must not be promoted to GOLD until the source-quality issue is resolved and provenance is recorded.

## Future Extensions

The same object-store contract will be extended to:

- BRONZE raw Gate archive evidence where retention is justified;
- SILVER canonical 15-minute candles and deterministically derived 1h/4h/1d candles;
- monthly incremental ingestion for newly completed months;
- B2-first backtest restore/cache so historical reconstruction is not repeated;
- separate read-only CI credentials from ingestion read/write credentials.
