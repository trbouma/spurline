---
title: Witness Operator Runbook
description: Commission a Spurline instance and authorize its observation witness role.
---

# Witness Operator Runbook

## What is available

Operators can commission a Spurline identity and separately authorize it as an
observation witness for OpenETR kinds 1415 and 1416. Both exchanges retain signed
evidence and expose it for independent verification.

**Automatic Witness Records are opt-in.** Durable jobs, clock-health
gating and local publication are implemented; see [operation](automatic-witness-operation.md).
The frozen
experimental receipt kind is 1418; see the [wire profile](observation-receipt-v1.md). `authorized` is permission to perform a role, not evidence that the
service is currently performing it. `receipt_issuance_enabled` reports configuration,
not clock health or successful issuance.

Use this runbook to prepare and inspect authorization. Do not advertise an active
timestamp service until the receipt implementation and its operational checks
are complete.

## Responsibilities and prerequisites

The deployment administrator controls the relay configuration, persistent data,
and service key. The commissioning operator controls a separate signing key
and approves the relationship and policy. A relying application independently
decides whether to trust that operator as a commissioning authority.

Before starting:

- Configure a stable `SPURLINE_SERVICE_NSEC`, management mode, and persistent
  `SPURLINE_DATABASE`. Protect the service secret separately from public evidence.
- Confirm the intended operator npub through an independent channel. A valid
  signature does not itself establish that it is the operator you intended.
- Keep the operator private key out of the relay container. Have an external
  signing workflow capable of reviewing and signing the exact event schema.
- Confirm the mounted data directory is backed up and access-controlled.
- Prepare a public witness policy. Do not put credentials, private host details,
  or other secrets in this policy.

The following commands assume the repository's Docker Compose service named
`spurline`. Local development equivalents use `poetry run spurline` and the same
environment settings. These are local administrative operations, not public
HTTP mutation routes.

## Commission the service identity

Inspect the current state:

```bash
docker compose exec -T spurline spurline service show
```

For an uncommissioned instance, substitute the real operator npub:

```bash
docker compose exec -T spurline spurline service request npub1operator...
```

