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
