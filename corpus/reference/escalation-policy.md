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
