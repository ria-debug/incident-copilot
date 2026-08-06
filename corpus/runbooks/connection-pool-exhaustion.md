# Runbook: Connection pool exhaustion on credit-api

Applies to `credit-api` and `credit-worker`. Paged as `CreditApiPoolSaturation`.

## Symptoms
Request latency climbs while CPU and memory stay flat. The `pool_wait_seconds`
histogram develops a long tail. Downstream databases look healthy. Clients see
504 gateway timeouts rather than 500s, because requests are queuing for a
connection rather than failing inside the handler.

## Immediate check
Compare `pool_active_connections` against `pool_max_connections`. If active is
pinned at max for more than two minutes while `pool_wait_seconds` p99 exceeds
1.5 seconds, the pool is saturated and this runbook applies.

## Most common cause: a leaked connection
A code path that acquires a connection and returns without releasing it. The
signature is a sawtooth in `pool_active_connections` that never returns to
baseline after traffic subsides. Check deploys in the last 24 hours before
looking anywhere else; this is almost always introduced by a change.

## Second cause: a slow downstream
If the database is answering slowly, connections are held longer and the pool
saturates without any leak. Distinguish the two using `db_query_duration_seconds`.
If query duration rose first and saturation followed, treat the database as the
incident and this as a symptom of it.

## Mitigation
Do not raise `pool_max_connections` as a first response. It shifts the
saturation point to the database, which has a hard connection limit and fails
harder when it reaches it. Roll back the suspect deploy first. If no deploy
correlates, restart the affected pods one at a time to reclaim leaked
connections, keeping at least half the replicas serving throughout.

## Escalation
If saturation returns within thirty minutes of a restart, the leak is not
deploy-related. Escalate to the owning team and treat it as a P2.
