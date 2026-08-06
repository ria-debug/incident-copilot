"""Writes the synthetic corpus. Rerunnable; overwrites the markdown files.

The corpus is synthetic. It is modelled on the shape of real banking-API
operational documentation — runbooks that assume context, postmortems that
bury the actual cause three paragraphs in, reference pages nobody reads until
they need one line of it — but contains no real system, threshold, or incident.

That shape is the point. A corpus of clean, self-contained, keyword-rich
paragraphs makes any retriever look good and teaches you nothing. These
documents deliberately include the properties that break retrieval in practice:
procedures whose body never repeats their own topic, symptoms described in the
words a user would use rather than the words the title uses, and two documents
that partially contradict each other.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "corpus"

DOCS: dict[str, str] = {}

DOCS["runbooks/connection-pool-exhaustion.md"] = """\
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
"""

DOCS["runbooks/tls-certificate-expiry.md"] = """\
# Runbook: TLS certificate expiry and handshake failures

Applies to any service behind the internal gateway. Paged as `TlsHandshakeFailureRate`.

## Symptoms
Clients report connection failures rather than HTTP errors. The connection is
rejected before a request is made, so nothing appears in application logs at
all. Gateway logs show `certificate has expired` or `bad certificate domain`.
Traffic drops to zero abruptly rather than degrading gradually.

## Immediate check
Run a handshake against the affected endpoint and read the validity dates. A
certificate that expired within the last hour, combined with a clean drop to
zero traffic, is conclusive. Stop investigating and go straight to mitigation.

## Why monitoring misses this
Expiry alerting fires at thirty days and seven days. Both are email-only and
neither pages anyone. Certificates renewed manually during a change freeze are
the recurring gap: renewal is deferred, the reminder is acknowledged and closed,
and no page ever fires. See the 2026-06-21 postmortem for the full sequence.

## Mitigation
Renew and deploy the certificate. There is no safe partial mitigation. Disabling
verification to restore traffic converts an outage into a security incident and
is not authorised at any severity, including P1.

## Prevention
Expiry within seven days should page rather than email. Any manual renewal
during a change freeze needs a named owner and a follow-up dated before the
freeze ends.
"""

DOCS["runbooks/api-latency-degradation.md"] = """\
# Runbook: General API latency degradation

Applies to all public API services. Paged as `ApiLatencyP99High`.

## Symptoms
The p99 latency of a service exceeds its SLO for five consecutive minutes.
Median latency is frequently unaffected, which is exactly why this is invisible
on a dashboard showing averages.

## Triage order
Work outside in — the cheapest checks eliminate the most causes.

First, establish whether the degradation is global or per-endpoint. A single
endpoint degrading points at one query or one downstream. Every endpoint
degrading points at a shared resource: the connection pool, the host, or the
network.

Second, correlate against deploy time. Most latency regressions are introduced
by a change, and rolling back is faster than diagnosing.

Third, check saturation of the four shared resources, in this order: connection
pool, CPU throttling, memory pressure, disk I/O wait.

## Resource saturation signatures
CPU throttling appears as `container_cpu_cfs_throttled_seconds` rising while
utilisation sits below the limit — the container is being throttled at its
quota, not running out of headroom. Memory pressure appears as increased garbage
collection pause time well before it appears as an out-of-memory kill. Disk I/O
wait is usually a noisy neighbour on the node rather than the service's own work.

## When to stop and escalate
If latency is degraded across several unrelated services at once, this is not an
application incident. Stop and escalate to the platform team — the cause is
shared infrastructure and application-level triage will waste the window.
"""

DOCS["runbooks/kafka-consumer-lag.md"] = """\
# Runbook: Consumer lag and backlog growth

Applies to `settlement-consumer` and `audit-consumer`. Paged as `ConsumerGroupLagHigh`.

## Symptoms
Consumer group lag grows monotonically. Downstream data is stale rather than
missing, so the first report often comes from a business team noticing that
yesterday's figures have not moved, rather than from monitoring.

## Immediate check
Read lag per partition, never just the total. Even lag across all partitions
means the consumer is simply too slow for current throughput. Lag concentrated
on one or two partitions means a poison message or a hot key, which needs a
completely different fix.

## Cause: a poison message
A message that throws on deserialization, is retried, and blocks its partition
indefinitely. The signature is one partition's lag growing while the rest stay
flat, plus a repeating exception in the consumer log at the same offset.
Skipping the offset requires sign-off from the data owner, because the message
is dropped rather than reprocessed.

## Cause: insufficient consumer capacity
Lag growing evenly across every partition during peak traffic. Scale the
consumer group up, bounded by partition count — consumers beyond the number of
partitions sit idle and add nothing.

## Cause: a slow downstream write
The consumer is healthy but blocked on writing. Check sink write latency before
scaling. Adding consumers against a saturated sink makes the sink worse and lag
will not improve.

