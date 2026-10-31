"""Signed service-identity commissioning evidence."""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from stroma import Event, Keys
from stroma import EventError as StromaEventError
from stroma import KeyError as StromaKeyError

from .events import validate_event, EventValidationError


class CommissioningError(ValueError):
    """Invalid or unavailable service commissioning evidence."""


APPLICATION_EVENT_KIND = 78
ADDRESSABLE_APPLICATION_EVENT_KIND = 30078
REQUEST_SCHEMA = "org.mainstay.service-commissioning-request"
ATTESTATION_SCHEMA = "org.mainstay.service-operator-attestation"
DESCRIPTOR_SCHEMA = "org.mainstay.service-descriptor"
SERVICE_TYPE = "nostr-relay"
REQUEST_TTL_SECONDS = 24 * 60 * 60
MAX_CLOCK_SKEW_SECONDS = 5 * 60


@dataclass(frozen=True)
class VerifiedCommissioning:
    request: Event
    attestation: Event
    operator_npub: str


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def normalize_public_key(value: str, *, label: str) -> tuple[str, str]:
    try:
        keys = Keys(pub_k=value.strip())
    except StromaKeyError as exc:
        raise CommissioningError(f"{label} must be an npub or 32-byte public key") from exc
    return keys.public_key_hex(), keys.public_key_bech32()


