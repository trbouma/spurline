from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

import uvicorn
from stroma import RelayError

from .config import Settings
from .main import create_app
from .commissioning import CommissioningError
from .service import ServiceCommissioning
from .witness import WitnessAuthorization


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local Nostr relay.")
    parser.add_argument("--host", help="Host interface to bind.")
    parser.add_argument("--port", type=int, help="Port to bind.")
    parser.add_argument(
        "--database",
        type=Path,
        help="SQLite database path.",
    )
    parser.add_argument(
        "--no-verify-signatures",
        action="store_true", default=None,
        help="Accept events without Schnorr signature verification.",
    )
    parser.add_argument(
        "--public-url",
        help="Externally visible ws:// or wss:// relay URL.",
    )
    commands = parser.add_subparsers(dest="command")
    service = commands.add_parser("service", help="Locally administer service commissioning.")
    actions = service.add_subparsers(dest="action", required=True)
    request = actions.add_parser("request", help="Sign a request to the specified operator.")
    request.add_argument("operator_npub")
    commission = actions.add_parser("commission", help="Accept an operator attestation JSON from stdin.")
    commission.add_argument("--file", type=Path, help="Read attestation JSON from a file instead.")
    actions.add_parser("show", help="Show retained public evidence.")
    actions.add_parser("verify", help="Verify the complete retained evidence chain.")
    publish = actions.add_parser("publish", help="Publish retained evidence to specified relays.")
    publish.add_argument("--relay", action="append", required=True)
    publish.add_argument("--timeout", type=float, default=10)
    witness = actions.add_parser("witness", help="Request and retain operator authorization to witness.")
    witness_actions = witness.add_subparsers(dest="witness_action", required=True)
    witness_request = witness_actions.add_parser("request", help="Request authorization under a public policy.")
    witness_request.add_argument("--policy", type=Path, required=True, help="UTF-8 policy file; retained and publicly exposed.")
    witness_request.add_argument("--valid-for", type=int, required=True, help="Authorization duration in seconds, at most one year.")
    witness_request.add_argument("--kind", type=int, action="append", choices=[1415, 1416], help="Repeat to select subject kinds; default: both.")
    renewal = witness_actions.add_parser("renew", help="Request a signed renewal referencing the lifecycle head.")
    renewal.add_argument("--policy", type=Path, required=True)
    renewal.add_argument("--valid-for", type=int, required=True)
    renewal.add_argument("--kind", type=int, action="append", choices=[1415, 1416])
    authorize = witness_actions.add_parser("authorize", help="Import the commissioned operator's signed authorization.")
    authorize.add_argument("--file", type=Path)
    revoke_request = witness_actions.add_parser("revocation-request", help="Prepare an unsigned operator revocation template.")
    revoke_request.add_argument("--reason", required=True, help="Public signed reason.")
    revoke = witness_actions.add_parser("revoke", help="Import an operator-signed revocation.")
    revoke.add_argument("--file", type=Path)
    for action in ("suspend", "resume"):
        control = witness_actions.add_parser(action, help=f"Locally {action} witness permission; never changes signed authority.")
        control.add_argument("--reason", required=True, help="Local audit reason, not published.")
    witness_actions.add_parser("history", help="Show all verified lifecycle evidence and local audit controls.")
    witness_actions.add_parser("show")
    witness_actions.add_parser("verify", help="Verify evidence and report its current validity state.")
    witness_publish = witness_actions.add_parser("publish", help="Publish retained witness request and authorization.")
    witness_publish.add_argument("--relay", action="append", required=True)
    witness_publish.add_argument("--timeout", type=float, default=10)
    return parser


async def publish_evidence(evidence, relays, timeout, *, names=None):
    from stroma import Event, RelayPool
    pool = RelayPool(relays, timeout=timeout)
    published = []
    for name in names or ("commissioning_request", "operator_attestation", "service_descriptor"):
        event = Event.load(evidence[name], validate=True)
        results = await pool.publish(event, require=len(set(relays)))
        published.append({"event_id": event.id, "relays": [result.relay for result in results]})
    return {"state": "published", "events": published}


def read_signed_event(path):
    if path:
        with path.open(encoding="utf-8") as stream:
            raw = stream.read(1024 * 1024 + 1)
    else:
        raw = sys.stdin.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise CommissioningError("attestation exceeds 1 MiB")
    event = json.loads(raw)
    return event["event"] if isinstance(event, dict) and "event" in event else event


def witness_command(args, settings):
    witness = WitnessAuthorization(settings)
    if args.witness_action in ("request", "renew"):
        return witness.request(args.policy, valid_for=args.valid_for, kinds=args.kind or [1415, 1416],
                               renew=args.witness_action == "renew")
    if args.witness_action == "authorize":
        return witness.authorize(read_signed_event(args.file))
    if args.witness_action == "revocation-request":
        return witness.revocation_request(args.reason)
    if args.witness_action == "revoke":
        return witness.revoke(read_signed_event(args.file))
    if args.witness_action in ("suspend", "resume"):
        return witness.control(args.witness_action, args.reason)
    if args.witness_action == "verify":
        return witness.verify()
    if args.witness_action == "publish":
        status = witness.verify()
        evidence = {}
        for index, entry in enumerate(status["history"]):
            for name in ("request", "authorization", "revocation"):
                if name in entry:
                    evidence[f"{index}:{name}"] = entry[name]
        return asyncio.run(publish_evidence(evidence, args.relay, args.timeout,
                                           names=tuple(evidence)))
    return witness.show()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = Settings.from_env()
    overrides = {key: value for key, value in {
        "host": args.host, "port": args.port, "database_path": args.database,
        "verify_signatures": False if args.no_verify_signatures else None,
        "public_url": args.public_url,
    }.items() if value is not None}
    settings = replace(settings, **overrides)
    if args.command == "service":
        service = ServiceCommissioning(settings)
        try:
            if args.action == "witness":
                result = witness_command(args, settings)
            elif args.action == "request":
                result = service.request(args.operator_npub)
            elif args.action == "commission":
                result = service.commission(read_signed_event(args.file))
            elif args.action == "verify":
                result = service.verify()
            elif args.action == "publish":
                service.verify()
                result = asyncio.run(publish_evidence(service.show()["evidence"], args.relay, args.timeout))
            else:
                result = service.show()
        except (CommissioningError, OSError, ValueError, sqlite3.Error, RelayError) as exc:
            parser.exit(1, f"Error: {exc}\n")
        print(json.dumps(result, indent=2))
        return
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
