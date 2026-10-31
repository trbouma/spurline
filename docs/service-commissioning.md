# Service commissioning

For a task-oriented walkthrough, see the [witness operator runbook](witness-operator-runbook.md).
Applications can use the proposed [Witness Record discovery flow](openetr-witness-records.md)
once receipt generation is implemented.

Spurline supports the same reciprocal service commissioning evidence model as
Clear: a service-signed request, an operator-signed attestation, and a
service-signed descriptor. The service type is `nostr-relay` and the descriptor
advertises `nostr.relay`. Commissioning establishes an attributable operator
relationship, not certification, trusted time, or a guarantee of relay behavior.

## Configure the identity

Set `SPURLINE_SERVICE_NSEC` through the deployment's secret configuration and
retain it across restarts. `SPURLINE_SERVICE_MANAGEMENT` accepts `independent`
or `mainstay-managed`. The CLI reads these variables and `SPURLINE_DATABASE`,
just like the server. Global CLI flags override the corresponding environment
settings; put them before `service`.

Administrative commands require local access to the configured service key and
data directory. There are no public HTTP mutation endpoints. The operator's
private key remains outside Spurline.

## Commission the relay

Create a request naming the intended operator's public key:

```bash
docker compose exec -T spurline spurline service request npub1operator...
```

For development, use `poetry run spurline service request npub1operator...`.
The response contains `commissioning_request`, a signed Nostr event. Send that
event to the operator's signing workflow. The operator must verify the request
and intentionally authorize the relationship before signing the attestation.
The abbreviated npub above is a placeholder, not a usable key.

Import the operator's signed attestation:

```bash
docker compose exec -T spurline spurline service commission < attestation.json
docker compose exec -T spurline spurline service show
docker compose exec -T spurline spurline service verify
```

Input can be a raw event object or an object containing `event`. Local CLI use
also supports `service commission --file attestation.json`. Spurline validates
the event ID and signature, exact requested operator, request reference, service
identity, management mode, schema, tags, and time bounds before committing the
complete evidence chain atomically.

Requests use a random 32-byte nonce and expire after 24 hours. A new request
supersedes a pending request; an attestation for the old request is rejected.
The same completed attestation can be imported again safely. Different
attestations and new requests are rejected once commissioned.

Request expiry is an exchange deadline, not authorization expiry. Historical
verification continues after the request expires. This initial profile supports
only the initial `authorize` relationship, sequence 1 with no predecessor.
Renewal, revocation, operator changes, and service-key rotation require a future
lifecycle profile; do not delete the stored evidence to simulate those actions.

## Operator attestation format

The exchange uses Clear's version-1 Mainstay schemas:

| Evidence | Kind | Schema |
| --- | --- | --- |
| Request | 78 | `org.mainstay.service-commissioning-request` |
| Operator attestation | 30078 | `org.mainstay.service-operator-attestation` |
| Descriptor | 30078 | `org.mainstay.service-descriptor` |

The attestation's canonical JSON content contains exactly these fields:

```json
{
  "action": "authorize",
  "commissioning_request": "<request event id>",
  "installation": "<operator hex pubkey>",
  "issued_at": 1800000000,
  "management": "mainstay-managed",
  "previous": null,
  "relationship": "operates",
  "schema": "org.mainstay.service-operator-attestation",
  "schema_version": 1,
  "sequence": 1,
  "service": {"pubkey": "<relay hex pubkey>", "type": "nostr-relay"}
}
```

Replace placeholders and the example timestamp; `management` must match the
request. Encode content with sorted keys and compact JSON separators. The event
author is the requested operator, and `created_at` equals `issued_at`, within
the request's validity window. Required tags are:

```json
[
  ["d", "org.mainstay.service-operator-attestation:<relay hex pubkey>"],
  ["p", "<relay hex pubkey>", "", "service"],
  ["e", "<request event id>", "", "commissioning-request"],
  ["service-type", "nostr-relay"]
]
```

The `mainstay-managed` value is a lifecycle label, not remote administrative
access. This change supplies Spurline's local commands and evidence format;
it does not add a `mainstay-local service commission spurline` wrapper.

## Public discovery and publication

`/`, `/info`, and `/.well-known/nostr.json` report the commissioning state,
operator npub, and descriptor event ID. `GET /v1/service-identity` returns
`service_identity` and the complete public `evidence` object. The HTML home page
also reflects commissioning state. No private keys are returned.

Publish the retained events explicitly:

```bash
docker compose exec -T spurline spurline service publish --relay ws://127.0.0.1:8080
```

Repeat `--relay` to publish to multiple destinations. Each event must receive an
acknowledgment from every distinct requested relay. Publication is not atomic:
on failure some events may already have been accepted. Local commissioning
evidence remains intact; retrying publishes the same event IDs. Publication does
not establish that a relying party trusts the operator or guarantees retention
at the destination relay. The original request includes an expiration tag, so
retain the complete local evidence even if a remote relay expires that event.