## Do not
Do not reset offsets to latest to clear lag. It looks like an instant fix and
silently discards every unprocessed message, which for settlement data is a
reportable data-loss event.
"""

DOCS["runbooks/disk-pressure-eviction.md"] = """\
# Runbook: Node disk pressure and pod eviction

Applies to all Kubernetes workloads. Paged as `NodeDiskPressure`.

## Symptoms
Pods are evicted and rescheduled with no application error preceding them. The
distinguishing pattern is several unrelated services restarting on the same node
simultaneously, which separates this from an application crash loop.

## Immediate check
Identify the node and inspect filesystem usage. The kubelet begins evicting at
85 percent by default, so pressure starts well before the disk is actually full.

## Most common cause: log volume
An application logging at debug level in production, usually left enabled after
an investigation. One verbose pod can fill a node's disk within hours and evict
every other workload sharing that node.

## Second cause: image accumulation
Unused container images that were never garbage-collected on long-lived nodes.
This builds over weeks rather than hours, and presents as several nodes crossing
the threshold within a few days of one another.

## Mitigation
Cordon the node so nothing new schedules onto it, then reclaim space. Do not
delete application data volumes to free space under time pressure — confirm what
a volume holds before removing anything.

## Prevention
Every service needs a guard preventing debug log levels in production, and node
image garbage collection should be verified during cluster maintenance.
"""

DOCS["runbooks/auth-401-spike.md"] = """\
# Runbook: Authentication 401 error spike

Applies to `auth-service` and every service behind it. Paged as `Auth401RateHigh`.

## Symptoms
A sharp rise in 401 responses. Users report being logged out mid-session. The
auth service itself reports healthy throughout, because it is rejecting requests
correctly — its own health checks pass the entire time.

## Immediate check
Separate 401s from 403s before anything else. A 401 spike is a credential or
token problem. A 403 spike is an authorisation or policy problem and is a
different runbook entirely.

## Cause: signing key rotation
A rotated JWT signing key that has not propagated to every validating service.
The signature is 401s isolated to a subset of services while others are
unaffected, beginning exactly at the rotation timestamp. Verify the key ID
inside a rejected token against the current active key.

## Cause: clock skew
Validation fails because a node's clock has drifted past the token's validity
window. The signature is 401s isolated to a single node while the token expiry
is still in the future by the client's clock. Check time synchronisation on the
affected node.

## Cause: upstream identity provider outage
Tokens cannot be refreshed, so sessions expire naturally and are never renewed.
The signature is a gradual ramp over roughly one token lifetime rather than a
step change. Check the provider's status page before treating this as internal.

## Mitigation
Do not disable token validation to restore service. Rolling back a key rotation
is safe; disabling validation is not, at any severity.
"""

DOCS["postmortems/2026-03-14-payments-degradation.md"] = """\
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
"""

DOCS["postmortems/2026-05-02-batch-overrun.md"] = """\
# Postmortem: Settlement batch overrun, 2 May 2026

Severity P3. No customer impact. Author: data platform.

## Impact
The nightly settlement batch, normally complete by 03:10, finished at 09:40. The
morning reconciliation report was six hours late. No data was lost or incorrect.

## Timeline
01:00 — Batch started on schedule.
03:10 — Expected completion. No alert fired, because the only alert is on batch
failure and the job had not failed; it was simply still running.
08:15 — A finance analyst reported the report was missing. This was the first
anyone knew of it.
08:40 — Consumer lag on `settlement-consumer` found to be six hours and growing.
09:05 — The sink database was found to be the bottleneck, running an unrelated
index rebuild started by a maintenance window at 00:30.
09:40 — The index rebuild completed and the batch drained on its own.

## Root cause
An unrelated maintenance job held write locks on the settlement sink for most of
the batch window. The consumer was healthy and simply blocked on writes. Scaling
the consumer group, which was considered at 08:50, would have made the lock
contention worse.

## What went wrong beyond the cause
There is no alert for a batch that runs long without failing. Detection came
from a human noticing a missing report, six hours after the fact. The
maintenance window and the batch window overlap and neither team knew.

## Corrective actions
Alert on batch duration exceeding 150 percent of its rolling median, not only on
failure. Publish maintenance windows to a shared calendar the batch owners see.
"""

DOCS["postmortems/2026-06-21-certificate-outage.md"] = """\
# Postmortem: Gateway outage from expired certificate, 21 June 2026

Severity P1. Full outage for 31 minutes. Author: platform.

## Impact
All traffic through the internal gateway failed for 31 minutes. Every dependent
service was unavailable. This was a complete outage, not a degradation.

