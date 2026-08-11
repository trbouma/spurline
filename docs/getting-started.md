---
title: Getting Started
description: Run Spurline locally.
---

# Getting Started

Install dependencies with Poetry:

```bash
poetry install --with dev,docs
```

Run the relay:

```bash
poetry run spurline --host 127.0.0.1 --port 8080 --database ./data/spurline.sqlite3
```

Connect a Nostr client to:

```text
ws://127.0.0.1:8080/
```

Check the relay:

```bash
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/info
```

For local experiments or test fixtures, signature verification can be disabled:

```bash
poetry run spurline --no-verify-signatures
```

## Development server

Spurline runs as a FastAPI application under Uvicorn:

```bash
poetry run uvicorn spurline.main:create_app --factory --host 127.0.0.1 --port 8080 --reload
```

## Tests

```bash
poetry run pytest
```
