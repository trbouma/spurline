"""Persistent Nostr identity binding for a Spurline relay instance."""

from __future__ import annotations

import json
import os
from pathlib import Path

from stroma import KeyError as StromaKeyError
from stroma import Keys
from stroma import fips_ipv6_address as stroma_fips_ipv6_address


def service_npub(secret: str) -> str:
    """Derive the NIP-19 npub for a hex or nsec-encoded private key."""

    try:
        return Keys(priv_k=secret).public_key_bech32()
    except StromaKeyError as exc:
        raise ValueError("SPURLINE_SERVICE_NSEC is invalid") from exc


def fips_ipv6_address(npub: str) -> str:
    """Derive the FIPS fd00::/8 address for a service npub."""

    try:
        return stroma_fips_ipv6_address(npub)
    except StromaKeyError as exc:
        raise ValueError("Spurline service npub is invalid") from exc


def bind_service_identity(database_path: Path, *, npub: str | None) -> None:
    """Bind a persistent relay data directory to one service identity."""

    path = database_path.parent / "service-identity.json"
    if path.is_file():
        try:
            recorded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Spurline service identity sentinel is invalid") from exc
        recorded_npub = recorded.get("npub") if isinstance(recorded, dict) else None
        if not isinstance(recorded_npub, str) or not recorded_npub:
            raise RuntimeError("Spurline service identity sentinel is invalid")
        if npub is None:
            raise RuntimeError(
                "SPURLINE_SERVICE_NSEC is required for the recorded Spurline identity"
            )
        if recorded_npub != npub:
            raise RuntimeError(
                "SPURLINE_SERVICE_NSEC does not match the recorded Spurline identity"
            )
        return

    if npub is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"schema": "org.mainstay.service-identity", "npub": npub}) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
