# Operator Signing CLI

Use `spurline operator` on a trusted operator workstation to sign commissioning
attestations and initial witness authorizations. It works offline, does not load
relay configuration, and does not open the relay database or publish events.
Keep the operator private key outside the relay container.

The commands validate the signed request, require an independently confirmed
service identity, display the terms, prompt for the operator private key with
echo disabled, check that it belongs to the requested operator, and require
typing `yes`. Only the resulting signed event goes to stdout; review text and
prompts go to stderr. There is intentionally no `--nsec`, environment-key option,
or noninteractive approval flag. A real terminal is required. The key is not
stored, but Python cannot guarantee erasure of secret bytes from process memory.

## Sign commissioning

On the relay host, export the existing pending request without replacing it:

```bash
docker compose exec -T spurline spurline service show > commissioning-state.json
```

Copy this public JSON to the operator workstation. Confirm the relay's service
npub or hexadecimal public key through an independent trusted channel. From an
updated Spurline checkout with its Poetry dependencies installed:

```bash
poetry run spurline operator sign-commissioning \
  --file commissioning-state.json \
  --service-npub EXPECTED_SERVICE_NPUB_OR_HEX > attestation.json
```

The input can also be the output of `service request`, or the bare signed request.
Review the service identity, operator, management mode, request ID, and terms
before approving. The request must still be within its 24-hour window when
signing completes. A future-dated request is rejected rather than backdating a
signature. Failed or cancelled signing emits no event; shell redirection may
still leave an empty output file. Only transfer the output after a successful exit.

Copy `attestation.json` back to the relay host and import it:

```bash
docker compose exec -T spurline spurline service commission < attestation.json
docker compose exec -T spurline spurline service verify
```

## Sign an initial witness authorization

On the relay host, export the complete commissioning evidence and request a
witness grant using the exact public policy file:

```bash
docker compose exec -T spurline spurline service show > commissioning-state.json
docker compose exec -T spurline spurline service witness request \
  --policy /data/witness-policy.txt --valid-for 2592000 \
  --kind 1415 --kind 1416 > witness-request.json
```

Copy the two JSON files and exact policy bytes to the operator workstation:

```bash
poetry run spurline operator sign-witness \
  --file witness-request.json \
  --commissioning-file commissioning-state.json \
  --policy witness-policy.txt \
  --service-npub EXPECTED_SERVICE_NPUB_OR_HEX > witness-authorization.json
```

The signer verifies the complete commissioning chain, its binding to the
requested service and operator, the request's signature and expiry, allowed
kinds, validity interval, and exact policy digest. It constructs its own event
rather than signing the relay's supplied unsigned template. The full policy is
displayed as JSON-escaped text to prevent terminal control-character injection.
The operator must still judge whether the policy is adequate and achievable.

This command signs **initial grants only**. Renewal and revocation signing need
a separate lifecycle-aware review flow and are not supported by this signer.
Cryptographic verification of a supplied bundle does not prove the absence of
newer evidence or grant permission beyond the reviewed request.

Import the signed result on the relay host:

```bash
docker compose exec -T spurline spurline service witness authorize < witness-authorization.json
docker compose exec -T spurline spurline service witness verify
```

Continue with [evidence publication](witness-operator-runbook.md#import-and-publish-authorization)
and [automatic witness setup](automatic-witness-operation.md). Signing or
importing these events does not enable the automatic worker.
