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
