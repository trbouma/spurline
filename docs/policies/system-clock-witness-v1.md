# Spurline System Clock Witness Policy Version 1

Spurline-Clock-Profile: system-v1

## Authority and observation

The policy owner is the operator identified by the relay's verified commissioning
and witness authorization. This policy takes effect only when that operator
signs a grant containing the digest of these exact policy bytes. The grant names
the service key, allowed kinds and validity interval.

The relay may observe complete signed Nostr kind 1415 and 1416 events. It verifies
the event ID and signature and binds its receipt to both. A receipt means the
relay reports observing that signed assertion; it does not certify its content,
legal status, or consequential validity under OpenETR.

## System time only

Observation and issuance timestamps come from the relay's system clock through
Python's `time.time()`. No external clock monitor or synchronization check is
required. Host NTP may run independently, but this policy makes no claim that
NTP is enabled, synchronized, or accurate.

Version 3 receipts use `clock_basis: "system-clock"`,
`clock_accuracy: "unspecified"`, and `clock_uncertainty_ms: null`.
Null does not mean zero error. Millisecond encoding does not promise millisecond
accuracy. A signature authenticates the relay's statement, not its clock.
The receipt cannot alone establish a strict UTC deadline, exact original
creation time, or authoritative ordering across relays.

The relay checks for wall-clock versus monotonic-clock discontinuities greater
than 250 milliseconds during its process lifetime. Detection blocks acquisition
and issuance until the clock is investigated and the relay restarted.
This alarm is not an accuracy bound and does not detect every clock problem,
gradual drift, manipulation, or changes during downtime. An inaccurate but
steadily advancing clock may still produce receipts. The operator remains
responsible for host time and for suspending witnessing when it is unreliable.

## Processing and authority

Current witness authorization and absence of local suspension are required at
acquisition and issuance. Grant windows and the maximum 60-second issuance delay
are checked against local time, without a guaranteed UTC error interval.
Authorization changes and suspension serialize with local receipt issuance.
Pending jobs retain their original observation time; changing policies or clock
modes does not silently rewrite them. No backdating or historical backfill is
promised. Queue limits and failed checks can prevent a receipt even when the
underlying event is accepted. Ordinary event acceptance is not a receipt promise.

## Publication, retention and reliance

Receipts are durably stored locally before delivery to subscribers. Retrying
delivery reuses the committed receipt. The operator makes the commissioning
chain, witness authorization, and exact policy bytes available for verification.
External replication, complete discovery and permanent retention are not
guaranteed. Normal deletion rules, administrative removal, outages, and data
loss can affect availability. Operators may remove material for legal, privacy,
security or operational reasons; absence is not proof of nonexistence.

The operator protects signing keys and retained evidence, maintains backups,
and suspends witnessing when compromise is suspected. It communicates incidents
and applicable revocation evidence through established operational channels;
no universal notification or response-time guarantee is made.

Relying parties independently verify the exact subject binding, signatures,
policy digest, known authorization lifecycle, and whether they recognize the
commissioning operator. They should retain portable evidence copies. Applications
requiring bounded UTC accuracy must treat this time assurance as insufficient.
These receipts supplement, and do not replace, OpenETR validation rules.
