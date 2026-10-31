from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from . import __version__
from .config import Settings
from .events import EventValidationError, StoredEvent, validate_event
from .filters import FilterValidationError, matches_any_filter, normalize_filters
from .homepage import render_homepage
from .identity import bind_service_identity
from .service import ServiceCommissioning
from .witness import WitnessAuthorization
from .automatic_witness import AutomaticWitness
from .storage import EventStorage, SQLiteStorage, StorageError

logger = logging.getLogger(__name__)

SubscriptionMap = dict[str, list[dict[str, Any]]]


class RelayService:
    def __init__(self, store: EventStorage, *, verify_signatures: bool = True) -> None:
        self.store = store
        self.verify_signatures = verify_signatures
        self.witness = None
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

        try:
            inserted = (await asyncio.to_thread(self.witness.accept, event)
                        if self.witness else await self.store.save(event))
        except (StorageError, sqlite3.Error, OverflowError):
            logger.exception("Event storage failed")
            await websocket.send_json(["OK", event.id, False, "error: storage could not confirm publication"])
            return
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
        self.connections[websocket].pop(subscription_id, None)
        try:
            filters = normalize_filters(payload[2:])
        except FilterValidationError as exc:
            await websocket.send_json(["CLOSED", subscription_id, f"invalid: {exc}"])
            return
        self.connections[websocket][subscription_id] = filters

        try:
            events = await self.store.query(filters)
        except StorageError:
            logger.exception("Subscription query failed")
            self.connections[websocket].pop(subscription_id, None)
            await websocket.send_json(["CLOSED", subscription_id, "error: storage query failed"])
            return
        for event in events:
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


def create_app(settings: Settings | None = None, *, store: EventStorage | None = None) -> FastAPI:
    configured = settings or Settings.from_env()
    store = store if store is not None else SQLiteStorage(configured.database_path)
    relay = RelayService(store, verify_signatures=configured.verify_signatures)
    if configured.witness_enabled:
        if not isinstance(store, SQLiteStorage):
            raise ValueError("automatic witnessing currently requires SQLiteStorage")
        relay.witness = AutomaticWitness(configured, store._store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker = None
        try:
            bind_service_identity(
                configured.database_path, npub=configured.service_npub
            )
            await asyncio.to_thread(ServiceCommissioning(configured).show)
            await asyncio.to_thread(WitnessAuthorization(configured).show)
            if relay.witness:
                worker = asyncio.create_task(relay.witness.run(relay.broadcast))
            yield
        finally:
            if worker:
                relay.witness.stopping.set()
                await worker
            await app.state.store.close()

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

    @app.get("/", response_model=None)
    async def root(request: Request):
        info = await asyncio.to_thread(relay_info, configured)
        if "text/html" in request.headers.get("accept", "").lower():
            identity = info["service_identity"]
            return HTMLResponse(
                render_homepage(
                    version=__version__,
                    relay_url=info["relay"]["websocket_url"],
                    verify_signatures=configured.verify_signatures,
                    supported_nips=info["supported_nips"],
                    service_npub=configured.service_npub,
                    service_fips_ipv6_address=(
                        configured.service_fips_ipv6_address
                    ),
                    service_management=identity["management"],
                    service_state=identity["state"],
                )
            )
        return info

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "spurline", "version": __version__}

    @app.get("/assets/spurline-logo.svg", include_in_schema=False)
    async def spurline_logo():
        return FileResponse(
            Path(__file__).with_name("assets") / "spurline-logo.svg",
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/info")
    async def info():
        return await asyncio.to_thread(relay_info, configured)

    @app.get("/v1/service-identity")
    async def service_identity():
        status = await asyncio.to_thread(ServiceCommissioning(configured).show)
        info = await asyncio.to_thread(relay_info, configured, status=status)
        return {"service_identity": info["service_identity"], "evidence": status["evidence"]}

    @app.get("/v1/witness-authorization")
    async def witness_authorization():
        status = await asyncio.to_thread(WitnessAuthorization(configured).show)
        return {key: value for key, value in status.items() if key != "local_controls"}

    @app.get("/v1/witness-status/{digest}")
    async def witness_status(digest: str):
        if len(digest) != 64 or any(ch not in '0123456789abcdef' for ch in digest):
            return {"state": "invalid-digest"}
        if not relay.witness:
            return {"state": "disabled", "receipt_event_id": None}
        return await asyncio.to_thread(relay.witness.status, digest)

    @app.get("/.well-known/nostr.json")
    async def well_known_info():
        return await asyncio.to_thread(relay_info, configured)

    @app.websocket("/")
    async def nostr_relay(websocket: WebSocket):
        await relay.connect(websocket)
        try:
            while True:
                message = await websocket.receive_text()
                await relay.handle_message(websocket, message)
        except WebSocketDisconnect:
            pass
        finally:
            relay.disconnect(websocket)

    return app


def relay_info(settings: Settings, *, status: dict[str, Any] | None = None) -> dict[str, Any]:
    if status is None:
        status = ServiceCommissioning(settings).show()
    witness = WitnessAuthorization(settings).show()
    return {
        "name": "Spurline",
        "description": "A local-first relay for individuals and communities.",
        "software": "spurline",
        "version": __version__,
        "automatic_witness": {"configured": settings.witness_enabled,
                              "publication": "local", "receipt_kind": 1418,
                              "status_url": "/v1/witness-status/{signed_event_digest}",
                              "clock_health_required": True},
        "witness_authorization": {key: value for key, value in witness.items()
                                  if key not in {"evidence", "history", "pending", "pending_status", "local_controls"}},
        "service_identity": {
            "npub": settings.service_npub,
            "fips_ipv6_address": settings.service_fips_ipv6_address,
            "type": "nostr-relay",
            "management": settings.service_management,
            "state": status["state"],
            "descriptor_event_id": status.get("service_descriptor_event_id"),
            "operator": status.get("operator_npub"),
        },
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
