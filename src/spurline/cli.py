from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .relay import Relay


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local Nostr relay.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind.")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("spurline.sqlite3"),
        help="SQLite database path.",
    )
    parser.add_argument(
        "--no-verify-signatures",
        action="store_true",
        help="Accept events without Schnorr signature verification.",
    )
    return parser


async def run(args: argparse.Namespace) -> None:
    relay = Relay(
        database_path=args.database,
        host=args.host,
        port=args.port,
        verify_signatures=not args.no_verify_signatures,
    )
    await relay.serve_forever()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
