# Operational Witness Setup

This is the optional monitored mode. For the simpler setup without host services,
use [system clock witnessing](system-clock-witness-setup.md) instead.

Use this mode for ordinary NTP-backed observations without a numeric UTC-accuracy
promise. The bundled timesyncd adapter reports synchronization status only.
The existing bounded mode and version 1 receipts are unchanged. Witnessing
remains disabled by default; do not enable it until the policy is approved and
the monitor has been checked on the actual host.

## Install the host monitor

On Beelink, from the updated Spurline checkout, install the standalone Python
file and systemd units. Only Python 3 and the existing systemd tools are needed;
the host does not need Poetry or the relay's dependencies.

```bash
sudo install -d -m 0755 /usr/local/libexec
sudo install -m 0644 src/spurline/clock_monitor.py /usr/local/libexec/spurline-clock-monitor.py
sudo install -m 0644 deploy/spurline-clock-monitor.service /etc/systemd/system/
sudo install -m 0644 deploy/spurline-clock-monitor.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now spurline-clock-monitor.timer
sudo systemctl start spurline-clock-monitor.service
cat /run/spurline-clock/health.json
```

Check for `synchronized: true`, `mode: "operational"`, `uncertainty_ms: null`,
and `reason: "ok"`. The file should refresh while the timer is active. The service
runs with a dynamic unprivileged user and atomically replaces a public, readable
status file. No keys are involved. Review failures with:

```bash
systemctl status spurline-clock-monitor.timer
journalctl -u spurline-clock-monitor.service --since '10 minutes ago'
```

The adapter reads `NTPSynchronized` and requires timesyncd to be active. It also
uses `/run/systemd/timesync/synchronized`, which systemd touches on successful
synchronization, to reject samples older than two hours. It does not use
`/var/lib/systemd/timesync/clock`, which can also be refreshed without an NTP
exchange. See [systemd-timesyncd documentation](https://www.freedesktop.org/software/systemd/man/260/systemd-timesyncd.html)
and the [machine-readable timedatectl interface](https://www.freedesktop.org/software/systemd/man/257/timedatectl.html).
The two-hour limit accommodates the reported 34-minute polling interval; it is
not a calculated uncertainty bound. No NTP configuration changes are required.

If the host does not expose the expected synchronization file or read-only D-Bus
properties, the adapter reports unhealthy. Do not substitute a static healthy
JSON file. Check the adapter on the actual Linux host before enabling issuance.

## Mount the status directory and select the mode

Add these settings to the deployment `.env`, retaining all existing settings:

```dotenv
COMPOSE_FILE=compose.yaml:deploy/compose.clock.yaml
SPURLINE_WITNESS_ENABLED=false
SPURLINE_WITNESS_CLOCK_MODE=operational
SPURLINE_WITNESS_CLOCK_FILE=/run/spurline-clock/health.json
SPURLINE_WITNESS_MAX_DELAY_SECONDS=60
```

If `COMPOSE_FILE` already lists custom files, append `deploy/compose.clock.yaml`
instead of replacing that list. The overlay mounts `/run/spurline-clock` read-only
and refuses to create an absent host directory. The mount is a directory so
atomic file replacements remain visible. Do not expose the host D-Bus socket to
the relay container. Docker must run on the same host whose clock is monitored.

Recreate the container with the overlay in effect and inspect the mounted file:

```bash
docker compose config --quiet
docker compose up -d --build --force-recreate spurline
docker compose exec -T spurline cat /run/spurline-clock/health.json
```

This does not enable witnessing. If the runtime directory is removed and recreated
while the container is running, recreate the container to refresh the bind mount.
The supplied service preserves the directory between timer runs.

## Approve the operational policy

Review [Operational Witness Policy Version 1](policies/operational-witness-v1.md).
It is ready for adoption only if the operator accepts its commitments. Copy its
exact bytes to the mounted data directory; for example, when that directory is
`/mnt/bitcoin/spurline`:

```bash
sudo install -m 0644 docs/policies/operational-witness-v1.md /mnt/bitcoin/spurline/witness-policy.txt
docker compose exec -T spurline spurline service show > commissioning-state.json
docker compose exec -T spurline spurline service witness request \
  --policy /data/witness-policy.txt --valid-for 2592000 \
  --kind 1415 --kind 1416 > witness-request.json
```

Adjust the host destination to your actual `SPURLINE_DATA_DIR`. The signed policy
must contain the exact line `Spurline-Clock-Profile: operational-v1`. This explicit
permission marker prevents enabling operational mode under an unrelated policy;
the relay also rejects bounded mode under this marker and operational issuance
configured with a delay greater than the policy's 60-second limit.
The rest of the policy still requires human review. Changing bytes after signing
changes the digest and requires new approval. Do not promise bounded accuracy
elsewhere in the policy.

Copy the JSON files and exact policy to the trusted operator workstation. Use
the [operator signing command](operator-signing.md#sign-an-initial-witness-authorization),
then import and publish the signed authorization on the relay host:

```bash
docker compose exec -T spurline spurline service witness authorize < witness-authorization.json
docker compose exec -T spurline spurline service witness verify
docker compose exec -T spurline spurline service publish --relay ws://127.0.0.1:8080
docker compose exec -T spurline spurline service witness publish --relay ws://127.0.0.1:8080
```

These commands assume no prior witness grant, as in the current deployment.
For an already authorized instance, use the existing renewal process; the offline
signer currently supports initial grants only. Do not erase lifecycle history to
switch policies. The commissioning already completed need not be repeated.

## Enable and test

After checking the monitor and authorization, set `SPURLINE_WITNESS_ENABLED=true`
and recreate the container. `/info` should report `clock_mode: "operational"` and
`receipt_version: 2`; configuration alone is not proof of current clock health.
Submit a fresh signed kind 1415 or 1416 test event and query kind 1418 receipts
by its `e` tag. Verify the resulting receipt's signature, exact subject binding,
policy reference, and the [version 2 time fields](observation-receipt-v2.md).

Old receipts are never rewritten. Pending jobs retain their acquisition profile;
a mode change makes incompatible pending jobs unavailable, not silently upgraded
or downgraded. The same signed subject's existing job is not replaced on resubmission.
There is no database schema migration for this mode.

To stop issuance, use the existing local `service witness suspend` command or
set witnessing disabled and recreate the container. To investigate a clock-step
alarm, first suspend issuance, correct and check host synchronization, restart
the relay, and only then resume. Restart clears the process-local alarm; it is
not itself evidence that the clock is trustworthy.
