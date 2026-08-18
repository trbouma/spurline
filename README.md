# spurline
A local relay for the global Nostr network.

Spurline is a small Python Nostr relay intended for local development and experiments. It
implements the core NIP-01 relay flow:

- `EVENT` acceptance with canonical event ID checks and Schnorr signature verification.
- `REQ` subscriptions with stored-event replay.
- `CLOSE` subscription cleanup.
- SQLite persistence.
- Live fan-out to matching subscriptions.

## Install

```bash
poetry install --with dev
```

## Run

```bash
poetry run spurline --host 127.0.0.1 --port 8080 --database ./data/spurline.sqlite3
```

The relay runs as a FastAPI application under Uvicorn. For direct ASGI
development, use:

```bash
poetry run uvicorn spurline.main:create_app --factory --host 127.0.0.1 --port 8080 --reload
```

For test fixtures or private local experiments, signature verification can be disabled:

```bash
poetry run spurline --no-verify-signatures
```

Then connect a Nostr client to:

```text
ws://127.0.0.1:8080
```

HTTP probes are available on the same port:

```text
http://127.0.0.1:8080/health
http://127.0.0.1:8080/info
http://127.0.0.1:8080/.well-known/nostr.json
```

## Test

```bash
poetry run pytest
```

## Docker

Build and run Spurline with a persistent SQLite volume:

```bash
docker compose up --build --detach
docker compose ps
curl http://127.0.0.1:8080/health
```

The container listens on port `8080`, runs as an unprivileged user, and uses a
named Docker volume backed by `/mnt/bitcoin/spurline` on the host. Create that
directory for container UID and GID `10001` before the first start. See the
[container deployment guide](https://trbouma.github.io/spurline/container-deployment/)
for image publishing, ARM64 support, reverse-proxy guidance, and configuration.

## Site

```bash
poetry install --with docs
poetry run mkdocs serve
```