## Persistence and safety boundaries

The administrative database is `<SPURLINE_DATABASE>.service.sqlite3`, beside the
relay database. It is independent of public event storage and NIP-09 deletion.
Back up it and `service-identity.json` with the relay data, and protect the
service secret separately. Local commands and the server share this state;
commissioning updates are visible without restarting.

Startup and public discovery validate retained commissioning evidence. An
invalid chain is not presented as commissioned. Commissioning validation is
always enabled, even when normal relay signature checks are disabled for
testing. Ordinary uncommissioned relay operation remains supported.

This does not implement Clear's mint-specific readiness checks or treasury gate.
Service commissioning alone does not authorize timestamp receipts, provide
append-only public storage, or implement PQ signatures. Relying parties must
explicitly decide which operators they recognize.

The [automatic observation receipt proposal](automatic-observation-receipts.md)
describes discoverable signed receipts for OpenETR events. The `operates`
relationship does not authorize that role; the separate exchange below does.

## Authorize the observation witness role

After commissioning, the relay can request an additional `observation-witness`
authorization from that same operator. This records permission, not a trust
decision on behalf of clients. It does not start a receipt worker: all current
status responses report `receipt_issuance_enabled: false`.

Prepare a UTF-8 policy file covering clock requirements, uncertainty,
retention, and operational responsibilities. Its exact bytes are hashed with
SHA-256 and retained alongside the signed evidence. **The entire policy is
publicly exposed; do not include secrets or private configuration.** Maximum
size is 256 KiB. The software binds authorization to the policy but does not
certify its adequacy or enforce clock requirements yet.

For local development, with the relay environment configured:

```bash
poetry run spurline service witness request \
  --policy witness-policy.txt \
  --valid-for 2592000 \
  --kind 1415 --kind 1416
```

The duration is in seconds; the example requests 30 days. It is required and
must be positive and no greater than 365 days. The validity period starts when
the request is created, not when it is accepted. The request must be completed
within 24 hours or before authorization expiry, whichever comes first. Omit
`--kind` to request both 1415 and 1416; no other kinds are currently supported.

For Docker, place the public policy in the mounted data directory and run:

```bash
docker compose exec -T spurline spurline service witness request \
  --policy /data/witness-policy.txt --valid-for 2592000
```

The response includes a service-signed `evidence.request`, the retained policy,
and an `unsigned_authorization` template. The commissioned operator should
independently verify the service request, commissioning reference, policy digest,
scope, and validity period. It then signs the template using its own key outside
Spurline. The template is not an authorization until signed. If updating the
signing time, update both `created_at` and content `issued_at` consistently,
within the request window, and serialize content canonically before signing.

Import the operator's signed event and inspect the result:

```bash
docker compose exec -T spurline spurline service witness authorize < witness-authorization.json
docker compose exec -T spurline spurline service witness show
docker compose exec -T spurline spurline service witness verify
docker compose exec -T spurline spurline service witness publish --relay ws://127.0.0.1:8080
```

Local equivalents use `poetry run spurline`; `authorize --file PATH` is also
supported. Import accepts a raw event or an object containing `event`, never an
operator private key. Publishing sends the signed request and authorization;
publish the commissioning chain separately with `service publish`. It does not
upload the policy artifact to other relays. Retrieve the exact policy through
the public evidence endpoint or export it with an evidence package.

The request uses kind 78 and schema
`org.spurline.witness-authorization-request`. The authorization uses kind 30078
and schema `org.spurline.witness-authorization`, version 1. Its address is
`org.spurline.witness-authorization:<service hex pubkey>`. Required signed terms
include `role`, service identity, operator identity, commissioning attestation
ID, request event ID, policy digest, permitted kinds, `not_before`, and
`not_after`. The request's generated template specifies all content and tags;
the operator may accept those terms or ask for a new request, not change them
silently. Initial authorization has `sequence: 1` and `previous: null`.

An `e` tag links the authorization to its exact request and another to the
commissioning attestation. All event identifiers and signatures are checked
even if ordinary relay validation is disabled. Policy bytes and signed evidence
are retained in the same administrative database used for commissioning.

`GET /v1/witness-authorization` exposes the public evidence and current state.
Relay info responses include a `witness_authorization` summary. States include
`not-authorized`, `pending`, `request-expired`, `not-yet-valid`, `authorized`,
and `expired`. `verify` verifies retained evidence even after expiry and reports
the current state; `evidence_verified: true` alone does not mean currently
authorized. Clients must evaluate the interval, their own trust policy, and
the receipt-issuance capability separately.

A new pending request invalidates the prior pending request. Reimporting the
same authorization is idempotent. Use `service witness renew` for a fresh signed
grant, `revocation-request` and `revoke` for operator-signed withdrawal, and
`suspend` / `resume` for independent local safety control. Signed history is
preserved; `history` and `publish` cover all accepted lifecycle events. See the
[lifecycle guide](witness-lifecycle.md) for commands and historical semantics.
