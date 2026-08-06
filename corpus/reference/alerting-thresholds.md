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
