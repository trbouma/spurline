---
title: Runtime Model
description: How Spurline is structured internally.
---

# Runtime Model

Spurline follows the same broad application shape as Grove and Safebox Web:

- FastAPI app factory;
- Uvicorn runtime;
- HTTP routes for health and metadata;
- WebSocket routes for live protocol traffic;
- SQLite for local persistence;
- Poetry for dependency and command management.

## Components

```text
spurline.main      FastAPI app factory and route definitions
spurline.config    runtime settings
spurline.events    event validation and ID calculation
spurline.filters   NIP-01 filter matching
spurline.store     SQLite event persistence
spurline.cli       Uvicorn launcher
```

The relay protocol logic is kept close to the FastAPI WebSocket route while
storage, event validation, and filter matching remain separate modules.

## Local-first defaults

The default bind address is:

```text
127.0.0.1:8080
```

The default database path is:

```text
spurline.sqlite3
```

For ordinary local use, prefer an explicit data directory:

```bash
poetry run spurline --database ./data/spurline.sqlite3
```
