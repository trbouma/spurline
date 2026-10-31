# Operating Automatic Witnessing

Spurline can issue experimental kind 1418 observation receipts for independently
verified kind 1415 and 1416 events. This is opt-in and currently SQLite-only.
Receipts are published to the local relay and its live subscribers. External
receipt fan-out and historical backfill are not implemented.

## Enable the worker

First complete [commissioning and witness authorization](witness-operator-runbook.md).
Publish the signed evidence and make the exact approved policy bytes available
to relying parties. Authorization does not enable the worker on its own.

Configure:

```dotenv
SPURLINE_WITNESS_ENABLED=true
SPURLINE_WITNESS_CLOCK_FILE=/run/spurline-clock/health.json
SPURLINE_WITNESS_QUEUE_LIMIT=1000
SPURLINE_WITNESS_MAX_DELAY_SECONDS=60
```

Restart Spurline. For containers, explicitly mount the clock monitor's directory
read-only at `/run/spurline-clock` using a Compose override. Mount the directory,
not an individual file: the monitor must replace the file atomically. The monitor
must measure the same host clock used by Spurline. Keep one application worker
per instance; multi-process live subscription delivery is not supported.

## Clock monitor contract

Supply a trusted host time-monitor adapter which atomically writes this JSON:

```json
{"synchronized":true,"checked_at_ms":1793443200000,"uncertainty_ms":100}
```

The timestamp above is illustrative, not a usable health file. No automatic NTP
adapter is bundled. Do not periodically write `synchronized: true` without
checking a real synchronization source and deriving a conservative uncertainty.
The adapter must declare a bound that covers the host clock throughout the
30-second freshness window, including holdover drift. Operators must ensure
these runtime limits conform to the signed policy; free-form policy prose is
not machine-enforced.

The worker requires an integer check timestamp no more than 30 seconds old and
not in the future, a Boolean true synchronization flag, and an integer uncertainty
between 0 and 1000 milliseconds. Missing, malformed, stale, or unhealthy input
prevents witnessing. A wall-clock/monotonic-clock divergence greater than 250 ms
latches a failure until restart; correct the clock before restarting. This
detects discontinuities during the process lifetime, not dishonest monitoring
or clock changes while the service is stopped. The file and monitor are trusted
operator infrastructure; restrict write access accordingly.

## Submission and recovery

Eligible signatures are checked even if ordinary relay signature checks are
disabled. The subject and original observation job commit in one transaction.
The signing worker rechecks current authorization, suspension, clock health,
permission-window boundaries and the issuance deadline. Administrative changes
serialize with the issuance transaction. Renewal does not silently rebind an old
job to a new grant. Expiry, revocation, suspension or lost clock health makes a
pending job unavailable rather than inventing a later observation time.

The signed receipt, job completion and local broadcast outbox commit together.
After a crash, pending jobs retain their original observation time and committed
receipts are reused byte-for-byte. Broadcast is best-effort, at-least-once;
clients may receive duplicates and must deduplicate by event ID. Disconnected
clients use normal `REQ` discovery. Queue saturation accepts ordinary events but
records unavailable witnessing; the queue limit bounds pending signing work,
not total database size. Apply deployment-level connection/message limits too.

The observation commits to both the subject ID and its exact signature. A
different valid signature for the same ID can therefore have a separate receipt.
Receipts never trigger receipts. No OpenETR semantic validation is asserted:
the claim is observation of an event with a valid ID and signature.

## Inspect results

An ordinary Nostr `OK` confirms event storage, **not receipt issuance**.
`/info` reports whether automatic witnessing is configured, separately from
authorization. `receipt_issuance_enabled` is a configuration flag, not clock
health or a guarantee of receipt delivery.

Use `spurline.receipts.signed_event_digest(subject)` to calculate the lookup key:

```text
GET /v1/witness-status/{signed_event_digest}
```

States are `disabled`, `not-observed`, `pending`, `issued`, or `unavailable`.
`issued` includes `receipt_event_id`. `not-observed` means no durable observation
job exists, including when authorization or clock health prevented acquisition;
it does not prove the subject was absent. Invalid digests return `invalid-digest`.
Terminal unavailable jobs are retained and retries do not replace their history.

Discover receipts independently using ordinary Nostr queries:

```json
["REQ","witnesses",{"kinds":[1418],"#e":["SUBJECT_EVENT_ID"]}]
```

Verify the receipt and exact subject binding, then separately evaluate the
commissioning chain, full authorization lifecycle, policy and recognized
operator. Finding a receipt does not make its timestamp trusted or satisfy
OpenETR's core ruleset automatically.

Back up both SQLite databases and the identity sentinel consistently. Stopping
the worker does not undo published receipts. Normal relay deletion semantics
have not changed; append-only evidence retention remains a separate policy.
