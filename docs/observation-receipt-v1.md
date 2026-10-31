# Observation Receipt Profile Version 1

Frozen experimental wire profile, 31 October 2026. **Kind 1418** is selected
locally for receipts; it is not an assigned NIP or a registry reservation.
Automatic local issuance is opt-in; see [operation](automatic-witness-operation.md).
`spurline.receipts.verify_receipt`
implements wire, signature, and subject-binding checks only, not witness trust.

## Kind selection

The [Nostr kind registry](https://github.com/nostr-protocol/registry-of-kinds/blob/master/schema.yaml)
was checked on 31 October 2026; it contained no entry for 1418. The number is in
the regular-event range described by [NIP-01](https://github.com/nostr-protocol/nips/blob/master/01.md).
Absence from a registry does not prove global non-use. Kind 1417 was rejected
because OpenETR already proposes it for linked evidence. Do not interpret any
kind-1418 event as a receipt without the schema and binding checks below.

## Envelope and exact tags

Use a standard classical Nostr event signed by the witness key, with kind 1418.
The outer event ID and signature must verify. The exact tag array, in order, is:

```text
[["e", SUBJECT_EVENT_ID],
 ["p", SUBJECT_AUTHOR_HEX],
 ["k", SUBJECT_KIND_DECIMAL],
 ["t", "spurline-observation-receipt-v1"]]
```

No duplicate, extra, or role-marker tag elements are permitted in version 1.
The earlier design's fourth-position `observed-event` and `observed-author`
markers are dropped; purpose comes from the receipt schema. Subject kinds are
1415 and 1416 only. Both event IDs and signatures must be verified independently.

## Content

Content is a JSON object encoded as a string with lexicographically sorted keys,
compact separators, and no extra whitespace. All version-1 string values are
ASCII constants or lowercase hex, so Unicode normalization is not involved.
No unknown or duplicate fields are accepted. The complete field set is:

| Field | Constraint |
| --- | --- |
| `schema` | `org.spurline.observation-receipt` |
| `schema_version` | Integer 1, not boolean |
| `subject_profile` | `nostr-schnorr-secp256k1-v1` |
| `event_id` | Exact subject ID |
| `signed_event_digest` | Commitment below |
| `observed_at_ms` | Nonnegative UTC Unix milliseconds |
| `issued_at_ms` | Nonnegative UTC Unix milliseconds, at least observation time |
| `clock_uncertainty_ms` | Nonnegative integer uncertainty bound |
| `validation` | `event-id-and-signature` |
| `observation_mode` | `live` or `backfill` |
| `witness_policy_digest` | SHA-256 digest, 64 lowercase hex characters |
| `authorization_event_id` | Exact grant event ID, 64 lowercase hex characters |

All numeric content fields must be integers, not booleans or floats, at most
`2^53 - 1`. The sum of observation time and uncertainty must also fit that range.
Outer `created_at` is the integer floor of `issued_at_ms / 1000`.

The commitment is lowercase hex of:

```text
SHA256(ASCII("spurline.observed-signed-event.v1") || 0x00 ||
       decode_hex(subject.id) || decode_hex(subject.sig))
```

The decoded ID is exactly 32 bytes and signature exactly 64 bytes. A different
valid signature for the same event ID yields a different signed-subject
commitment and cannot reuse this receipt. This profile does not support PQ
subjects or signatures. Algorithm extensions require a separately versioned
profile, never silent fallback.

## Discovery and trust

```json
["REQ", "witnesses", {
  "kinds": [1418],
  "#e": ["<subject event id>"],
  "#t": ["spurline-observation-receipt-v1"],
  "limit": 100
}]
```

`verify_receipt` returns the decoded body after structural and cryptographic
checks. A caller must still retrieve and verify the exact authorization, its
complete known lifecycle, commissioning evidence, and policy bytes; assess the
scope, observation/issuance permission window, allowed clock uncertainty and
delay; and decide whether it recognizes the commissioning authority. It must
report missing evidence and conflicts. A valid wire record is not an accepted
timestamp, and a placeholder authority ID in a test fixture proves no authority.

## Interoperability fixture and compatibility

`tests/fixtures/observation-receipt-v1.json` contains a signed subject and signed
receipt for offline cryptographic checks. It uses public test keys and dummy
authority references. Its subject is not a qualifying OpenETR anchor: it tests
wire binding, not OpenETR rules or witness recognition. Tests also cover an
alternative valid subject signature, duplicate tags, and invalid times and fields.

The frozen profile supplies a stable experimental contract. Breaking changes
require a new schema/profile version and explicit migration. Registry conflicts
discovered later require coordinated kind migration; do not silently reinterpret
old signed receipts. The local receipt worker and clock-health gate are implemented;
an application trust evaluator and external receipt fan-out remain separate work.
