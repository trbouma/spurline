---
title: Container Deployment
description: Build and operate Spurline as a Docker container.
---

# Container Deployment

Spurline ships with a production-oriented container build for AMD64 and ARM64.
It runs as an unprivileged user, stores its SQLite database in `/data`, and
serves Nostr WebSocket traffic and HTTP probes on port `8080`.

## Start with Docker Compose

Build and start the relay:

```bash
docker compose up --build --detach
docker compose ps
```

The default port is bound to host loopback only:

```text
ws://127.0.0.1:8080/
http://127.0.0.1:8080/health
http://127.0.0.1:8080/info
```

Follow runtime logs with:

```bash
docker compose logs --follow spurline
```

The `spurline-data` Docker volume uses the local driver to bind the host
directory `/mnt/bitcoin/spurline` at `/data` inside the container. This gives
Docker a named volume while keeping the database at an explicit host location.
Create the directory with ownership matching Spurline's unprivileged container
user before the first start:

```bash
sudo install -d -o 10001 -g 10001 /mnt/bitcoin/spurline
```

The database therefore lives at:

```text
/mnt/bitcoin/spurline/spurline.sqlite3
```

This directory survives container replacement. Normal updates do not erase
relay events:

```bash
docker compose up --build --detach --force-recreate
```

`docker compose down` leaves the named volume, host directory, and database
untouched. Removing the Docker volume registration does not replace a proper
backup policy for the host directory.

To back the named volume with another host location, set
`SPURLINE_DATA_DIR` when Compose first creates the volume:

```bash
SPURLINE_DATA_DIR=/srv/spurline docker compose up --build --detach
```

Docker records the selected device path in the volume definition. If you later
change `SPURLINE_DATA_DIR`, remove and recreate the empty Docker volume
registration before starting Spurline against the new directory. Do not delete
the underlying host data.

## Publish on another interface

Loopback is the conservative default. To make the port reachable on the local
network, explicitly select a publish address:

```bash
SPURLINE_PUBLISH_ADDRESS=0.0.0.0 docker compose up --build --detach
```

For internet-facing operation, put Spurline behind a TLS reverse proxy that
supports WebSocket upgrades. Publish `wss://` to clients rather than exposing
the plain WebSocket port directly.

## Configuration

The image recognizes these environment variables:

| Variable | Container default | Purpose |
| --- | --- | --- |
| `SPURLINE_HOST` | `0.0.0.0` | Internal bind address |
| `SPURLINE_PORT` | `8080` | Internal HTTP and WebSocket port |
| `SPURLINE_DATABASE` | `/data/spurline.sqlite3` | SQLite database path |
| `SPURLINE_VERIFY_SIGNATURES` | `true` | Verify Nostr event signatures |

Signature verification should remain enabled outside disposable test fixtures.

## Published image

Pushes to `main` publish a multi-architecture image to GitHub Container
Registry:

```bash
docker pull ghcr.io/trbouma/spurline:latest
docker run --detach \
  --name spurline \
  --publish 127.0.0.1:8080:8080 \
  --volume /mnt/bitcoin/spurline:/data \
  ghcr.io/trbouma/spurline:latest
```

Tagged releases also receive their Git tag as an image tag. The build targets
`linux/amd64` and `linux/arm64`, including Raspberry Pi 4 installations using a
64-bit operating system.

## Operational boundaries

Run one Spurline process against each SQLite database. Live WebSocket
subscriptions are held in process memory, so adding Uvicorn workers would
partition connected clients and event fan-out. Future horizontal scaling
requires an explicit shared coordination design rather than a worker-count
change.
