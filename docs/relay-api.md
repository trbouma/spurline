---
title: Relay API
description: Spurline HTTP and WebSocket surface.
---

# Relay API

Spurline exposes HTTP utility routes and a Nostr WebSocket relay route on the
same FastAPI application.

## WebSocket

```text
WS /
```

Implemented NIP-01 message flow:

- `EVENT`
- `REQ`
- `CLOSE`
- `EOSE`
- `OK`
- `NOTICE`

Events are validated, stored, replayed to matching subscriptions, and broadcast
to live matching subscriptions.

## HTTP

```text
GET /
GET /health
GET /info
GET /.well-known/nostr.json
```

`/health` returns a minimal readiness response:

```json
{
  "status": "ok",
  "service": "spurline",
  "version": "0.1.0"
}
```

`/info` and `/.well-known/nostr.json` return relay metadata:

```json
{
  "name": "Spurline",
  "description": "A local-first relay for individuals and communities.",
  "software": "spurline",
  "version": "0.1.0",
  "supported_nips": [1]
}
```

## Storage

Spurline uses SQLite for local persistence. The current schema stores event
fields and the raw canonical event JSON. SQLite runs in WAL mode.

The current implementation is designed for a single local relay process.