def create_commissioning_request(
    service_nsec: str,
    operator_npub: str,
    management: str,
    *,
    now: int | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    service_keys = Keys(priv_k=service_nsec)
    operator_hex, _ = normalize_public_key(operator_npub, label="operator")
    issued_at = int(time.time()) if now is None else int(now)
    expires_at = issued_at + REQUEST_TTL_SECONDS
    request_nonce = nonce or secrets.token_hex(32)
    if len(request_nonce) != 64:
        raise CommissioningError("commissioning nonce must contain 32 bytes of hex")
    try:
        if len(bytes.fromhex(request_nonce)) != 32:
            raise ValueError("invalid nonce length")
    except ValueError as exc:
        raise CommissioningError("commissioning nonce must contain 32 bytes of hex") from exc
    content = {
        "expires_at": expires_at,
        "issued_at": issued_at,
        "management": management,
        "nonce": request_nonce,
        "requested_operator": operator_hex,
        "schema": REQUEST_SCHEMA,
        "schema_version": 1,
        "service": {
            "pubkey": service_keys.public_key_hex(),
            "type": SERVICE_TYPE,
        },
    }
    event = Event(
        kind=APPLICATION_EVENT_KIND,
        content=canonical_json(content),
        tags=[
            ["d", f"{REQUEST_SCHEMA}:{request_nonce}"],
            ["p", operator_hex, "", "operator"],
            ["t", "mainstay-service-commissioning"],
            ["service-type", SERVICE_TYPE],
            ["expiration", str(expires_at)],
        ],
        created_at=issued_at,
    )
    event.sign(service_keys)
    return event.data()


def verify_commissioning_request(
    event_data: dict[str, Any],
    *,
    service_npub: str,
    management: str,
    now: int | None = None,
    require_current: bool = True,
) -> tuple[Event, dict[str, Any]]:
    event = _valid_event(event_data, label="commissioning request")
    content = _content(event, REQUEST_SCHEMA)
    service_hex, _ = normalize_public_key(service_npub, label="service")
    current = int(time.time()) if now is None else int(now)
    if event.kind != APPLICATION_EVENT_KIND:
        raise CommissioningError("commissioning request has an unsupported event kind")
    if event.pub_key != service_hex:
        raise CommissioningError("commissioning request was not signed by this service")
    if event.created_at > current + MAX_CLOCK_SKEW_SECONDS:
        raise CommissioningError("commissioning request is dated too far in the future")
    if content.get("issued_at") != event.created_at:
        raise CommissioningError("commissioning request issue time does not match its event")
    expires_at = content.get("expires_at")
    if type(expires_at) is not int:
        raise CommissioningError("commissioning request expiry is invalid")
    if require_current and expires_at <= current:
        raise CommissioningError("commissioning request has expired")
    if expires_at - event.created_at != REQUEST_TTL_SECONDS:
        raise CommissioningError("commissioning request has an invalid validity period")
    if content.get("management") != management:
        raise CommissioningError("commissioning request management mode does not match")
    if content.get("service") != {"pubkey": service_hex, "type": SERVICE_TYPE}:
        raise CommissioningError("commissioning request service identity does not match")
    operator_hex, _ = normalize_public_key(
        str(content.get("requested_operator") or ""),
        label="requested operator",
    )
    nonce = content.get("nonce")
    if not isinstance(nonce, str) or len(nonce) != 64:
        raise CommissioningError("commissioning request nonce is invalid")
    try:
        if len(bytes.fromhex(nonce)) != 32:
            raise ValueError("invalid nonce length")
    except ValueError as exc:
        raise CommissioningError("commissioning request nonce is invalid") from exc
    _require_tag(event, ["p", operator_hex, "", "operator"])
    _require_tag(event, ["expiration", str(expires_at)])
    _require_tag(event, ["service-type", SERVICE_TYPE])
    return event, content


def verify_operator_attestation(
    request_data: dict[str, Any],
    attestation_data: dict[str, Any],
    *,
    service_npub: str,
    management: str,
    now: int | None = None,
    require_current_request: bool = True,
) -> VerifiedCommissioning:
    request, request_content = verify_commissioning_request(
        request_data,
        service_npub=service_npub,
        management=management,
        now=now,
        require_current=require_current_request,
    )
    attestation = _valid_event(attestation_data, label="operator attestation")
    content = _content(attestation, ATTESTATION_SCHEMA)
    current = int(time.time()) if now is None else int(now)
    if attestation.kind != ADDRESSABLE_APPLICATION_EVENT_KIND:
        raise CommissioningError("operator attestation has an unsupported event kind")
    operator_hex = str(request_content["requested_operator"])
    if attestation.pub_key != operator_hex:
        raise CommissioningError(
            "operator attestation was not signed by the requested operator"
        )
    if attestation.created_at < request.created_at:
        raise CommissioningError("operator attestation predates the commissioning request")
    if attestation.created_at > int(request_content["expires_at"]):
        raise CommissioningError("operator attestation was signed after the request expired")
    if attestation.created_at > current + MAX_CLOCK_SKEW_SECONDS:
        raise CommissioningError("operator attestation is dated too far in the future")
    service_hex, _ = normalize_public_key(service_npub, label="service")
    expected = {
        "action": "authorize",
        "commissioning_request": request.id,
        "installation": operator_hex,
        "issued_at": attestation.created_at,
        "management": management,
        "previous": None,
        "relationship": "operates",
        "schema": ATTESTATION_SCHEMA,
        "schema_version": 1,
        "sequence": 1,
        "service": {"pubkey": service_hex, "type": SERVICE_TYPE},
    }
    if canonical_json(content) != canonical_json(expected):
        raise CommissioningError("operator attestation content does not match the request")
    _require_tag(
        attestation,
        ["d", f"{ATTESTATION_SCHEMA}:{service_hex}"],
    )
    _require_tag(attestation, ["p", service_hex, "", "service"])
    _require_tag(
        attestation,
        ["e", request.id, "", "commissioning-request"],
    )
    _require_tag(attestation, ["service-type", SERVICE_TYPE])
    return VerifiedCommissioning(
        request=request,
        attestation=attestation,
        operator_npub=Keys(pub_k=operator_hex).public_key_bech32(),
    )


def create_service_descriptor(
    service_nsec: str,
    attestation_data: dict[str, Any],
    *,
    management: str,
    now: int | None = None,
) -> dict[str, Any]:
    service_keys = Keys(priv_k=service_nsec)
    attestation = _valid_event(attestation_data, label="operator attestation")
    issued_at = int(time.time()) if now is None else int(now)
    content = {
        "capabilities": ["nostr.relay"],
        "issued_at": issued_at,
        "management": management,
        "operator": {
            "attestation_event_id": attestation.id,
            "pubkey": attestation.pub_key,
        },
        "schema": DESCRIPTOR_SCHEMA,
        "schema_version": 1,
        "service": {
            "pubkey": service_keys.public_key_hex(),
            "type": SERVICE_TYPE,
        },
        "state": "commissioned",
    }
    event = Event(
        kind=ADDRESSABLE_APPLICATION_EVENT_KIND,
        content=canonical_json(content),
        tags=[
            ["d", DESCRIPTOR_SCHEMA],
            ["p", str(attestation.pub_key), "", "operator"],
            ["e", attestation.id, "", "operator-attestation"],
            ["t", "mainstay-service-descriptor"],
            ["service-type", SERVICE_TYPE],
        ],
        created_at=issued_at,
    )
    event.sign(service_keys)
    return event.data()


def verify_service_descriptor(
    descriptor_data: dict[str, Any],
    attestation_data: dict[str, Any],
    *,
    service_npub: str,
    management: str,
) -> Event:
    descriptor = _valid_event(descriptor_data, label="service descriptor")
    attestation = _valid_event(attestation_data, label="operator attestation")
    content = _content(descriptor, DESCRIPTOR_SCHEMA)
    service_hex, _ = normalize_public_key(service_npub, label="service")
    if descriptor.kind != ADDRESSABLE_APPLICATION_EVENT_KIND:
        raise CommissioningError("service descriptor has an unsupported event kind")
    if descriptor.pub_key != service_hex:
        raise CommissioningError("service descriptor was not signed by this service")
    if content.get("issued_at") != descriptor.created_at:
        raise CommissioningError("service descriptor issue time does not match its event")
    if content.get("management") != management:
        raise CommissioningError("service descriptor management mode does not match")
    if content.get("service") != {"pubkey": service_hex, "type": SERVICE_TYPE}:
        raise CommissioningError("service descriptor identity does not match")
    operator = content.get("operator")
    if operator != {
        "attestation_event_id": attestation.id,
        "pubkey": attestation.pub_key,
    }:
        raise CommissioningError("service descriptor operator evidence does not match")
    if content.get("state") != "commissioned":
        raise CommissioningError("service descriptor is not commissioned")
    _require_tag(descriptor, ["d", DESCRIPTOR_SCHEMA])
    _require_tag(
        descriptor,
        ["e", attestation.id, "", "operator-attestation"],
    )
    return descriptor


def _valid_event(event_data: dict[str, Any], *, label: str) -> Event:
    try:
        validate_event(event_data, verify_signature=True)
        event = Event.load(event_data, validate=True)
    except (StromaEventError, EventValidationError, TypeError, ValueError, KeyError) as exc:
        raise CommissioningError(f"{label} is not a valid Nostr event") from exc
    if event is None:
        raise CommissioningError(f"{label} signature is invalid")
    return event


def _content(event: Event, schema: str) -> dict[str, Any]:
    try:
        content = json.loads(event.content)
    except json.JSONDecodeError as exc:
        raise CommissioningError(f"{schema} content is not valid JSON") from exc
    if not isinstance(content, dict):
        raise CommissioningError(f"{schema} content must be a JSON object")
    if content.get("schema") != schema or content.get("schema_version") != 1:
        raise CommissioningError(f"unsupported {schema} schema")
    if canonical_json(content) != event.content:
        raise CommissioningError(f"{schema} content is not canonically encoded")
    return content


def _require_tag(event: Event, expected: list[str]) -> None:
    if expected not in event.tags.as_list():
        raise CommissioningError(f"event is missing required {expected[0]} tag")
