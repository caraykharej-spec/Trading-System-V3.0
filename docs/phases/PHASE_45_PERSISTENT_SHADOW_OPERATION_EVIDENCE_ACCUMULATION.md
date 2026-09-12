# Phase 45 — Persistent Shadow Operation & Evidence Accumulation

## Objective

Turn the bounded Phase 43 validation into a durable, periodic observation process.
The worker accumulates inspectable PASS/HOLD/FAIL evidence while preserving the
same public-data and deterministic Strategy → Context → Risk → Portfolio boundary.
It has no execution connector, wallet, order queue, live account or trading database.

## Architecture

```text
systemd worker (default 30-minute delay)
        ↓
exclusive expiring SQLite lease
        ↓
Phase 43 read-only capture and deterministic replay
        ↓
append-only evidence transaction
        ↓
report digest + previous hash → new chain hash
        ↓
summary / integrity verification / encrypted backup
```

The worker runs a new interval after the prior observation finishes. This avoids
overlap and provider bursts; it is a fixed-delay schedule, not wall-clock cron.
The default lease is two intervals so a normal next invocation cannot overlap a
slow capture. A crashed worker's lease expires rather than blocking forever.

## Evidence contract

Every observation persists:

- unique run ID and monotonically increasing sequence;
- UTC observation and persistence timestamps;
- requested canonical symbols;
- complete Phase 43 report and PASS/HOLD/FAIL status;
- report digest, previous chain hash and current chain hash.

Writes use `BEGIN IMMEDIATE`, `synchronous=FULL`, busy timeout and WAL where
supported. A duplicate run ID rolls back. The integrity command recomputes every
report digest and link from `GENESIS`; any edit, removal or reorder fails the chain.
The chain is tamper-evident, not a digital signature or protection against an
attacker who can replace the entire database and its backups.

Provider failures and stale/unsupported evidence are stored as HOLD and do not
stop later observations. Unexpected exceptions are stored as sanitized FAIL with
the exception class only; exception text, secrets and credentials are excluded.
No-trade decisions are valid evidence and are never converted into signals.

## Commands

Configuration is supplied through environment variables documented in
`deploy/shadow.env.example`.

```bash
trading-shadow-operation once
trading-shadow-operation worker
trading-shadow-operation summary
trading-shadow-operation verify
```

The default database is `data/shadow_evidence.sqlite3`, the default universe is
`config/universe.json`, and the default bounded symbol set is `BTC/USDT`.
Production must use an absolute persistent path owned only by the shadow service.

The supplied `deploy/shadow-worker.service` runs under a dedicated unprivileged
account with a strict filesystem boundary. Install the application in
`/opt/trading-system`, place configuration in `/etc/trading-system/shadow.env`,
grant write access only to `/var/lib/trading-system-shadow`, then enable the unit.

## Longitudinal readout

`summary` reports total PASS/HOLD/FAIL observations, total qualified candidates,
first/last observation and chain validity. These are operational evidence counts,
not profitability metrics. Signal outcome tracking, simulated fills, slippage,
forward returns and statistical promotion criteria require a later phase with an
explicit outcome model.

## Backup and retention

The evidence database and WAL are runtime data and must never be committed.
Use SQLite online backup or stop the worker before copying. Encrypt and export
backups to a separate failure domain. Verify the chain after every restore.
No automatic deletion is implemented: retention and archival require an approved
policy that preserves chain continuity and independently signed checkpoints.

## Operational gates

Repository implementation is complete when feature and merged-main CI pass.
Persistent-shadow operational validation remains HOLD until a real host proves:

1. at least seven consecutive days of scheduled observations;
2. no overlapping captures and no unexplained sequence gaps;
3. retained PASS/HOLD/FAIL reports and a valid hash chain;
4. monitoring for worker absence, FAIL rate, HOLD rate, disk and backup health;
5. encrypted backup plus successful restore and post-restore chain verification;
6. reviewed symbol scope and provider-rate impact.

Seven days is an initial infrastructure soak, not strategy qualification. Live
execution remains disabled regardless of accumulated evidence.
