from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import Settings
from .events import EventValidationError, StoredEvent, validate_event
from .filters import matches_any_filter, normalize_filters
from .store import EventStore

SubscriptionMap = dict[str, list[dict[str, Any]]]


class RelayService:
    def __init__(self, store: EventStore, *, verify_signatures: bool = True) -> None:
        self.store = store
        self.verify_signatures = verify_signatures
        self.connections: dict[WebSocket, SubscriptionMap] = {}

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections[websocket] = {}

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections.pop(websocket, None)

    async def handle_message(self, websocket: WebSocket, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            await websocket.send_json(["NOTICE", "invalid JSON"])
            return

        if not isinstance(payload, list) or not payload or not isinstance(payload[0], str):
            await websocket.send_json(["NOTICE", "message must be a Nostr array"])
            return

        match payload[0]:
            case "EVENT":
                await self._handle_event(websocket, payload)
            case "REQ":
                await self._handle_req(websocket, payload)
            case "CLOSE":
                await self._handle_close(websocket, payload)
            case _:
                await websocket.send_json(["NOTICE", f"unsupported command: {payload[0]}"])

    async def _handle_event(self, websocket: WebSocket, payload: list[Any]) -> None:
        if len(payload) != 2:
            await websocket.send_json(["NOTICE", "EVENT expects one event object"])
            return

        raw_event = payload[1]
        event_id = raw_event.get("id") if isinstance(raw_event, dict) else ""

        try:
            event = validate_event(raw_event, verify_signature=self.verify_signatures)
        except EventValidationError as exc:
            await websocket.send_json(["OK", event_id, False, f"invalid: {exc}"])
            return

        inserted = self.store.save(event)
        if not inserted:
            await websocket.send_json(["OK", event.id, True, "duplicate: already have event"])
            return

        await websocket.send_json(["OK", event.id, True, ""])
        await self.broadcast(event)

    async def _handle_req(self, websocket: WebSocket, payload: list[Any]) -> None:
        if len(payload) < 3 or not isinstance(payload[1], str):
            await websocket.send_json(["NOTICE", "REQ expects a subscription id and filters"])
            return

        subscription_id = payload[1]
        filters = normalize_filters(payload[2:])
        self.connections[websocket][subscription_id] = filters

        for event in self.store.query(filters):
            await websocket.send_json(["EVENT", subscription_id, event.to_dict()])
        await websocket.send_json(["EOSE", subscription_id])

    async def _handle_close(self, websocket: WebSocket, payload: list[Any]) -> None:
        if len(payload) != 2 or not isinstance(payload[1], str):
            await websocket.send_json(["NOTICE", "CLOSE expects a subscription id"])
            return
        self.connections[websocket].pop(payload[1], None)

    async def broadcast(self, event: StoredEvent) -> None:
        sends = []
        for websocket, subscriptions in list(self.connections.items()):
            for subscription_id, filters in subscriptions.items():
                if matches_any_filter(event, filters):
                    sends.append(websocket.send_json(["EVENT", subscription_id, event.to_dict()]))
        if sends:
            await asyncio.gather(*sends, return_exceptions=True)


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings or Settings.from_env()
    store = EventStore(configured.database_path)
    relay = RelayService(store, verify_signatures=configured.verify_signatures)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        app.state.store.close()

    app = FastAPI(
        title="Spurline",
        description="A local-first relay for individuals and communities.",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = configured
    app.state.store = store
    app.state.relay = relay
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
        max_age=86400,
    )

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Access-Control-Allow-Origin", "*")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    @app.get("/")
    async def root():
        return relay_info(configured)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "spurline", "version": __version__}

    @app.get("/info")
    async def info():
        return relay_info(configured)

    @app.get("/.well-known/nostr.json")
    async def well_known_info():
        return relay_info(configured)

    @app.websocket("/")
    async def nostr_relay(websocket: WebSocket):
        await relay.connect(websocket)
        try:
            while True:
                message = await websocket.receive_text()
                await relay.handle_message(websocket, message)
        except WebSocketDisconnect:
            relay.disconnect(websocket)

    return app


def relay_info(settings: Settings) -> dict[str, Any]:
    return {
        "name": "Spurline",
        "description": "A local-first relay for individuals and communities.",
        "software": "spurline",
        "version": __version__,
        "supported_nips": [1],
        "contact": "",
        "pubkey": "",
        "limitation": {
            "payment_required": False,
            "auth_required": False,
            "restricted_writes": False,
        },
        "relay": {
            "websocket_url": settings.public_url or f"ws://{settings.host}:{settings.port}",
            "health_url": "/health",
            "info_url": "/info",
        },
    }
