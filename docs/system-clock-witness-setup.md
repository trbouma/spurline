# Simple System Clock Witnessing

Use `system` mode for Python system time with unspecified accuracy. No clock
monitor, health file, extra volume, systemd service, or NTP configuration change
is needed. Existing host NTP can continue normally, but Spurline does not check
it or claim synchronization. Witnessing remains disabled by default, and existing
deployments do not switch modes automatically.

## Configure without enabling yet

In the relay's `.env`:

```dotenv
SPURLINE_WITNESS_ENABLED=false
SPURLINE_WITNESS_CLOCK_MODE=system
```

`SPURLINE_WITNESS_CLOCK_FILE` is ignored in system mode. Use the normal Compose
file. If you added `deploy/compose.clock.yaml` to `COMPOSE_FILE`, remove only that
overlay while preserving other custom files. If you installed the optional
monitor, you can stop it without changing host NTP:

```bash
sudo systemctl disable --now spurline-clock-monitor.timer
sudo systemctl stop spurline-clock-monitor.service
```

Skip those commands if you never installed it. They leave installed files in
place. Recreate the relay after removing a monitor bind mount.

## Approve the system clock policy

Your existing service commissioning remains valid. Review
[System Clock Witness Policy Version 1](policies/system-clock-witness-v1.md).
On the relay host, copy its exact bytes into the existing data directory. For
the `/mnt/bitcoin/spurline` deployment:

```bash
sudo install -m 0644 docs/policies/system-clock-witness-v1.md /mnt/bitcoin/spurline/witness-policy.txt
docker compose exec -T spurline spurline service show > commissioning-state.json
docker compose exec -T spurline spurline service witness request \
  --policy /data/witness-policy.txt --valid-for 2592000 \
  --kind 1415 --kind 1416 > witness-request.json
```

Adjust the host path to your actual `SPURLINE_DATA_DIR`. Copy the two JSON files
and exact policy to the trusted operator workstation. From its updated Spurline
checkout, sign using the independently confirmed relay identity:

```bash
poetry run spurline operator sign-witness \
  --file witness-request.json \
  --commissioning-file commissioning-state.json \
  --policy witness-policy.txt \
  --service-npub EXPECTED_SERVICE_NPUB_OR_HEX > witness-authorization.json
```

The operator key is prompted privately. Copy the successful signed output back
to the relay host and import it:

```bash
docker compose exec -T spurline spurline service witness authorize < witness-authorization.json
docker compose exec -T spurline spurline service witness verify
docker compose exec -T spurline spurline service publish --relay ws://127.0.0.1:8080
docker compose exec -T spurline spurline service witness publish --relay ws://127.0.0.1:8080
```

These commands assume no previous witness grant. Existing grants need the
lifecycle renewal process, not deletion of history. The offline signer currently
supports initial grants only. A pending unsigned request can be replaced before
approval using the intended policy.

The exact policy line `Spurline-Clock-Profile: system-v1` permits system mode.
Other clock-policy markers cannot be combined with it. Changing the mode alone
cannot weaken an approved monitored policy. The policy's 60-second maximum
issuance delay remains enforced; its prose still requires human review.

## Enable and check

Set `SPURLINE_WITNESS_ENABLED=true`, keeping `SPURLINE_WITNESS_CLOCK_MODE=system`,
then rebuild/recreate the relay. `/info` reports `clock_mode: "system"`,
`receipt_version: 3`, and `clock_health_required: false`. That last field means
no external health file is required, not that clock-jump checks are disabled.

Submit a fresh signed kind 1415 or 1416 test event and query kind 1418 by the
subject's `e` tag. Expect schema version 3 and:

```json
{"clock_basis":"system-clock","clock_accuracy":"unspecified","clock_uncertainty_ms":null}
```

Version 3 retains the version 2 fields and checks except for `schema_version: 3`,
basis `system-clock`, and tag `["t","spurline-observation-receipt-v3"]`.
The verifier requires these exact values and rejects an NTP basis in v3.
Versions 1 and 2 are unchanged. Old clients must reject unsupported versions
rather than assume monitored time.

Signatures authenticate the relay's statement, not clock correctness. Accuracy,
UTC deadlines and cross-relay ordering remain unverified. Authorization,
suspension, receipt deduplication, restart recovery and clock-jump detection
remain active. No new database migration is required. Mode changes never
rewrite old receipts or silently convert pending jobs.
