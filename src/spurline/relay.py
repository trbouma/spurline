from __future__ import annotations

import asyncio
import json
import signal
from contextlib import suppress
from pathlib import Path
from typing import Any

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from .events import EventValidationError, StoredEvent, validate_event
from .filters import matches_any_filter, normalize_filters
from .store import EventStore


SubscriptionMap = dict[str, list[dict[str, Any]]]


class Relay:
    def __init__(
        self,
        *,
        database_path: Path,
        host: str = "127.0.0.1",
        port: int = 8080,
        verify_signatures: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.verify_signatures = verify_signatures
        self.store = EventStore(database_path)
        self.connections: dict[ServerConnection, SubscriptionMap] = {}

    async def serve_forever(self) -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with suppress(NotImplementedError):
                loop.add_signal_handler(sig, stop.set)

        async with serve(self.handle_connection, self.host, self.port):
            print(f"spurline listening on ws://{self.host}:{self.port}")
            await stop.wait()

        self.store.close()

    async def handle_connection(self, websocket: ServerConnection) -> None:
        self.connections[websocket] = {}
        try:
            async for message in websocket:
                await self.handle_message(websocket, message)
        except ConnectionClosed:
            pass
        finally:
            self.connections.pop(websocket, None)

    async def handle_message(self, websocket: ServerConnection, message: str | bytes) -> None:
        if isinstance(message, bytes):
            await websocket.send(json.dumps(["NOTICE", "binary messages are not supported"]))
            return

        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            await websocket.send(json.dumps(["NOTICE", "invalid JSON"]))
            return

        if not isinstance(payload, list) or not payload or not isinstance(payload[0], str):
            await websocket.send(json.dumps(["NOTICE", "message must be a Nostr array"]))
            return

        match payload[0]:
            case "EVENT":
                await self._handle_event(websocket, payload)
            case "REQ":
                await self._handle_req(websocket, payload)
            case "CLOSE":
                await self._handle_close(websocket, payload)
            case _:
                await websocket.send(json.dumps(["NOTICE", f"unsupported command: {payload[0]}"]))

    async def _handle_event(self, websocket: ServerConnection, payload: list[Any]) -> None:
        if len(payload) != 2:
            await websocket.send(json.dumps(["NOTICE", "EVENT expects one event object"]))
            return

        raw_event = payload[1]
        event_id = raw_event.get("id") if isinstance(raw_event, dict) else ""

        try:
            event = validate_event(raw_event, verify_signature=self.verify_signatures)
        except EventValidationError as exc:
            await websocket.send(json.dumps(["OK", event_id, False, f"invalid: {exc}"]))
            return

        inserted = self.store.save(event)
        if not inserted:
            await websocket.send(json.dumps(["OK", event.id, True, "duplicate: already have event"]))
            return

        await websocket.send(json.dumps(["OK", event.id, True, ""]))
        await self._broadcast(event)

    async def _handle_req(self, websocket: ServerConnection, payload: list[Any]) -> None:
        if len(payload) < 3 or not isinstance(payload[1], str):
            await websocket.send(json.dumps(["NOTICE", "REQ expects a subscription id and filters"]))
            return

        subscription_id = payload[1]
        filters = normalize_filters(payload[2:])
        self.connections[websocket][subscription_id] = filters

        for event in self.store.query(filters):
            await websocket.send(json.dumps(["EVENT", subscription_id, event.to_dict()]))
        await websocket.send(json.dumps(["EOSE", subscription_id]))

    async def _handle_close(self, websocket: ServerConnection, payload: list[Any]) -> None:
        if len(payload) != 2 or not isinstance(payload[1], str):
            await websocket.send(json.dumps(["NOTICE", "CLOSE expects a subscription id"]))
            return
        self.connections[websocket].pop(payload[1], None)

    async def _broadcast(self, event: StoredEvent) -> None:
        sends = []
        for websocket, subscriptions in list(self.connections.items()):
            for subscription_id, filters in subscriptions.items():
                if matches_any_filter(event, filters):
                    sends.append(websocket.send(json.dumps(["EVENT", subscription_id, event.to_dict()])))
        if sends:
            await asyncio.gather(*sends, return_exceptions=True)
