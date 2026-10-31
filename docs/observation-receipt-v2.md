# Operational Observation Receipt Version 2

Version 2 adds an explicit unspecified-accuracy profile to experimental kind
1418. Version 1 remains frozen and continues to require numeric uncertainty.
The separate [version 3 system-clock mode](system-clock-witness-setup.md#enable-and-check)
does not claim synchronization; it uses a distinct version and marker rather than
changing the meaning of existing v2 receipts.
This is not a registered NIP. Consumers must recognize the version explicitly;
unsupported versions must not be treated as version 1.

Version 2 retains version 1's subject commitment, canonical JSON encoding,
authorization and policy references, timestamps, validation scope, observation
mode, and exact `e`, `p`, `k` tag order. Differences are:

| Field | Required value |
| --- | --- |
| `schema_version` | `2` |
| `clock_uncertainty_ms` | JSON `null` |
| `clock_accuracy` | `"unspecified"` |
| `clock_basis` | `"ntp-synchronized-system-clock"` |
| Fourth tag | `["t", "spurline-observation-receipt-v2"]` |

No extra fields are accepted. The verifier rejects numeric uncertainty in v2,
null uncertainty in v1, mixed markers, and unsupported accuracy/basis values.
`observed_at_ms` and `issued_at_ms` remain nonnegative safe integers, observation
must not be after issuance, and outer `created_at` equals issued milliseconds
divided by 1000 and rounded down. The signed-subject digest profile is unchanged.

**Null means no numeric accuracy bound is asserted.** It is not zero, infinity,
an omitted validation step, or permission to assume an application-default
tolerance. Millisecond encoding does not promise millisecond accuracy.

The issuer claims it observed synchronization status at acquisition and issuance
under its policy. Neither the signature nor `clock_basis` independently proves
clock correctness or authentic NTP service. The local clock is used for grant
window and issuance-delay checks. Without a bound, a relying party cannot derive
a guaranteed UTC observation interval or assert strict UTC-boundary compliance.
Applications requiring bounded timestamps must reject this assurance as
insufficient. Ordering between different relays is not established by these times.

`spurline.receipts.verify_receipt` checks both versions' cryptography and wire
structure. It still does not evaluate operator recognition, complete authority
history, clock policy, or consequential OpenETR validity. A client that discovers
v2 receipts must not present them as precise timestamps. See the
[operational policy](policies/operational-witness-v1.md) and
[deployment instructions](operational-witness-setup.md).
