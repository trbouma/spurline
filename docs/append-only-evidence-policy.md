---
title: Append Only Evidence and Nostr Deletion
description: Proposed Spurline evidence-retention policy for OpenETR and possible NIP-09 changes.
---

# Append Only Evidence and Nostr Deletion

## Status and recommendation

Design proposal, 2026-10-31. Neither the relay policy nor the protocol changes
below are implemented by this note. No NIP amendment has been submitted or adopted.

Evaluate a dedicated, configurable Spurline evidence-relay mode in which author
deletion requests cannot suppress accepted regular events. Use additional signed
evidence to express corrections, retractions, revocations and reversals. OpenETR
determines their consequential effects under explicit rules, independently of
relay deletion and replacement.

Start with an advertised deployment policy, not a universal change to Nostr.
Regular events also carry personal communications; applying evidence retention
silently to a general-purpose relay would create privacy and compatibility risks.
This policy is independent of signature algorithm and complements the
[optional PQ anchor proposal](post-quantum-anchor-events.md).

## Separate three operations

**Replacement** introduces a new signed event for the same logical key or address.
It does not edit an existing signed event. The NIP-01 replaceable/addressable
conventions permit older versions to be discarded; they are not history-preserving
archives. [NIP-01](https://github.com/nostr-protocol/nips/blob/master/01.md)

**Deletion** requests removal or suppression of referenced events. Current NIP-09
uses kind 5, references targets by `e` or `a` tags, and recommends same-author
target suppression without a regular-event exemption. It recommends retaining
deletion requests; deleting a deletion request does not undo it.
[NIP-09](https://github.com/nostr-protocol/nips/blob/master/09.md)

**Consequential state change** is an application decision derived from evidence.
Deleting an event or publishing a replacement is not, by itself, an authorized
reversal of a transfer or discharge of an obligation.

OpenETR should distinguish:

- **Authenticity:** whether the assertion was signed under the claimed key.
- **Availability and historical evidence:** whether the exact assertion can be retrieved
  and independently verified, with explicit completeness limitations.
- **Consequential validity:** what effect that assertion has under the applicable ruleset.

An authentic assertion can remain in history despite being mistaken, unauthorized,
contradicted, expired or no longer effective. Retention does not endorse its truth.

## Proposed relay policy

| Event class | Evidence-relay behavior |
| --- | --- |
| Regular | Retain accepted events without honoring author-requested suppression |
| Replaceable | Apply defined replacement and eligible deletion semantics; no promise of complete version history |
| Addressable | Apply defined address-based replacement and eligible deletion semantics; no promise of complete version history |
| Ephemeral | Do not persist; deletion is unnecessary |
| Unclassified or unsupported | Apply an explicit admission rule; do not silently classify every remaining kind as regular |

Use the existing NIP-01 classification rather than a per-event `no_delete` tag.
Publish the classification/specification revision used by the implementation;
future assignments must not silently change the retention promise for stored data.
Special cases defined by individual NIPs still require review.

Recommended policy wording:

> Within the configured evidence-relay policy, accepted regular events remain
> retrievable notwithstanding subsequent author deletion requests. Corrections,
> retractions, revocations and reversals are represented by additional signed
> evidence. Their effects are evaluated under application rules, not inferred
> from relay deletion or replacement.

“Append-only” here means a logical restriction on author-controlled protocol
operations, not physically immutable storage or guaranteed eternal availability.

### Admission and retention boundary

The operator decides which events to accept, subject to published size, resource,
identity and content policies. An append-only policy does not imply unlimited
storage or open publishing. For a dedicated evidence deployment, protect all
accepted regular events consistently; narrow the admitted kinds if necessary
rather than making undisclosed exceptions to retention.

Operators retain administrative removal powers for legal, privacy, security and
operational reasons. Such removal changes availability, not OpenETR state. Where
appropriate, record a minimal administrative audit entry without republishing the
sensitive content or implying that a signed public removal notice is mandatory.
Storage loss, outages and removal on other relays remain possible.

Advertise the mode before clients publish. Disclose any retention horizon,
capacity-based eviction and migration policy; do not market a finite or evictable
store as permanent. Changing modes must not silently apply historical tombstones
and hide previously protected evidence. Require an explicit operator migration
decision, backup and documented client impact.

### Deletion requests are evidence, not automatic retractions

A kind-5 request may itself be accepted and retained as the author's statement
about its targets. For protected regular targets, the request has no suppression
effect. OpenETR must not infer that it constitutes an effective retraction unless
the applicable ruleset explicitly assigns that effect and verifies authorization.

Evaluate each target separately in mixed-class requests. Derive its class and
author from the verified target, not solely a request's claimed `k` tag. For an
unknown target, retain a pending request if appropriate, but do not apply a blanket
tombstone: when the target arrives, classify and authorize the action first.

Acknowledging storage of the request is not confirmation that every requested
deletion occurred. Preserve normal EVENT acknowledgement meaning; consider a
separate policy/status mechanism if clients need per-target outcomes. Do not
invent a new standardized status code in this implementation.

## OpenETR representation and reconstruction

Issuance, transfer, relinquishment, discharge and other consequential assertions
should be represented by durable regular evidence events, not solely by mutable
profiles or addressable records. Mutable records can act as discovery pointers or
current-state summaries, but the evidence underlying a summary must be portable
and independently verifiable by exact event ID.

A correction or reversal should identify its target evidence, statement type,
applicable ruleset, authorized actor and scope. The ruleset determines whether it
adds context, supersedes a claim, changes prospective state or has another defined
effect. Authorization to issue the original statement does not automatically grant
unilateral authority to undo all consequences relied on by other parties.

For example, after a transfer from A to B:

1. A's subsequent deletion request does not remove the transfer from protected history.
2. A's signed assertion that the transfer was mistaken becomes additional evidence.
3. A verifier evaluates that assertion and any required counterparty/authority evidence
   under the transfer ruleset; it does not simply restore A's control.
4. If essential evidence is missing or conflicts remain unresolved, the verifier reports
   an incomplete or contested result rather than inferring a clean history.

Portable evidence packages should carry exact signed events, required artifacts,
digest algorithms and rule references. Package integrity does not prove that all
relevant evidence has been included. Multi-relay retrieval improves availability,
not completeness or consensus. Event absence never proves that an event did not
exist. Self-reported timestamps do not supply trusted ordering by themselves.

## Possible changes to NIP-09

Two routes should be evaluated separately:

1. **Specialized policy profile:** describe how an evidence relay departs from current
   deletion recommendations, and how clients discover that policy. This is the
   recommended initial route and does not require claiming universal compliance
   with a new deletion rule.
2. **Protocol amendment:** change the default eligibility rules in NIP-09 to restrict
   author-requested deletion to replaceable/addressable targets. This changes
   existing expectations and requires broader Nostr review and migration planning.

The following requirements are proposed amendment text, **not current NIP rules**:

> A relay applying event-class-restricted deletion MUST NOT remove or suppress a
> regular event solely because its author published a deletion request. Author
> deletion eligibility is limited to replaceable and addressable targets, subject
> to target-author authorization. Ephemeral events require no retained deletion
> state. Undefined event classes require explicitly specified treatment.

If adopted universally, the conditional phrase would need removal and the change
would become a new normative default. If scoped to a profile, its activation and
discovery mechanism must be specified before interoperability is claimed.

An amendment would need to address these parts of NIP-09 explicitly:

| Area | Proposed change or clarification |
| --- | --- |
| General target rule | Replace unrestricted same-author suppression guidance with class-based eligibility |
| `e` references | Check the referenced event's actual class and author; pending requests cannot preemptively suppress regular targets |
| `a` references | Preserve address/author validation and defined timestamp cutoff behavior for eligible mutable versions |
| `k` tags | Treat as classification hints, not authority to override a target's actual kind |
| Mixed targets | Apply eligibility independently; define request acceptance separately from per-target execution |
| Client rendering | Separate local hide/mute preferences from evidence retention and consequential invalidation |
| Request retention | Preserve the request as evidence and retain the existing no-undo rule for deletion of deletion requests |
| Operator powers | Explicitly distinguish author protocol requests from administrative removal and retention expiry |
| Discovery | Specify how clients learn the applied policy and limits without inventing a supported-NIP number |
| Transition | Explain old tombstones, preexisting data, mode changes and communication with legacy clients |

Keep deletion distinct from replacement: restricting NIP-09 would not make mutable
version history durable under NIP-01. If historical versions of mutable records
are also required, that is a separate archival policy or protocol proposal.

Existing clients may hide regular events as soon as they observe an authorized
deletion request, even if the relay retains them. Evidence-aware clients must
evaluate the relay policy and application rules and must not present a local hide
decision as erasure of evidence. Users should still be free to hide unwanted
content locally; the relay policy is not a command to display it.

No new wire field, kind, NIP number or relay-info schema is standardized here.
Publication of policy metadata and clear user-facing retention notices should be
prototyped before proposing a universal amendment. Retention disagreements across
relays cannot be resolved merely by changing the text of a NIP.

## Spurline implementation implications

The reviewed Spurline store records kind-5 `e` tombstones and hides targets with
matching authors. It does not currently implement complete replaceable/addressable
selection or address-based deletion. Therefore this proposal is more than a switch
that disables one SQL predicate.

Before implementation:

1. Define and test a shared event-class classifier and explicit undefined-kind behavior.
2. Add opt-in settings and discoverable policy metadata; keep ordinary deployments unchanged.
3. Apply eligibility to deletion recording, pending requests and query visibility,
   including the effect of tombstones already in the database.
4. Implement and qualify replacement/addressable behavior before advertising the full table.
5. Keep historical queries and live subscriptions consistent about visibility;
   distinguish new correction evidence from a request to erase cached copies.
6. Keep administrative removal out of the public author-deletion path; define
   whether removed IDs are blocked from reimport and how the policy is audited.
7. Apply the same validation and retention rules to synchronization, imports and
   alternate storage backends; none is a privileged bypass.

Required tests include regular-target retention; same-author and foreign-author
requests; deletion before arrival; mixed classes; false `k` hints; addressable
cutoff boundaries; replacement ordering/ties; ephemeral non-retention; request
retention; mode migration with existing tombstones; administrative removal;
backup/restore; classical/PQ parity; and reconstruction with missing or conflicting
OpenETR evidence. Validate actual OpenETR rulesets separately before claiming
their current implementations satisfy these requirements.

## Guiding principle

> Evidence may be superseded, contradicted or invalidated, but an author cannot
> retract its historical existence through relay protocol operations. Its
> consequential effect changes only under explicit rules; its continued
> availability remains a separate responsibility.

The architectural objective is independently verifiable consequential history,
not dependence on mutable relay state or a guarantee that an operator can never
remove stored bytes.
