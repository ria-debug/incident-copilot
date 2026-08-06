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
