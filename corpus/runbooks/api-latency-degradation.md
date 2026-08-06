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
