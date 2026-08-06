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
