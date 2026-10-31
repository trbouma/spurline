---
title: Optional Post Quantum Anchor Events
description: Proposed Stroma-backed validation of identity and attestation anchors in Spurline.
---

# Optional Post Quantum Anchor Events

## Status and purpose

Design proposal following a read-only implementation review on 2026-10-31,
at Spurline revision `237e057c678e8a91f57051f6f25d0e1830c8cd9b`.
No runtime code, dependencies, databases or deployment configuration were changed
for this review. PQ event acceptance is **not implemented in Spurline**.

The intended use is durable signed evidence: identity anchors, key bindings and
attestations, rather than replacing all ordinary Nostr traffic. Recommend an
opt-in ML-DSA-44 event validator backed by Stroma, with append-only anchor history
and explicit application rules for trust, supersession, revocation and recovery.
Low expected traffic is not a substitute for abuse controls.

ML-DSA supplies signatures, not encryption. A valid signature establishes that a
statement was signed under a key; it does not establish the subject's real-world
identity, the issuer's authority, or the truth of an attestation. See
[FIPS 204](https://csrc.nist.gov/pubs/fips/204/final). Using its algorithms is not
FIPS module validation or certification of this system.

## What the current implementation permits

| Component | Observed behavior | Consequence for PQ anchors |
| --- | --- | --- |
| `events.py` | Requires 32-byte public keys and 64-byte signatures, recomputes the event ID, verifies with coincurve | Keep canonical ID checking; add explicit ML-DSA dispatch, not a generic long-key fallback |
| `main.py` | Validates synchronously in the async request handler before storage | PQ work needs bounded off-thread execution and admission control |
| `config.py` | Allows signature verification to be disabled | PQ-enabled anchor mode must refuse disabled verification |
| `store.py` | SQLite keys/signatures are unrestricted TEXT; full event JSON is retained | No obvious column-width migration, but larger indexes and query plans need measurement |
| `store.py`, `filters.py` | Only 64-character authors use the exact-key path; other lengths count as prefixes | Recognize complete 2,624-character ML-DSA keys and keep DB/live-filter behavior aligned |
| `store.py` | Same-author kind-5 tombstones hide events from queries, including deletion-before-arrival | Anchor retention needs an explicit policy; deleting evidence is not revoking a claim |
| `store.py` | Events are stored by ID; no replaceable-event selection was found | Do not assume a latest-identity record or silently assign standard replacement semantics |
| `main.py` | Handles EVENT, REQ, CLOSE; advertises NIP-01 and no required authentication | No NIP-42/PQ authentication support should be inferred |
| `identity.py` | Service identity is classical nsec/npub with a persistent binding sentinel | Keep operator/service identity separate from PQ anchor authors |
| `pyproject.toml` | Already depends on Stroma's main branch, without PQ extras | Add explicit opt-in packaging and tested commit pins later |
| `storage.py` | Async protocol isolates SQLite operations using threads | Preserve that boundary; do not put signature policy inside SQLite |

The 4,096-character filter-string ceiling admits a full ML-DSA-44 public key,
but the current prefix-count rule misclassifies it. SQL treats a 64-character
author as exact while live matching treats every author value as a prefix; with
longer keys that distinction could produce inconsistent historical/live results.
Both paths need one documented key-aware matching rule.

No application-level event byte cap, subscription count cap or verification queue
limit was found in the reviewed request path. Server/proxy defaults are not a
sufficient anchor resource policy. Existing validation also accepts Python bools
as integers and does not consistently enforce storage-range bounds; strict PQ
parsing must address these cases before native calls.

## Wire profile and compatibility

Standard [NIP-01](https://github.com/nostr-protocol/nips/blob/master/01.md) uses
secp256k1 keys and signatures. An ML-DSA public key in the outer `pubkey` field
is a **nonstandard event extension**, even if it uses the familiar JSON fields.
It must not be advertised as a new supported NIP.

For a first interoperability prototype, match pqrelay exactly:

- ML-DSA-44 public key: 1,312 bytes, encoded as 2,624 lowercase hex characters.
- Signature: 2,420 bytes, encoded as 4,840 lowercase hex characters.
- Event ID: SHA-256 of the canonical `[0, pubkey, created_at, kind, tags, content]`.
- Signature input: the 32 decoded event-ID bytes, using ordinary randomized
  ML-DSA-44 with an empty context. This is not HashML-DSA prehash mode.
- Verify field types, sizes and event ID before calling Stroma. Reject Falcon,
  unexpected lengths, malformed hex and unsupported profiles without fallback.

The PQ key and signature alone occupy 7,464 ASCII bytes, excluding JSON framing,
content and tags. Transport limits must accommodate this overhead explicitly.

This digest-signing profile inherits SHA-256's security properties as well as
ML-DSA's. Do not equate the resulting protocol's security with the signature
primitive alone. Before durable production identity use, review whether to retain
this compatibility profile or adopt a distinct versioned, domain-separated
transcript. A change must be explicit and jointly implemented in clients and
relays, never guessed by trying several verifiers.

For anchor use, propose a signed profile marker in tags and operator-configured
allowed kinds. No kind numbers or marker syntax are assigned by this note.
Bare pqrelay demo events would remain an interoperability test, not automatically
qualify as identity anchors. Freeze the application schema and permitted kinds
before enabling anchor admission. Do not overload kind 0 or a replaceable range
merely to resemble a profile.

Stroma's standard query client verifies classical events and rejects these PQ
events. PQ-aware consumers need an explicit adapter, as pqrelay does. Ordinary
relays, key encodings such as npub, and classical authentication must not be
assumed to understand the new format. Never truncate a PQ key into a classical
identifier. A versioned fingerprint can aid discovery but does not replace the
full key or establish trust in it.

## Identity and attestation model

The signed application payload should bind a schema version, statement type,
subject identifier, issuer key/anchor reference, scope, applicable validity
period, and any referenced artifact's digest and digest algorithm. Distinguish
an identity's self-asserted anchor from an independent issuer's attestation.
Specify canonical payload encoding if consumers compare payload digests.

Prefer minimal public claims and content digests over personal data. Hashes of
predictable personal information can still enable correlation or guessing.
An artifact digest binds bytes, not their availability, provenance or truth.
Relays and Blossom locators are retrieval hints, not trusted validation endpoints.

Applications, not Spurline, decide:

- which issuer roots and initial key bindings they trust;
- whether a key is authorized for a particular identity, role or claim;
- validity, expiry, revocation and conflict resolution;
- required evidence completeness and how to report an unavailable history.

An attacker can generate another valid PQ key and claim the same subject. Relay
acceptance must never mean identity verification. A classical signature linking
an npub to a PQ key may assist transition today, but is not a sufficient enduring
trust root after the classical key becomes forgeable. Cross-signatures, independent
issuers and out-of-band pinning are evidence whose acceptance needs an explicit
verifier policy, not automatic equivalence between identities.

## Anchor lifecycle and walkthroughs

### Identity creation and rotation

1. An owner independently generates a PQ signing key and protects its recovery
   material. Merely deriving it from, or wrapping it only under, a vulnerable
   classical credential can undermine the intended protection.
2. The owner signs an identity anchor. A PQ-enabled Spurline validates the wire
   profile and signature, durably stores the event, then acknowledges it.
3. A relying party retrieves and independently verifies the anchor, and evaluates
   the initial binding using its configured trust evidence.
4. Rotation creates new evidence linking the old anchor to a new key. Require
   authorization by the old key and proof of possession by the new key under the
   chosen application policy; retain both statements and their references.
5. If the old key is lost or compromised, use a previously established independent
   recovery authority/policy. A relay operator or a newly presented key cannot
   unilaterally establish legitimate continuity.

Conflicting successors are evidence of a fork, not grounds to select whichever
has the newest self-reported timestamp. `created_at` is not trusted time and a
relay acknowledgement is not a trusted timestamp or a transparency-log proof.

### Attestation and revocation

1. An issuer signs an attestation referencing the subject's exact identity anchor
   and a claim or content-addressed artifact, with scope and validity conditions.
2. Spurline checks cryptographic validity and admission limits, not claim truth.
3. The consumer checks the issuer's authority, subject binding, artifact digest,
   and relevant rotation/revocation evidence independently.
4. Revocation is a new authorized signed statement referencing the attestation.
   It does not erase the original evidence or retroactively invalidate its signature.

Absence of a revocation in one relay response is not proof that none exists.
Consumers need a freshness/completeness policy and an inconclusive state when
required evidence cannot be retrieved. Multiple relays improve availability but
do not by themselves establish consensus or prevent equivocation.

## Persistence and deletion policy

See the [append-only evidence policy and proposed NIP-09 changes](append-only-evidence-policy.md)
for the broader OpenETR rationale, event-class boundaries and migration questions.
That policy applies to classical as well as PQ evidence.

Recommend an append-only *logical history* for designated anchor events, with
signed supersession/revocation records. This is not a promise of immutable physical
storage: operators can lose or remove data, and retention/privacy obligations remain.

For that profile, kind-5 deletion must not silently hide an anchor. Reject or
ignore its effect on protected evidence according to a documented policy, including
tombstones received before their targets. Keep existing classical deletion behavior
unchanged. Because the existing SQL hides events based on author and target alone,
implementing this requires both query and tombstone-policy tests, not just rejecting
deletion requests after an anchor happens to be stored.

Do not introduce latest-only replacement semantics for anchors. A separate
application projection can calculate current status while preserving the evidence
history. Keep database uniqueness and author comparisons on full keys initially;
any auxiliary digest index needs exact full-key comparison after lookup.

Existing `raw_json` storage can retain the experimental event shape, but verify
all supported backends, migrations, backup/restore and indexing with real PQ data.
Disabling PQ after storing anchors must not delete or misclassify them. Define
read-only historical retrieval and metadata behavior separately from new admission.

## Optional installation and execution

Propose PQ-disabled behavior by default. A candidate `spurline[pq]` extra must
activate the **existing** Stroma dependency's `pq` extra without making classical
installs pull PQ packages. Test resolver metadata for both modes before choosing
the packaging declaration; avoid parallel conflicting Stroma dependencies.

Candidate settings (not implemented) are `SPURLINE_PQ_ENABLED`,
`SPURLINE_PQ_LIBOQS_PATH`, and an anchor profile/kind allowlist. PQ enablement
must require verification enabled, a compatible backend, and explicit admission
policy. Missing dependencies or unsupported native versions must fail startup;
never downgrade or download at runtime.

Use the reviewed Stroma `PQBackend` adapter, presently paired with liboqs-python
0.16.0.2 and native liboqs 0.16.0. Native builds belong in a separate optional
Docker build stage/target, pinned and bounded as in pqrelay. Keep the classical
image small, retain the non-root runtime, and copy no compilers or private keys.
The relay needs public keys only; it does not need anchor-signing private keys.

ML-KEM is not used for relay signature validation. The current fixed Stroma backend
requires both algorithm families to be available; document this build dependency
without advertising encryption support. Keep the relay's classical service nsec,
npub and Mainstay identity binding unchanged in this phase.

Before accepting PQ traffic, enforce frame/event bytes before JSON/native work,
strict field/tag limits, bounded author-list bytes and query result bytes,
subscription limits and per-client/global admission budgets. Proposed starting
limits for benchmarking are 64 KiB per PQ event, two verification workers and a
queue of 16; these are hypotheses, not measured production defaults. Full PQ
keys amplify query costs even when the count of filter values is bounded.

Validate shape and ID cheaply, then acquire bounded admission before dispatching
native verification. Hold capacity until native work finishes: cancelling an
await does not stop a C call in a worker thread. Account for Stroma's serialized
native calls; a thread pool does not guarantee parallel crypto throughput.
Reject excess work visibly, drain in-flight operations during shutdown, and test
classical latency under PQ load. Do not claim a native execution timeout unless
the chosen isolation mechanism can actually enforce one.

## Discovery and rollout gates

Expose experimental profile identifiers, enabled admission kinds, signature
algorithm and size limits in a separate relay-info extension. Do not append an
invented NIP number or advertise identity certification. Public capability metadata
does not authenticate the relay operator or prove what code is running.

Recommended implementation sequence:

1. Freeze the prototype signing profile and separate anchor application schema.
2. Add an isolated Stroma-backed validator and parser tests; leave default behavior unchanged.
3. Add optional packaging/startup checks, bounded dispatch and metadata.
4. Qualify full-key filters, storage, deletion protection and historical retrieval.
5. Run pqrelay/Spurline cross-implementation tests, then an identity/attestation pilot.

Required tests include default installation without liboqs; missing/incompatible
backend; disabled-verification refusal; classical regressions; key/signature sizes;
bool/range/type rejection; modified content/tags/ID/context; PQ publish/readback/live
subscription; exact and prefix author parity; duplicate handling; protected deletion
before/after arrival; rotation forks and unauthorized revocation in application
tests; unavailable evidence; queue saturation and cancellation; restart/backup;
and Docker amd64/arm64 qualification. A negative test must confirm that a standard
Stroma query does not silently accept the nonstandard signature format.

Before production use, obtain independent cryptographic/protocol review of the
signing transcript, SHA-256 dependency, key trust/recovery model and lifecycle
rules. The successful pqrelay prototype demonstrates mechanics, not those broader
security properties.
