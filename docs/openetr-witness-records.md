---
title: Finding Witness Records for OpenETR
description: Proposed receipt format, discovery queries, and multi-witness verification for applications.
---

# Finding Witness Records for OpenETR

## Integration model and implementation status

An application can present an OpenETR Anchor Record with a collection of
corresponding Witness Records. In this guide, **Witness Record** is the
application-facing name for a relay-signed observation receipt, not a new
OpenETR Anchor Event or Publisher Notice.

The relationship is one-to-many: each witness signs its own assertion about
observing the exact signed subject. The same approach applies to kind 1416
Publisher Notices, each referenced by its own event ID.

Spurline currently implements service commissioning, witness authorization,
signed renewal and revocation, and local suspension. **Automatic receipt generation and application trust evaluation remain pending.
The frozen experimental kind is 1418; wire/binding checks and a test fixture
are implemented in Spurline.** The formats and queries
below describe the intended integration contract. They do not make an existing
OpenETR verifier recognize these records automatically.

## Example Witness Record

The outer object is a standard signed event whose author is the witnessing
relay. This schematic uses experimental kind 1418 and placeholder IDs and
signatures. It is not a publishable test vector; see the
[frozen profile and fixture](observation-receipt-v1.md) for executable wire checks.
This example is version 1. [Version 2](observation-receipt-v2.md) instead explicitly
reports unspecified accuracy; its null uncertainty must never be treated as zero.
Queries using the v1 `t` marker alone exclude v2 receipts. Query by kind and `e`
reference to discover both, then validate each version explicitly.

```javascript
{
  "id": "<receipt event id>",
  "pubkey": "<witness relay hex pubkey>",
  "created_at": 1800000002,
  "kind": 1418,
  "tags": [
    ["e", "<anchor event id>"],
    ["p", "<anchor publisher hex pubkey>"],
    ["k", "1415"],
    ["t", "spurline-observation-receipt-v1"]
  ],
  "content": "<canonical JSON string of the receipt body below>",
  "sig": "<witness relay signature>"
}
```

The decoded content would look like this. On the wire it is a string encoded
with sorted keys and compact JSON separators, not a nested JSON object:

```json
{
  "authorization_event_id": "<operator-signed witness authorization id>",
  "clock_uncertainty_ms": 1000,
  "event_id": "<anchor event id>",
  "issued_at_ms": 1800000002000,
  "observation_mode": "live",
  "observed_at_ms": 1800000000000,
  "schema": "org.spurline.observation-receipt",
  "schema_version": 1,
  "signed_event_digest": "<commitment to anchor event id AND anchor signature>",
  "subject_profile": "nostr-schnorr-secp256k1-v1",
  "validation": "event-id-and-signature",
  "witness_policy_digest": "<sha256 of exact witness policy bytes>"
}
```

These times and the one-second uncertainty are illustrative, not a recommended
clock guarantee. `created_at` describes receipt issuance. `observed_at_ms`
describes the relay's observation after verification. Neither is the anchor's
self-declared creation time.

