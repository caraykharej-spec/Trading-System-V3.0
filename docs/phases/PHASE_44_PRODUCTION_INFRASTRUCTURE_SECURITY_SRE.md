# Phase 44 — Production Infrastructure / Security / SRE

## Objective

Package the existing PAPER/SHADOW API as a hardened, observable single-instance
service and define honest production operating gates. This phase does not enable
live trading, create a venue execution connector, schedule trading cycles, or
claim high availability.

## Delivered boundary

- reproducible two-stage Python 3.11 container;
- numeric non-root identity (`10001:10001`);
- read-only container filesystem, dropped Linux capabilities, no-new-privileges,
  bounded memory/CPU, loopback-only host publication and persistent data volume;
- separate backup volume and explicit production configuration example;
- deploy-time fail-closed preflight for API policy, secret quality, TLS
  acknowledgement, absolute persistent paths, universe presence and backup separation;
- authenticated `/metrics` endpoint with process-local, low-cardinality RED metrics;
- HSTS and Permissions-Policy headers in production;
- liveness/readiness container probes and graceful-stop allowance;
- pull-request container build, non-root assertion and HIGH/CRITICAL Trivy scan.

## Trust boundaries

TLS must terminate at a controlled reverse proxy or ingress. The application is
published only on `127.0.0.1:8000` in the supplied Compose topology. The ingress
must restrict access, set the canonical Host, enforce HTTPS, protect the API key,
and scrape `/metrics` with that key. The application deliberately leaves
`proxy_headers=False`; client IP is not trusted through forwarded headers.

The API key must be injected by a secret manager or protected deployment
environment. `production.env.example` is documentation only. Real `.env` files,
databases and logs remain excluded from git.

## SRE contract

`/healthz` proves process responsiveness. `/readyz` evaluates database, universe,
provider-circuit, runtime and position state. A failed readiness probe removes the
instance from service but must not restart it blindly; liveness is the restart signal.

`/metrics` reports request rate, status class, cumulative latency, in-flight
requests and uptime. It intentionally excludes API keys, request IDs, symbols,
queries, paths and trading evidence. Metrics and rate limiting are process-local,
matching the current one-worker SQLite architecture.

Initial service objectives for an operated PAPER/SHADOW deployment:

| Indicator | Objective | Window |
|---|---:|---:|
| API availability, excluding planned maintenance | 99.5% | 30 days |
| Server-error request ratio | < 0.5% | 30 days |
| Readiness success | >= 99% | 24 hours |
| Restore drill completion | 100% | quarterly |

Alerting policy: page on sustained liveness failure, readiness failure for 10
minutes, or 5xx ratio above 5% for 10 minutes. Ticket on error-budget burn,
backup failure, certificate expiry within 21 days, or disk use above 80%.

## Backup and recovery

The SQLite database and its companion market-data database require application-
consistent backups. An operator must use SQLite's online backup mechanism or stop
the service before copying; copying active files is not an accepted backup.
Backups must be encrypted, stored outside the data volume, retention-tested and
restored in a quarterly drill. A mounted empty backup volume is not proof of backup.

Target objectives are RPO 24 hours and RTO 4 hours for PAPER/SHADOW. Live trading
requires a separate, stricter phase and venue reconciliation before these targets
can be reconsidered.

## Deployment sequence

1. Pin the source revision and immutable image tag.
2. Supply secrets through the deployment environment; never commit them.
3. Mount persistent data and separate backup storage.
4. Run `trading-production-preflight` in the target filesystem context.
5. Build and scan the exact image.
6. Start one instance behind TLS ingress.
7. Verify `/healthz`, `/readyz`, authenticated `/metrics`, logs and dashboard access.
8. Execute and retain a restore drill before calling the service production-ready.
9. Keep `TRADING_API_RUNTIME_CYCLE_ENABLED=0` until separately approved.

## Closure gates

Implementation is complete only after Python CI and Container Security pass on
the feature head and merged `main`. Operational production readiness remains
HOLD until a real target environment demonstrates TLS, secret injection,
persistent storage, automated encrypted backups, restore evidence, monitoring,
alerts and rollback. Phase completion therefore means the repository foundation
is validated—not that a production service is currently hosted.