## Timeline
06:00 — The gateway's TLS certificate expired.
06:00 — Traffic dropped to zero. `TlsHandshakeFailureRate` fired within a minute.
06:04 — On-call acknowledged. Initial investigation focused on the gateway
process itself, which was healthy, and on a suspected network fault.
06:18 — A client-side handshake reproduced the error and showed the expiry date.
06:22 — The renewed certificate, which had been generated three weeks earlier and
never deployed, was located and deployed.
06:31 — Traffic recovered fully.

## Root cause
The certificate was renewed on 30 May, during a change freeze. Deployment was
deferred until after the freeze and no ticket carried it. The thirty-day and
seven-day expiry reminders were both delivered by email, both acknowledged, and
neither paged. The renewed certificate sat undeployed for three weeks.

## What went wrong beyond the cause
Fourteen minutes were spent investigating the gateway process and network before
anyone checked the certificate, despite the drop to zero traffic being a
signature specific to handshake failure. The runbook covers this and was not
opened.

## Corrective actions
Certificate expiry inside seven days must page rather than email. Renewal and
deployment must be a single tracked unit of work — a renewed certificate that
has not been deployed is not a completed renewal. Add certificate validity to
the gateway dashboard.
"""

DOCS["reference/alerting-thresholds.md"] = """\
# Reference: Alert thresholds and routing

Current as of July 2026. Changes require review by the owning team.

## Latency
`ApiLatencyP99High` fires when p99 exceeds the service SLO for five consecutive
minutes. Routes to the owning team, pages between 07:00 and 22:00, and pages
around the clock for tier-one services.

## Saturation
`CreditApiPoolSaturation` fires when `pool_active_connections` reaches
`pool_max_connections` for two consecutive minutes. Pages around the clock.

`NodeDiskPressure` fires at 80 percent filesystem utilisation, five percentage
points below the kubelet eviction threshold, to leave room to act before pods
start moving.

## Errors
`Auth401RateHigh` fires when the 401 rate exceeds three times the rolling
seven-day median for ten minutes. The multiplier rather than an absolute
threshold is deliberate — absolute thresholds were too noisy across services
with very different baseline rates.

`TlsHandshakeFailureRate` fires on any handshake failure rate above one percent
for two minutes. Pages around the clock at any hour.

## Known gaps
Certificate expiry warnings at thirty and seven days are email-only and page
nobody. This is a known gap with a corrective action open against it from the
21 June postmortem.

Batch jobs alert on failure only, not on duration. A job that runs long without
failing is invisible to monitoring. Open from the 2 May postmortem.
"""

DOCS["reference/escalation-policy.md"] = """\
# Reference: Severity definitions and escalation

## Severity
P1 — complete loss of a customer-facing service, or any data-loss event.
Engages the incident commander rotation immediately and notifies leadership
within fifteen minutes.

P2 — significant degradation with a workaround available, or partial loss of a
non-critical service. Owning team leads; the incident commander is optional.

P3 — minor or internal-only impact with no customer visibility. Handled in
business hours.

## Escalation triggers
Escalate one level when a P2 is unresolved after sixty minutes, when the cause is
unknown after thirty minutes at P1, or when mitigation requires a change the
on-call engineer is not authorised to make.

## Authorisation limits
On-call may roll back a deploy, restart pods, scale a workload, and cordon a
node without further approval.

On-call may not disable authentication or TLS verification, reset consumer
offsets on financial data, delete a persistent volume, or modify an alert
threshold during an active incident. Each requires the owning team plus, for the
first two, security.

## Communication
Post an update every fifteen minutes at P1 and every thirty at P2, whether or not
anything has changed. Silence is read as an escalation by everyone watching.
"""

DOCS["reference/service-dependency-map.md"] = """\
# Reference: Service dependency map

## Tier one
`gateway` — all external traffic. Every service depends on it. A gateway failure
is a total outage by definition.
`auth-service` — token issuance and validation. Every authenticated path depends
on it.
`payments-api` — authorisation and capture. Depends on gateway, auth-service, and
the payments database.

## Tier two
`credit-api` — credit decisions. Depends on gateway, auth-service, and the credit
database. Fronted by `credit-worker` for asynchronous work.
`settlement-consumer` — consumes the settlement topic and writes to the
settlement sink. No synchronous dependents; failure delays data rather than
breaking requests.

## Shared infrastructure
The credit and payments databases share a cluster. Saturating one affects the
other, which is why raising a connection pool limit is not a safe unilateral
mitigation.

Both the settlement sink and the reporting database sit on the same storage
backend as the analytics warehouse. A maintenance operation on any one can block
writes to the others — this caused the 2 May batch overrun.

## Reading this during an incident
Failures propagate downward, so a symptom in a tier-two service frequently
originates in tier one. Check auth-service and gateway health before deep-diving
a tier-two service.
"""


def main() -> None:
    for rel, body in DOCS.items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    print(f"wrote {len(DOCS)} documents under {ROOT}")


if __name__ == "__main__":
    main()
