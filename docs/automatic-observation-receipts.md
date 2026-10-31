---
title: Automatic Observation Receipts
description: Proposed relay-signed witnesses for OpenETR events, discoverable by event reference.
---

# Automatic Observation Receipts

## Status and decision

Experimental local implementation, 31 October 2026. Receipt generation, clock-health
gating, and durable SQLite jobs are implemented behind an opt-in setting; see
[Automatic Witness Operation](automatic-witness-operation.md) for the implemented
scope and remaining limits. The [relay setup CLI](service-commissioning.md#authorize-the-observation-witness-role)
now supports an initial operator-signed witness authorization with a policy
digest, subject-kind scope, and validity period. Signed renewal and revocation plus local suspension are now implemented;
see the [lifecycle guide](witness-lifecycle.md). The base service commissioning
exchange establishes only an operator relationship; witness permission requires
the additional authorization. Neither exchange enables receipt issuance by itself.

Add opt-in automatic witnessing for configured event kinds, initially OpenETR
Anchor Events (1415) and Publisher Notices (1416). After observing and validating
an eligible signed event, Spurline would publish its own signed observation
receipt. Clients could retrieve that receipt using a reference to the original
event, from Spurline or another relay holding a copy.

The statement is deliberately narrow:

> This relay observed this particular signed event and successfully verified its
> event identifier and signature at the stated observation time.

It is not a declaration of OpenETR conformance, authority, truth, completeness,
or consequential validity. Receipt creation does not change an anchor or notice.

See the [operator runbook](witness-operator-runbook.md) for current setup and the
[OpenETR application guide](openetr-witness-records.md) for a sample Witness
Record, queries, verification steps, and multiple-witness handling.

## Explicit trust model

A valid receipt establishes authorship of a time assertion. Treating that
assertion as an accepted timestamp additionally requires trust in the witness's
clock, key custody, operating practices, and authorization.

A relying-party policy selects recognized commissioning authorities and the
relay keys they authorize for the observation-witness role. A self-declared
capability in a service descriptor is insufficient. The initial design uses
the commissioned relay service key to sign receipts; a separate witness key
would require an explicit, verifiable delegation profile.

The operator authorization should bind the service key, witness role, policy
version or digest, permitted subject kinds, validity interval, and lifecycle
references. The policy should define clock quality, publication limits,
retention, and compromise handling. Spurline's separate initial witness schema
implements the role, policy digest, kinds, and validity interval; its signed lifecycle and local suspension controls are now implemented. None of these are implied by Clear's version-1
`operates` attestation.

The verifier evaluates authorization at observation and receipt issuance,
including applicable revocation and compromise evidence. Queue processing must
not issue receipts after authorization ceases to permit issuance. A later
revocation does not automatically invalidate every historical receipt, nor
does a claimed pre-revocation timestamp automatically preserve trust.

There is no cryptographic proof of clock honesty in a relay signature. A stolen
witness key could sign backdated receipts. Independent witnesses or external
anchoring of signed receipt batches may provide additional evidence, but neither
is part of this initial implementation proposal.

## Bind the signed assertion

An ordinary Nostr event ID commits to the serialized event fields but excludes
the signature. Timestamping that ID alone does not establish that the signature
existed at observation time. An attacker could precommit unsigned contents under
another party's public key, then sign them after acquiring that party's key.

The proposed classical profile therefore commits to both the recomputed event
ID and the exact verified signature. Define:

```text
signed_event_digest = SHA256(
    ASCII("spurline.observed-signed-event.v1") || 0x00 ||
    decode_hex(event.id) || decode_hex(event.sig)
)
```

For this profile the decoded ID is exactly 32 bytes and the Schnorr signature
exactly 64 bytes; malformed lengths and encodings are rejected. The fixed domain
and lengths make the input unambiguous. Receipt verifiers recompute the event ID
from the subject and verify its signature before checking this commitment.

This profile does not cover PQ subjects. A future profile must explicitly
identify algorithms and encodings, with unambiguous lengths and domain separation.
Neither a PQ subject nor a PQ witness signature is silently accepted as classical.

## Receipt event and discovery

The receipt is a regular, non-replaceable Nostr event signed by the witness.
The frozen [version-1 profile](observation-receipt-v1.md) uses experimental kind
1418. This is a local selection, not a registered NIP. It does not repurpose
OpenETR kinds 1415 or 1416, linked-evidence kind 1417, or NIP-03 kind 1040.

Required tags would be:

```text
["e", SUBJECT_EVENT_ID]
["p", SUBJECT_AUTHOR_HEX]
["k", SUBJECT_KIND_DECIMAL]
["t", "spurline-observation-receipt-v1"]
```

Use exactly one subject `e` tag. The receipt's author is the relay, not the subject
author. Subject kind and author tags are discovery hints that must match the
validated subject, not substitutes for validation. No reply or OpenETR parent
relationship is implied by this reference.

Proposed canonical JSON content fields are:

| Field | Meaning |
| --- | --- |
| `schema` | `org.spurline.observation-receipt` |
| `schema_version` | Integer `1` |
| `subject_profile` | `nostr-schnorr-secp256k1-v1` |
| `event_id` | Exact subject ID, matching the `e` tag |
| `signed_event_digest` | Lowercase hex of the commitment defined above |
| `observed_at_ms` | UTC Unix milliseconds captured after successful subject validation |
| `issued_at_ms` | UTC Unix milliseconds at receipt signing |
| `clock_uncertainty_ms` | Nonnegative upper bound asserted under the witness's clock policy |
| `validation` | Fixed value `event-id-and-signature` |
| `observation_mode` | `live` or `backfill` |
| `witness_policy_digest` | SHA-256 of the exact retained policy artifact bytes |
| `authorization_event_id` | Exact operator authorization event supporting the witness role |

Encode content with sorted keys and compact JSON separators. Times and uncertainty
are integers, not booleans or floating-point values. Require issuance not to
precede observation. The receipt's ordinary `created_at` equals the floor of
`issued_at_ms / 1000`; it is not the subject's time or the receipt observation time.
Pin exact policy and authorization evidence in portable packages rather than
relying only on the latest mutable descriptor.

Clients could subscribe before publishing, or query afterward:

```json
["REQ", "observation-receipts", {
  "kinds": [1418],
  "#e": ["<subject event id>"],
  "#t": ["spurline-observation-receipt-v1"],
  "authors": ["<recognized witness hex pubkey>"]
}]
```

The angle-bracket strings are placeholders. The kind filter selects the
experimental receipt profile, but does not establish its validity. Returned events remain untrusted until their signatures,
schema, subject binding, and witness authorization have been checked. An `e`
reference alone must never turn an arbitrary event into a recognized receipt.

## Automatic generation and durable processing

Recommended initial controls are disabled-by-default witnessing, an explicit
kind allowlist, recognized operator authorization, a fixed witness policy, and
bounded job and publication queues. No environment variable names are frozen yet.

The intended sequence is:

1. Receive a complete eligible event and independently recompute its ID and
   verify its signature, even if ordinary relay checks are relaxed.
2. Confirm witness authorization and clock health. Capture observation time and
   its uncertainty after verification, not from the author's `created_at`.
3. In one storage transaction, persist the accepted subject and immutable job
   inputs: exact signed subject, observation data, policy and authorization
   references, witness key identity, and idempotency key.
4. A bounded background worker rechecks eligibility to issue, signs the receipt,
   and durably stores the exact receipt and publication-outbox entry atomically.
5. Publish that same receipt into local relay storage and live subscriptions,
   then to any explicitly configured external destinations. Retry delivery of
   the stored receipt rather than creating a new signature or timestamp.

An idempotency key combines witness key, receipt profile version, and
`signed_event_digest`. Database uniqueness and transactional job claiming must
protect against simultaneous duplicate submissions and workers. Multiple valid
signature encodings for the same event ID are distinct signed subjects; a receipt
for one does not witness another signature. Event storage keyed solely by event
ID therefore cannot serve as the receipt-job uniqueness model.

A crash before the subject/job transaction commits leaves no durable observation
claim. A retry makes a new observation. A crash after the transaction commits
must preserve the original job inputs. A crash after signing but before receipt
commit can require signing again; no receipt may leave the worker before its
durable commit. Once committed, publication retries reuse its exact event ID.

SQLite now implements the transactional subject-and-job operation and atomic
receipt/outbox completion. External fan-out in the target pipeline above is not
implemented. Separate best-effort writes to the event database and
the commissioning sidecar are not sufficient. Commissioning evidence remains
administrative state; witness jobs and the receipt outbox need a coordinated
storage design and recovery tests for each future backend.

## Acceptance and failure semantics

An ordinary Nostr `OK` acknowledges subject acceptance, not receipt issuance.
Receipt signing or external publication can finish later. Clients requiring a
witness must wait for and verify a receipt, not infer one from `OK`.

Ordinary relay service may continue when witness authorization, clock health,
or job capacity is unavailable. In that case the relay must make no time claim
and record an explicit witness-unavailable outcome. A proposed read-only status
resource should expose `pending`, `issued`, or `unavailable` for the submitted
signed-subject digest, with bounded reason codes; exact HTTP routes remain to
be specified. Status is operational information, not signed evidence.

If an atomic subject/job write fails, report storage failure rather than claim
an observation was recorded. A deliberate accept-without-witness path is a
separate outcome, not a silent fallback from a partially failed transaction.
Public capability metadata and metrics should distinguish configured, active,
and degraded witnessing. Unavailable status never proves an event did not exist.

Clock policy must specify acceptable synchronization sources, uncertainty bounds,
maximum issuance delay, and behavior on backward jumps or loss of synchronization.
If the clock cannot meet the policy, stop time attestations. A monotonic clock
can measure delay but does not supply trusted UTC. Uncertain observation times
must not be replaced with a fresh healthy-clock reading while retaining the old
observation claim.

## Existing events, loops, and abuse

Automatic receipts initially apply to live observations after activation. Finding
an old event in storage does not justify using its author timestamp or an
unverified database insertion timestamp. An explicit backfill operation may
validate and witness it at the current time, marked `backfill`. An existing
durable receipt job keeps its earlier recorded observation on retry.

Exclude the receipt kind from automatic witnessing and reject configurations
that include it. The initial allowlist is only 1415 and 1416. This prevents
receipts from recursively producing receipts, including across witnessing relays.

Bound subject size, validation work, per-client intake, queue depth, retries,
and external destinations. A valid signature does not entitle an attacker to
unlimited signing or storage work. Publish receipts only to operator-configured
destinations, never to arbitrary URLs taken from subject tags. Do not embed the
subject's content in the public receipt. Even its ID and author can reveal
associations, so disclose automatic witnessing to publishers.

## Retention and OpenETR evaluation

Retain subjects, signed receipts, policy artifacts, and authorization history
according to the disclosed [evidence policy](append-only-evidence-policy.md).
A receipt is additional evidence, not a replacement for its subject. Copying a
receipt to another relay preserves its witness signature but does not make the
hosting relay a second witness. No global persistence guarantee follows.

With an accepted witness and clock policy, the signed subject existed no later
than the upper end of the attested observation interval:
`observed_at_ms + clock_uncertainty_ms`. This is not its exact creation time or
proof of when it was first published anywhere.

OpenETR verifiers should report receipt signature validity separately from time
witness recognition and the time conclusion. They must still evaluate anchors,
notices, missing predecessors, conflicts, and retrieval limitations under the
identified OpenETR ruleset. Witness timestamps must not automatically choose a
winning notice branch or manufacture authority for a transition.

## Acceptance tests before deployment

- Eligible 1415 and 1416 events produce discoverable signed receipts; other kinds
  and receipts themselves do not.
- Invalid IDs and signatures never receive receipts, including in relaxed relay
  mode. A later signature for previously timestamped unsigned contents does not
  match the signed-subject commitment.
- Duplicate and simultaneous submissions preserve the same committed receipt;
  different signatures cannot reuse it.
- Crash tests cover each transaction and publication boundary; partial external
  publication retries the identical event.
- Expired or absent witness authorization, unhealthy clocks, clock rollback,
  queue saturation, and excessive issuance delays produce explicit non-success.
- Discovery works by subject `e` reference, including publication-before-query
  and subscription-before-publication cases; malformed lookalike receipts fail.
- Backfill uses the current observation time, never silently backdates.
- An unrecognized signer remains an untrusted time witness despite a valid
  receipt signature. Revocation and compromise cases follow explicit policy.
- Normal relay traffic remains functional and bounded under receipt-worker
  failure and load; `OK` is never represented as a timestamp receipt.

The experimental kind, version-1 receipt format, and signed authorization
lifecycle are now defined. The next implementation milestone is clock-health
checks, transactional jobs, and local receipt publication. External fan-out and independent time anchoring can
follow without changing the meaning of a local observation.
