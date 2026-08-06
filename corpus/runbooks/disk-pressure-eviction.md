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
