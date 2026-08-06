# Postmortem: Payments API degradation, 14 March 2026

Severity P2. Customer-visible for 47 minutes. Author: on-call, payments.

## Impact
Payment authorisation p99 latency rose from 240ms to 6.2 seconds. Roughly 4% of
authorisation requests timed out at the client. No payments were lost or
duplicated; the retry path behaved correctly throughout.

## Timeline
14:02 — A routine deploy of `payments-api` completed. No alerts.
14:19 — `ApiLatencyP99High` fired. On-call acknowledged at 14:21.
14:26 — CPU, memory, and database health all checked and found normal. Time was
spent here that the runbook's triage order would have saved.
14:38 — Connection pool saturation identified. `pool_active_connections` had been
pinned at max since 14:04, two minutes after the deploy.
14:44 — The 14:02 deploy was rolled back.
14:49 — Latency recovered to baseline.

## Root cause
The deploy introduced a code path that acquired a database connection to check a
feature flag and returned early without releasing it when the flag was disabled.
The flag was disabled in production and enabled in staging, which is why the leak
never appeared before release.

## What went wrong beyond the bug
The connection pool was checked fourth, after CPU, memory, and database health,
despite the deploy correlation being visible from the first minute. The
degradation was a textbook match for the pool-exhaustion runbook and it was not
opened, because the alert that fired was the generic latency alert and it does
not link to it.

## Corrective actions
Link `ApiLatencyP99High` directly to the pool exhaustion runbook. Add a pool
saturation panel to the payments dashboard. Require that feature flags be
evaluated identically in staging and production before release.
