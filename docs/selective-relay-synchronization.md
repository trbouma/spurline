---
title: Selective Relay Synchronization
description: A design for selective NIP-77 synchronization between Spurline relays and compatible peers.
---

# Selective Relay Synchronization

## Status

This document describes a proposed synchronization architecture for Spurline.
It is a design direction, not a claim that NIP-77 or automatic peer
synchronization is implemented in the current release.

## Purpose

Spurline is a local-first relay. It should preserve the events that matter to a
person, application, organization, or community without mirroring the entire
public Nostr network.

Selective relay synchronization allows two Spurline instances, or Spurline and
another compatible relay, to compare relevant event sets and transfer only
what is missing. This supports:

- reconnecting after an internet or satellite outage;
- synchronization between local and hosted relays;
- movement of events across a community mesh;
- migration or replacement of a relay;
- selective preservation of Acorn wallet and record events; and
- efficient convergence over constrained links.

The goal is eventual convergence for configured event sets, not transparent
federation of every event accepted by every peer.

## Protocol foundation

Spurline should implement
[NIP-77 Negentropy Syncing](https://github.com/nostr-protocol/nips/blob/master/77.md)
and remain interoperable with compatible implementations such as
[strfry](https://github.com/hoytech/strfry).

Negentropy performs range-based set reconciliation. Each participant builds an
ordered collection of matching events using:

```text
(created_at, event_id)
```

The participants exchange compact range fingerprints until the initiator
learns:

- event IDs it has and the peer needs; and
- event IDs the peer has and it needs.

NIP-77 deliberately does not transfer event bodies. Missing events continue to
move through ordinary Nostr messages:

```text
REQ     fetch events from the peer
EVENT   offer events to the peer
```

This distinction is important. Synchronized events must pass through
Spurline's normal event-ID, signature, policy, deduplication, and persistence
path. Synchronization is not a privileged write channel.

## Design principles

### Selective by default

A peer relationship does not imply full mirroring. Every synchronization job
has an explicit NIP-01 filter and direction.

### Events remain authoritative evidence

Spurline synchronizes signed events. It does not reinterpret encrypted content
or invent application-level conflict resolution. Applications decide how
several valid events relate to one another.

### Peers are not automatically trusted

Every received event is validated as if it came from an ordinary relay client.
A peer can provide availability without becoming an authority.

### Reconciliation is restartable

Interrupted sessions restart by comparing event sets again. Correctness must
not depend on a single timestamp cursor or an uninterrupted connection.

### Local operation does not depend on synchronization

Spurline continues serving its local database while peers are unavailable.
Synchronization is a continuity feature, not a prerequisite for local reads or
writes.

## Architecture

```text
configured peer policy
        |
        v
peer scheduler -----> connection and backoff
        |
        v
NIP-77 reconciliation session
        |
        +---- have IDs ----> EVENT upload through normal ingestion
        |
        +---- need IDs ----> REQ download through normal ingestion
        |
        v
SQLite event store
```

The implementation should retain clear component boundaries:

```text
spurline.store       filtered ordered event inventory and event lookup
spurline.negentropy  NIP-77 session and wire-protocol state
spurline.peers       peer configuration, scheduling, policy, and status
spurline.main        inbound WebSocket message routing
spurline.cli         manual sync and status commands
```

The exact module names may change, but reconciliation, peer policy, and event
storage should not collapse into one subsystem.

## Peer policy

A peer configuration should identify:

- stable peer name;
- WebSocket relay URL;
- synchronization direction;
- one or more explicit NIP-01 filters;
- schedule or manual-only behavior;
- connection and frame limits;
- authentication policy, when required;
- retry and backoff policy; and
- enabled or disabled state.

An illustrative configuration is:

```yaml
peers:
  - name: community-relay
    url: wss://relay.community.example
    direction: both
    interval_seconds: 300
    filters:
      - authors:
          - "<acorn-pubkey-hex>"
        kinds: [0, 5, 37375, 37376, 7375, 7377]
      - "#p":
          - "<acorn-pubkey-hex>"
        kinds: [1059, 7378]
```

This format is conceptual. Configuration syntax should be finalized together
with validation, secret handling, and compatibility tests.

### Direction

Supported directions should be:

```text
pull    download events the local Spurline lacks
push    upload events the peer lacks
both    converge both event sets
```

Direction applies after set reconciliation. A pull-only job may discover IDs
the peer lacks but must not upload them.

## Acorn-oriented synchronization

Spurline must remain application-neutral, but Acorn provides an important
selective-sync profile.

Wallet-authored events may include:

```text
0       public profile
5       deletion requests
37375   encrypted wallet configuration and private records
37376   related encrypted record state, where used
7375    encrypted Cashu proof state
7377    transaction history
```

Incoming events may require recipient filters:

```text
1059    NIP-59 gift-wrapped delivery
7378    Acorn ecash transfer event
```

Author filters and `#p` recipient filters serve different purposes. An
author-only synchronization policy can preserve outbound wallet state while
missing incoming transfers or messages addressed to that wallet.

Deletion events must travel with the events they affect. Copying kind `7375`
without relevant kind `5` events can make historical spent-proof events appear
current on another relay. Spurline preserves events; Acorn and the Cashu mint
remain responsible for interpreting current wallet and spend state.

## Inbound NIP-77 responder

Spurline should support the NIP-77 WebSocket messages:

```json
["NEG-OPEN", "sync-1", {"authors": ["..."]}, "<hex-message>"]
["NEG-MSG", "sync-1", "<hex-message>"]
["NEG-CLOSE", "sync-1"]
```

Errors should use:

```json
["NEG-ERR", "sync-1", "blocked: synchronization filter is too broad"]
```

Negentropy subscription IDs occupy a separate namespace from ordinary `REQ`
subscription IDs. Opening an existing Negentropy ID replaces its prior
session. Sessions are connection-scoped and must be released on close,
disconnect, timeout, or protocol error.

The responder should:

1. validate the message shape, filter, payload encoding, and protocol version;
2. enforce synchronization policy and resource limits;
3. retrieve matching `(created_at, event_id)` rows in deterministic order;
4. create bounded reconciliation state;
5. return `NEG-MSG` responses until reconciliation completes; and
6. discard session state promptly after completion or failure.

## Outbound peer worker

The outbound worker acts as the NIP-77 initiator:

1. connect to the peer;
2. confirm or attempt NIP-77 support;
3. build the local inventory for one configured filter;
4. send `NEG-OPEN`;
5. exchange `NEG-MSG` frames;
6. collect `have` and `need` event IDs;
7. transfer allowed events with ordinary `EVENT` and `REQ` messages;
8. verify acknowledgements and local persistence;
9. send `NEG-CLOSE`; and
10. record a non-sensitive session summary.

Each filter should reconcile independently. A failure in one filter must not
silently mark the entire peer as synchronized.

## Storage requirements

The current SQLite store should gain interfaces for:

- ordered iteration of matching `(created_at, event_id)` pairs;
- exact lookup by event ID;
- bounded event-ID batches;
- efficient author, kind, time, and tag filtering; and
- a stable read snapshot for the duration of inventory construction.

The NIP-77 inventory must use the same filtering semantics as ordinary `REQ`
queries. A mismatch would allow reconciliation to report convergence while the
relay API returns a different event set.

Indexes should be measured against realistic Acorn and community workloads
before adding broad schema complexity. Raspberry Pi and FreeBSD operation
remain first-class constraints.

## Synchronization state

Durable peer status may include:

```text
peer name and URL
filter identifier
last attempt and last successful completion
events uploaded and downloaded
bytes sent and received
duration
last protocol or policy error
consecutive failures and next retry time
```

It must not contain private event content, decrypted records, signing keys, or
authentication secrets.

Negentropy itself does not require a durable cursor. Status supports operations
and scheduling; correctness comes from comparing event sets again.

## Resource and security controls

Spurline is intended to run on modest local hardware. Synchronization requires
explicit limits:

- maximum matching events per filter;
- maximum concurrent sessions per connection and globally;
- maximum frame and payload size;
- maximum event IDs transferred per batch;
- session idle and total timeouts;
- bounded outbound queues;
- exponential backoff with jitter;
- peer allowlists or authentication where deployment policy requires them;
- restrictions on unrestricted or excessively old filters; and
- metrics that do not expose event contents or sensitive identifiers.

Malformed Negentropy payloads, unsupported protocol versions, invalid filters,
and resource-limit violations must close only the affected session where
possible. They must not terminate the relay process.

## Mesh behavior

Spurline instances may form a graph rather than a single source-target pair.
Event IDs make ordinary loops naturally idempotent: receiving the same signed
event through several peers does not create new records.

However, mesh operation still needs policy:

- peers may have different filters;
- deletion events may arrive later than referenced events;
- a partition may produce several valid application events;
- peer clocks may differ; and
- an adversarial peer may repeatedly advertise unwanted differences.

Spurline should converge configured event sets without attempting to select an
application-level winner. Where applications require canonical state, that
decision remains with the application protocol and its authorities.

## Failure behavior

Expected failures include:

- peer unavailable or intermittently connected;
- peer does not support NIP-77;
- authentication required;
- filter rejected as too broad;
- reconciliation session expires;
- event transfer succeeds only partially;
- peer acknowledges an event but later does not return it; and
- local storage becomes unavailable.

The safe response is to retain local events, record the failure, back off, and
reconcile again later. A failed synchronization must never delete local events
or report convergence from a partial transfer.

## Operator interface

The first operator-facing commands could be:

```bash
poetry run spurline sync --peer community-relay
poetry run spurline sync --peer community-relay --dry-run
poetry run spurline sync-status
```

`--dry-run` should reconcile and report differences without transferring event
bodies. Status output should distinguish:

```text
connected
reconciling
transferring
converged
backing-off
blocked
failed
```

HTTP health should remain about local relay readiness. Peer degradation belongs
in a separate synchronization status surface so an unreachable optional peer
does not make the local relay unhealthy.

## Implementation stages

### Stage 1: Storage inventory

- define normalized synchronization filters;
- add deterministic ordered event inventory;
- add exact event lookup and bounded batches;
- test identical timestamps and lexical ID ordering; and
- prove inventory and `REQ` filtering return the same set.

### Stage 2: NIP-77 responder

- select a maintained reference-compatible Negentropy implementation or
  binding;
- implement `NEG-OPEN`, `NEG-MSG`, `NEG-CLOSE`, and `NEG-ERR`;
- enforce session and filter limits; and
- validate against official protocol vectors.

### Stage 3: Manual outbound synchronization

- implement one-shot pull, push, and bidirectional sync;
- transfer differences through `REQ` and `EVENT`;
- add dry-run and status output; and
- test Spurline-to-Spurline convergence.

### Stage 4: Interoperability

- run Spurline as NIP-77 client against strfry;
- run strfry or another compatible client against Spurline;
- test empty, identical, disjoint, and partially overlapping event sets;
- test equal timestamps, deletions, duplicates, and interrupted sessions; and
- publish an interoperability ledger.

### Stage 5: Scheduled peers and mesh operation

- add validated peer configuration;
- add scheduling, bounded concurrency, and backoff;
- expose operational metrics and status;
- test constrained and intermittent links; and
- document FreeBSD service operation and recovery.

## Library decision

The reconciliation algorithm should not be casually reimplemented. Spurline
should prefer a maintained Negentropy implementation with published protocol
vectors and compatible wire behavior.

If no suitable Python implementation exists, the project should evaluate:

1. a small binding to the reference implementation;
2. a separately packaged Python implementation developed against the official
   vectors; or
3. a temporary external synchronization helper with a stable process boundary.

Whichever path is chosen must work on FreeBSD and Raspberry Pi, avoid making a
network service depend on an opaque untested binary, and remain replaceable
behind a narrow reconciliation interface.

## Acceptance criteria

The first synchronization milestone is complete when:

- two Spurline instances converge a configured filtered event set;
- repeated synchronization transfers no event bodies when already converged;
- both directions work independently and together;
- every transferred event passes normal validation and storage;
- deletion events can be included with application events;
- interrupted sessions resume through fresh reconciliation;
- broad or excessive filters fail with bounded `NEG-ERR` responses;
- local relay operation remains available while peers are offline; and
- at least one strfry interoperability scenario passes in each direction.

## Non-goals for the first milestone

The first implementation does not need:

- automatic discovery of arbitrary peers;
- unrestricted public-relay mirroring;
- application-level conflict resolution;
- consensus or leader election;
- deletion of local events because a peer lacks them;
- synchronization of Grove blob bodies; or
- Lockbox-wide orchestration.

Grove blob synchronization, higher-level community policy, and appliance
coordination may build on this foundation later, but they should not complicate
Spurline's first interoperable event-sync implementation.

## References

- [NIP-77 Negentropy Syncing](https://github.com/nostr-protocol/nips/blob/master/77.md)
- [Negentropy reference implementation](https://github.com/hoytech/negentropy)
- [strfry Negentropy documentation](https://github.com/hoytech/strfry/blob/master/docs/negentropy.md)

