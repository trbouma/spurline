# Witness Authorization Lifecycle

Implemented experimental lifecycle profile, 31 October 2026. Automatic receipt
issuance is disabled by default and can be [enabled separately](automatic-witness-operation.md).
These commands manage permission and local safety
state, not clock health or receipt jobs.

## Signed authority and local operation

The commissioned operator signs grants, renewals, and revocations. The relay
administrator can separately suspend or resume local permission. Resuming cannot
create authority, undo expiry, or override a signed revocation. A renewal never
clears a local suspension.

`authorization_state` reports the signed grant's current state. `state` becomes
`suspended` when the local control is set. `witnessing_permitted` means current
authorization and no local suspension; it is only an authority gate. It does
not establish clock health or worker availability. `receipt_issuance_enabled`
reports configuration only, not clock health or successful issuance.

## Renew

```bash
docker compose exec -T spurline spurline service witness renew \
  --policy /data/witness-policy.txt --valid-for 2592000 --kind 1415 --kind 1416
```

The response contains a service-signed renewal request and an
`unsigned_authorization` template for the commissioned operator. It binds the
policy bytes, scope, validity period, exact previous lifecycle event ID, and
next sequence. Have the operator verify and sign the template externally, then:

```bash
docker compose exec -T spurline spurline service witness authorize < renewal.json
```

Preparing a renewal does not remove the existing grant. The pending request and
its deadline are shown separately. An expired pending renewal does not expire
the current grant early. Importing the renewal advances the head atomically;
stale requests and conflicting predecessors are rejected. Renewal is also
permitted after expiry or revocation, but requires a fresh explicit operator
signature. It does not revive the old authorization event.

## Revoke

Generate an unsigned template for the current head:

```bash
docker compose exec -T spurline spurline service witness revocation-request \
  --reason "Withdrawal of witness authority"
```

The operator reviews and signs `unsigned_revocation` outside the relay. Its
`issued_at`, `effective_at`, and outer `created_at` must be the same integer Unix
second, no earlier than the predecessor's time. For a delayed signing, update
all three consistently and reserialize content canonically. Import it with:

```bash
docker compose exec -T spurline spurline service witness revoke < revocation.json
docker compose exec -T spurline spurline service witness publish --relay ws://127.0.0.1:8080
```

Import checks the commissioned signer, service, commissioning reference, role,
exact predecessor, and next sequence. Future-dated revocations are rejected.
Successful revocation immediately blocks local witness permission and clears a
pending renewal. Publication is a separate step; import alone does not notify
other applications. Reimporting an identical accepted event is idempotent and
does not roll the head back. The reason is public signed content (1–512 characters).

The operator can construct this exact signed event without relying on the
relay to supply a template. Local enforcement still requires import. External
verifiers need retrieval or supplied evidence of the revocation; no global
revocation dissemination guarantee exists.

## Suspend and resume locally

```bash
docker compose exec -T spurline spurline service witness suspend --reason "Clock investigation"
docker compose exec -T spurline spurline service witness resume --reason "Clock checks completed"
```

These operations require local administrative access. They survive restarts and
append local audit entries. Reasons are retained locally and omitted from public
HTTP responses and publication. Public status exposes suspension, but it is
operational metadata, not signed revocation evidence.

Resume requires a currently valid grant and does not itself perform the claimed
clock checks. Ordinary relay traffic is unaffected. If evidence validation fails,
permission must fail closed; suspension is not a way to bypass corrupt evidence.

## Evidence format and preservation

Initial version-1 grants remain valid and are retained byte-for-byte. New
renewal requests and operator lifecycle events use schema version 2. Renewal
requests retain the request schema and add `action: renew`, `sequence`, and
`previous`. Renewed grants retain the authorization schema, copy those signed
terms, and use the same scope, policy, and validity fields as the initial grant.

Operator events remain kind 30078. Version-2 grants use a unique `d` value:
`org.spurline.witness-authorization:<service hex pubkey>:<request id>`.
Revocations use
`org.spurline.witness-authorization:<service hex pubkey>:revoke:<previous id>`.
This avoids our renewals replacing earlier grants at one mutable address.
It does not prevent the author or a remote relay from replacing or deleting
copies. Retain exact-event evidence packages, not just current addresses.

Revocation content contains exactly `schema`, `schema_version: 2`, `action: revoke`,
`role`, `service`, `operator`, `management`, `commissioning_attestation`,
`issued_at`, `effective_at`, `reason`, `sequence`, and `previous`. The generated
template specifies the exact tags. `previous` names the accepted head and
`sequence` advances by one. A revocation cannot directly follow another
revocation; a renewed grant must explicitly reauthorize the role first.

The administrative database retains the ordered signed history and every accepted
grant's policy artifact. Legacy singleton grants are imported unchanged on the
first lifecycle write. Local controls are stored separately. All lifecycle
transitions use a transaction; a failed import leaves authority unchanged.

```bash
docker compose exec -T spurline spurline service witness history
docker compose exec -T spurline spurline service witness verify
docker compose exec -T spurline spurline service witness publish --relay ws://127.0.0.1:8080
```

`publish` sends the complete accepted history: grant requests, authorizations,
and revocations, in order. It does not publish pending requests, policy files,
or local control logs. `/v1/witness-authorization` returns signed history and
policies without local audit reasons. `/info` returns a compact summary.

## Historical receipts and conflicts

Expiry and renewal do not erase earlier permissions. For an independently
accepted time claim, evaluate the exact authorization named by the receipt,
not today's head. The signed permission window starts no earlier than both
grant issuance and `not_before`, and ends at `not_after` or a later signed
superseding transition's effective time, whichever comes first. Lifecycle times
are seconds; receipt times are milliseconds. Require the relevant observation
interval and issuance to fit the accepted permission window, and treat boundary
uncertainty conservatively rather than rounding it away.

Revocation's effective time is its signed issuance time, not a local import time.
An old receipt is not automatically invalid just because permission was later
withdrawn. Nor does a claimed earlier time make it trustworthy after suspected
key compromise: independently assess backdating, compromise evidence, and
authority recognition. This release validates lifecycle evidence and current
permission, not a complete historical timestamp trust decision.

The local database accepts one linear chain and rejects competing successors.
An external verifier discovering two valid signed successors must report a
conflict, not select one by timestamp, relay count, or arrival order. A complete
local history cannot prove the operator has not signed a different branch.
Key rotation and changes of commissioning operator remain separate work.
