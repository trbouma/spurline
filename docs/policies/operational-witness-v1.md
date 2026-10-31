# Spurline Operational Witness Policy Version 1

Spurline-Clock-Profile: operational-v1

## Authority and scope

The policy owner is the operator identified by the relay's verified commissioning
attestation and witness authorization. Adopting this policy requires that
operator's signature over a request containing the digest of these exact UTF-8
bytes. The grant identifies the service public key, permitted subject kinds,
and validity period. This policy grants no authority by itself.

The service may witness complete Nostr kind 1415 and 1416 events within its
authorized scope. It independently verifies each event ID and signature and
commits to both the event ID and exact signature. Its receipt means that the
service observed that signed assertion, not that the assertion is true or
consequentially valid under OpenETR or any other ruleset.

## Operational time and unspecified accuracy

Receipts use the relay's NTP-synchronized system clock. The service makes no
numeric guarantee of accuracy relative to UTC, no sub-second accuracy promise,
and no claim of authoritative ordering across relays. Millisecond field encoding
is a representation choice, not a precision claim. Receipts do not establish
the original creation time of the subject or a strict externally verified UTC
deadline, even when a signature is authentic.

Receipts follow experimental observation-receipt schema version 2, kind 1418,
with `clock_uncertainty_ms: null`, `clock_accuracy: "unspecified"` and
`clock_basis: "ntp-synchronized-system-clock"`. Null does not mean zero. A relying
party requiring bounded accuracy must reject this time assurance as insufficient.

The deployment uses a trusted host monitor of systemd-timesyncd. Witnessing
requires active timesyncd, a positive synchronization status, and a recorded
successful synchronization no more than two hours old. The monitor refreshes
status approximately every ten seconds; the relay accepts checks no more than
30 seconds old. These are liveness thresholds, not accuracy bounds. A fresh
monitor check does not assert that a new NTP exchange occurred.

The relay stops acquiring or signing receipts when these checks fail or become
stale. Detection is not instantaneous; it is limited by the monitor cadence,
status reporting, and the two-hour last-sync threshold. Missing monitor data is
not interpreted as healthy. A detected wall-clock/monotonic-clock divergence
greater than 250 milliseconds during the relay process lifetime blocks signing
until an operator checks the clock and restarts the process. This threshold is
a discontinuity alarm, not a bound on absolute accuracy. Clock manipulation,
gradual drift, changes during downtime, dishonest monitoring, and malicious NTP
responses are not ruled out by these checks.

## Authorization and processing

Acquisition and issuance require current authorization and no local suspension.
The relay evaluates grant windows against its local clock; without a numeric
uncertainty bound it cannot guarantee that those decisions satisfy strict UTC
boundaries. Renewal or revocation does not rewrite earlier evidence. Suspension
and signed authorization changes are serialized with issuance locally.

The service retains the original observation time across retries and issues
within 60 seconds according to its local clock. It does not backdate receipts
or refresh a pending job's time to make it eligible. Queue saturation or failed
checks may prevent a receipt even when the underlying event is accepted. There
is no guarantee that every eligible event receives a receipt. A Nostr acceptance
response confirms subject storage, not issuance of a witness receipt.

## Publication and retention

Receipts are durably stored on the local relay before delivery to subscribers.
Clients can retrieve them by subject event reference. Retries reuse the exact
committed receipt. External replication and historical backfill are not promised.
The operator publishes commissioning and authorization evidence and makes this
policy available for independent verification.

No permanent or global retention guarantee is made. Normal relay deletion rules,
operator removal, outages, and data loss may affect availability. Operators may
remove material for legal, privacy, security, or operational reasons. Relying
parties should retain portable copies of the subject, receipt, policy, and
authority evidence. Failure to retrieve evidence does not prove it never existed.

## Operator responsibilities and reliance

The operator protects the service key, commissioning key, monitor, and retained
evidence; keeps backups and recovery arrangements; and suspends witnessing when
compromise or unreliable time is suspected. The operator reviews incidents and
communicates affected identities, receipts and relevant revocation evidence to
known relying parties through its established operational channels. This policy
does not promise a notification deadline or universal discovery of every holder.

Relying parties verify signatures, exact subject binding, policy digest, and the
known commissioning and witness-authorization lifecycle. They independently
decide whether to recognize the operator. Neither this policy nor a receipt
certifies content, legal status, complete history, or the absence of conflicting
evidence. Operational time is supporting evidence, not a substitute for explicit
OpenETR validation rules.
