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