Pass the resulting signed `commissioning_request` to the operator. The operator
checks the service identity, management mode, nonce, validity window, and intended
relationship, then signs the attestation described in the
[commissioning format](service-commissioning.md#operator-attestation-format).
Creating the request does not sign on the operator's behalf.

Use the offline [Operator Signing CLI](operator-signing.md) to validate and sign
the request on an operator workstation with a hidden private-key prompt.

Import the returned event and verify the chain:

```bash
docker compose exec -T spurline spurline service commission < attestation.json
docker compose exec -T spurline spurline service verify
```

Expected result: `state: commissioned` with verified service-key control,
operator authorship, and reciprocal relationship. Confirm the reported operator
npub, not just the success state.

## Prepare and approve the witness policy

The policy should identify its owner and version and explain:

- What the relay observes: a complete signed event with a verified ID and signature.
- Which subject kinds are permitted; initially 1415 and 1416 only.
- Clock sources, synchronization monitoring, allowed uncertainty, clock-jump
  handling, and circumstances in which witnessing must stop.
- Retention, publication destinations, export arrangements, and removal exceptions.
- Service-key protection, incident reporting, and handling of compromise or
  disputed time assertions.
- Limits on the claim: no certification of content, authority, OpenETR state,
  global completeness, or exact original creation time.

These are policy commitments, not capabilities already enforced by the current
authorization implementation. The CLI checks the exact policy digest, not the
adequacy of its promises. Do not claim operational guarantees you cannot meet.

Place the UTF-8 policy at `/data/witness-policy.txt` in the container's mounted
data directory. Its exact bytes, including line endings, determine the digest.
It must be nonempty and no larger than 256 KiB and will be publicly retrievable.

Request 30 days of authorization for both OpenETR kinds:

```bash
docker compose exec -T spurline spurline service witness request \
  --policy /data/witness-policy.txt \
  --valid-for 2592000 \
  --kind 1415 --kind 1416
```

The response includes signed `evidence.request`, the policy, and an
`unsigned_authorization` template. The validity period starts now. Complete the
exchange within 24 hours or before the requested authorization expires,
whichever comes first.

The same commissioned operator must review the policy, digest, service key,
commissioning reference, kinds, and time interval before signing. It must not
sign a template merely because the relay supplied it. Follow the
[witness signing instructions](service-commissioning.md#authorize-the-observation-witness-role),
including consistent `created_at` and content `issued_at` values. The operator
returns a signed event, never its private key.

The [Operator Signing CLI](operator-signing.md#sign-an-initial-witness-authorization)
supports initial witness grants with commissioning-chain and exact-policy verification.

## Import and publish authorization

```bash
docker compose exec -T spurline spurline service witness authorize < witness-authorization.json
docker compose exec -T spurline spurline service witness verify
docker compose exec -T spurline spurline service publish --relay ws://127.0.0.1:8080
docker compose exec -T spurline spurline service witness publish --relay ws://127.0.0.1:8080
```

Check that the witness result names the intended operator, policy digest, subject
kinds, validity interval, and authorization event ID. `evidence_verified: true`
means the retained evidence verifies; check `state` separately for current
authorization. Receipt issuance must be enabled separately.

Repeat `--relay` for additional publication destinations. All requested relays
must acknowledge each event. Publication is not atomic across events or relays;
after partial failure, retrying sends the same signed events. The policy artifact
is not uploaded by these commands, so distribute it separately or retain access
to the public evidence endpoint.

Public inspection resources are:

| Resource | Information |
| --- | --- |
| `GET /info` | Service identity and witness-authorization summary |
| `GET /v1/service-identity` | Complete commissioning chain |
| `GET /v1/witness-authorization` | Witness request, authorization, exact policy text, and current state |

Publishing permission does not publish a Witness Record for an OpenETR event.
Those are separate receipt events described in the
[application integration guide](openetr-witness-records.md).

## Routine checks and failure handling

| Observation | Operator action |
| --- | --- |
| `not-authorized` | Complete commissioning, then request witness authorization |
| `pending` | Obtain the commissioned operator's signed response |
| `request-expired` | Create a fresh pending request and obtain a fresh response |
| Wrong operator or changed terms rejected | Check the identities and exact request; do not bypass verification |
| `not-yet-valid` | Check local time and signing time; do not bypass the validity test |
| `authorized` with issuance disabled | Default configuration; enable only with a functioning clock monitor |
| `expired` | Preserve history and request a signed renewal; do not treat old permission as current |
| Evidence verification fails | Investigate identity, policy, or database changes; do not overwrite evidence to clear the error |

Signed renewal, revocation, and local suspend/resume are now implemented.
Follow the [lifecycle runbook](witness-lifecycle.md); a renewal never clears
local suspension. Service-key replacement remains separate work.

If a service key or operator key is suspected compromised, preserve evidence,
notify relying parties through established channels, and suspend affected
service operation where appropriate. Use `revocation-request`, obtain the operator signature, then `revoke` and
`publish`. Local `suspend` immediately blocks witness permission but does not
notify other parties or revoke externally held evidence. Deleting local state or removing a relay copy does not revoke copies
already held elsewhere.

## Backups and production acceptance

Retain the relay database, `<SPURLINE_DATABASE>.service.sqlite3`, identity sentinel,
policy artifacts, and exported signed evidence. Use a consistent SQLite backup
method or stop writers before copying database files. Store service-key recovery
material separately and restrict access; public evidence is not a key backup.

Before enabling receipt generation in a deployment, test the
operator-approved clock policy, expiry and suspension behavior, bounded queues,
crash recovery, duplicate handling, local and external receipt discovery, and
failure reporting. Test an application that validates the entire chain, not just
one that finds an event with a matching `e` tag.
