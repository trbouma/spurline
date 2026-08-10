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
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Run

```bash
spurline --host 127.0.0.1 --port 8080 --database ./data/spurline.sqlite3
```

For test fixtures or private local experiments, signature verification can be disabled:

```bash
spurline --no-verify-signatures
```

Then connect a Nostr client to:

```text
ws://127.0.0.1:8080
```

## Test

```bash
pytest
```

## Site

```bash
python -m pip install -e ".[docs]"
mkdocs serve
```
