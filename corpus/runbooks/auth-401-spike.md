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
