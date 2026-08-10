from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

try:
    from coincurve import PublicKeyXOnly
except ImportError:  # pragma: no cover - handled at runtime for friendlier errors
    PublicKeyXOnly = None  # type: ignore[assignment]


HEX_32 = 64
HEX_64 = 128


class EventValidationError(ValueError):
    """Raised when an event does not satisfy the base Nostr event rules."""


@dataclass(frozen=True)
class StoredEvent:
    id: str
    pubkey: str
    created_at: int
    kind: int
    tags: list[list[str]]
    content: str
    sig: str

    @classmethod
    def from_dict(cls, event: dict[str, Any]) -> StoredEvent:
        return cls(
            id=event["id"],
            pubkey=event["pubkey"],
            created_at=event["created_at"],
            kind=event["kind"],
            tags=event["tags"],
            content=event["content"],
            sig=event["sig"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "pubkey": self.pubkey,
            "created_at": self.created_at,
            "kind": self.kind,
            "tags": self.tags,
            "content": self.content,
            "sig": self.sig,
        }


def canonical_event_payload(event: dict[str, Any]) -> str:
    payload = [
        0,
        event["pubkey"],
        event["created_at"],
        event["kind"],
        event["tags"],
        event["content"],
    ]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def event_id(event: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_event_payload(event).encode("utf-8")).hexdigest()


def validate_event(event: Any, *, verify_signature: bool = True) -> StoredEvent:
    if not isinstance(event, dict):
        raise EventValidationError("event must be an object")

    required = {"id", "pubkey", "created_at", "kind", "tags", "content", "sig"}
    missing = sorted(required.difference(event))
    if missing:
        raise EventValidationError(f"missing fields: {', '.join(missing)}")

    if not _is_hex(event["id"], HEX_32):
        raise EventValidationError("id must be 32 bytes of lowercase hex")
    if not _is_hex(event["pubkey"], HEX_32):
        raise EventValidationError("pubkey must be 32 bytes of lowercase hex")
    if not _is_hex(event["sig"], HEX_64):
        raise EventValidationError("sig must be 64 bytes of lowercase hex")
    if not isinstance(event["created_at"], int):
        raise EventValidationError("created_at must be an integer")
    if event["created_at"] > int(time.time()) + 900:
        raise EventValidationError("created_at is too far in the future")
    if not isinstance(event["kind"], int):
        raise EventValidationError("kind must be an integer")
    if not isinstance(event["content"], str):
        raise EventValidationError("content must be a string")
    if not _valid_tags(event["tags"]):
        raise EventValidationError("tags must be a list of string lists")

    expected_id = event_id(event)
    if event["id"] != expected_id:
        raise EventValidationError("id does not match serialized event")

    if verify_signature:
        verify_event_signature(event)

    return StoredEvent.from_dict(event)


def verify_event_signature(event: dict[str, Any]) -> None:
    if PublicKeyXOnly is None:
        raise EventValidationError("coincurve is required for signature verification")

    message = bytes.fromhex(event["id"])
    signature = bytes.fromhex(event["sig"])
    pubkey = bytes.fromhex(event["pubkey"])

    if not PublicKeyXOnly(pubkey).verify(signature, message):
        raise EventValidationError("signature verification failed")


def _is_hex(value: Any, length: int) -> bool:
    if not isinstance(value, str) or len(value) != length:
        return False
    return all(char in "0123456789abcdef" for char in value)


def _valid_tags(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(tag, list) and all(isinstance(item, str) for item in tag) for tag in value
    )
