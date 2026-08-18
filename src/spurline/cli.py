from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .config import Settings
from .main import create_app


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
    parser.add_argument(
        "--public-url",
        help="Externally visible ws:// or wss:// relay URL.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = Settings(
        host=args.host,
        port=args.port,
        database_path=args.database,
        verify_signatures=not args.no_verify_signatures,
        public_url=args.public_url,
    )
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