The signed-subject commitment is defined in the
[receipt design](automatic-observation-receipts.md#bind-the-signed-assertion).
It includes the subject signature to prevent an old commitment to unsigned
contents being presented as evidence that a later signature already existed.

For a Publisher Notice, replace the subject ID and author with the notice's own
values and use `"1416"` in the `k` tag. A receipt for an anchor does not witness
its subsequent notices or an entire Evidence Graph.

## Query after finding an anchor

First discover and validate an Anchor Event using the existing OpenETR process.
Then query configured evidence relays using its exact event ID:

```json
["REQ", "anchor-witnesses", {
  "kinds": [1418],
  "#e": ["<anchor event id>"],
  "#t": ["spurline-observation-receipt-v1"],
  "limit": 100
}]
```

Replace the placeholder with the actual ID. This deliberately omits `authors`
to discover receipts from multiple witnesses. To restrict retrieval to a known
set, add `authors` containing their hex public keys. Kind 1418 is experimental,
not a registered allocation. Schema and kind
validation still happen after retrieval; discovery tags are not proof.

The same query can run against multiple relays. A relay that stores a receipt
need not be the relay that signed it. Querying a relay does not cause it to
witness the anchor. To obtain multiple independent receipts, the subject must
actually reach multiple authorized, operational witnesses.

A client may subscribe before publication and receive receipts as they arrive.
The original event's `OK` acknowledgment is not a receipt. `EOSE` means the end
of stored results for that subscription, not that all possible witnesses have
responded or that discovery is globally complete. Close the subscription when
the application's monitoring window ends.

For several anchors or notices, an `#e` list can contain their IDs; associate
each returned receipt with its validated subject. Bound query size, responses,
timeouts, and validation work. A finite `limit` may truncate results. If more
retrieval is needed, use a tested bounded retrieval strategy and report its
scope rather than claiming an exhaustive witness list.

## Validate before accepting the timestamp

For every candidate Witness Record:

1. Verify its event ID and signature, supported kind, schema, and profile.
2. Validate the exact subject ID and signature. Check that its ID, author, and
   kind match the receipt content and discovery tags, and recompute the
   signed-subject commitment. An `e` tag match alone is insufficient.
3. Retrieve the exact `authorization_event_id`, witness request, commissioning
   chain, and policy artifact. Match the policy digest and service key; do not
   substitute the latest mutable authorization or descriptor for referenced
   evidence. Report missing evidence rather than treating it as authorization.
4. Verify that the commissioned operator signed permission for this service,
   witness role, policy, subject kind, and relevant interval. Evaluate the signed lifecycle and applicable compromise
   policy, including conflicting branches and retrieval limitations.
5. Apply the application's trust policy to the commissioning operator and the
   witness's stated clock practices. A valid signature from an unrecognized
   operator remains an attributable claim, not an accepted timestamp.
6. Check observation and issuance times, uncertainty, allowed issuance delay,
   and `live` versus `backfill` mode under that policy. Report the accepted
   time conclusion separately from the OpenETR ruleset result.

Retrieve dependencies from configured relays or supplied evidence packages.
Treat any advertised service URL as untrusted input subject to the application's
network policy, not an instruction to fetch arbitrary destinations.

For a recognized version 1 bounded-time receipt, the proposed accepted time conclusion is an upper bound: the signed subject
existed no later than `observed_at_ms + clock_uncertainty_ms`, conditional on
the recognized witness and policy. Preserve the stated uncertainty. This does
not establish exact creation time, content truth, legal authority, or the
consequential effect of the OpenETR event.

Version 2 does not support that numeric upper-bound calculation. Report its
observation time as operator-asserted operational time with unspecified accuracy;
do not use it alone to prove strict UTC deadlines or ordering across relays.

## Multiple witnesses and duplicate copies

Deduplicate identical receipts by receipt event ID, but retain the list of
retrieval sources. Group verified receipts by subject commitment and witness
public key. Multiple different receipts from one key are not independent
witnesses; preserve discrepancies rather than silently selecting a preferred
timestamp. Different keys under one operator may also share infrastructure or
clock sources, so independence is a policy assessment, not just a key count.

| Retrieved evidence | Application interpretation |
| --- | --- |
| Same receipt from three hosting relays | One signed witness assertion, three observed copies |
| Different valid receipts from three witness keys | Three witness assertions; assess trust and independence separately |
| Receipt signed by an unrecognized witness | Verifiable claim, but no accepted time conclusion under current policy |
| Receipt with unavailable authorization | Incomplete supporting evidence, not an accepted timestamp |
| Two differing receipts from one witness | Preserve both and evaluate the discrepancy |
| No receipt retrieved | No witness evidence found within this retrieval scope |

Different observation times are expected when relays receive an event at
different times. Do not average them, treat the newest as authoritative, or
use a simple majority to resolve OpenETR notice conflicts. A policy may select
the earliest accepted upper bound, but should retain the supporting receipt
and all relevant qualifications rather than presenting an unexplained single
timestamp.

## Suggested application presentation

Keep the Anchor Record's existing verification result intact and add a
separate **Witness Records** section. Suggested fields per receipt are:

- Witness service identity and commissioning operator.
- Observation time, uncertainty, and receipt issuance time.
- Signature validity, authorization findings, and time-witness trust decision.
- Policy and authorization references, observation mode, and receipt ID.
- Retrieval sources and any unresolved evidence or conflicting claims.

Use separate counts for discovered receipts and recognized distinct witnesses.
An empty state should say **“No Witness Records found in the queried sources”**,
not “unwitnessed,” “invalid,” or “never existed.” Do not turn a valid anchor into
an invalid one merely because this optional supporting evidence is absent.

The same component can appear alongside Publisher Notices. Witness Records
support observation and time assessment; the OpenETR ruleset continues to
govern anchors, notices, missing links, and conflicting branches.

## Integration milestones

The [receipt profile](observation-receipt-v1.md) and cryptographic fixture are
now defined, alongside the operational version 2 profile. Local generation,
clock gates, and publication are implemented. Before apps rely on this flow,
implement application-level lifecycle and trust evaluation. Test one witness, multiple witnesses,
duplicate hosting, missing authorization, invalid signatures, mismatched subject
signatures, expiry, delayed publication, backfill, and partial relay failure.

The [operator runbook](witness-operator-runbook.md) covers the authorization
preparation that is available now. No changes to an OpenETR application are
implemented by this guide.
