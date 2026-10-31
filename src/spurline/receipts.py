"""Experimental observation receipt v1 wire checks, not witness trust evaluation.

Signing and automatic issuance are implemented separately in automatic_witness.
"""

from __future__ import annotations

import hashlib
import json

from .commissioning import CommissioningError, canonical_json
from .events import validate_event

WITNESS_KIND = 1418  # Experimental local allocation, not a registered NIP.
RECEIPT_SCHEMA = "org.spurline.observation-receipt"
RECEIPT_MARKER = "spurline-observation-receipt-v1"
SUBJECT_PROFILE = "nostr-schnorr-secp256k1-v1"
DOMAIN = b"spurline.observed-signed-event.v1\x00"
MAX_SAFE_INTEGER = 2**53 - 1


def signed_event_digest(subject):
    """Commit to a verified classical event ID AND its exact signature."""
    validate_event(subject, verify_signature=True)
    for name in ("kind", "created_at"):
        value = subject[name]
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_SAFE_INTEGER:
            raise CommissioningError("subject kind and time must be nonnegative integers")
    return hashlib.sha256(DOMAIN + bytes.fromhex(subject["id"]) + bytes.fromhex(subject["sig"])).hexdigest()


def receipt_tags(subject):
    return [["e", subject["id"]], ["p", subject["pubkey"]],
            ["k", str(subject["kind"])], ["t", RECEIPT_MARKER]]


def verify_receipt(receipt, subject):
    """Return a structurally/cryptographically valid body; does NOT accept its time.

    Callers must separately validate commissioning, complete lifecycle evidence,
    policy, time bounds and their recognition of the commissioning authority.
    """
    validate_event(receipt, verify_signature=True)
    digest = signed_event_digest(subject)
    if not isinstance(receipt["kind"], int) or isinstance(receipt["kind"], bool) or receipt["kind"] != WITNESS_KIND:
        raise CommissioningError("unsupported receipt kind")
    if not isinstance(subject["kind"], int) or isinstance(subject["kind"], bool) or subject["kind"] not in (1415, 1416):
        raise CommissioningError("unsupported receipt subject kind")
    try:
        body = json.loads(receipt["content"])
    except (TypeError, ValueError) as exc:
        raise CommissioningError("invalid receipt JSON") from exc
    fields = {"schema", "schema_version", "subject_profile", "event_id", "signed_event_digest",
              "observed_at_ms", "issued_at_ms", "clock_uncertainty_ms", "validation",
              "observation_mode", "witness_policy_digest", "authorization_event_id"}
    if not isinstance(body, dict) or set(body) != fields or canonical_json(body) != receipt["content"]:
        raise CommissioningError("receipt fields or canonical encoding do not match v1")
    if (body["schema"] != RECEIPT_SCHEMA or type(body["schema_version"]) is not int
            or body["schema_version"] != 1 or body["subject_profile"] != SUBJECT_PROFILE
            or body["validation"] != "event-id-and-signature"
            or body["observation_mode"] not in ("live", "backfill")):
        raise CommissioningError("unsupported receipt profile")
    for name in ("observed_at_ms", "issued_at_ms", "clock_uncertainty_ms"):
        if type(body[name]) is not int or not 0 <= body[name] <= MAX_SAFE_INTEGER:
            raise CommissioningError("receipt times must be nonnegative safe integers")
    if (body["observed_at_ms"] > body["issued_at_ms"]
            or body["observed_at_ms"] + body["clock_uncertainty_ms"] > MAX_SAFE_INTEGER
            or not isinstance(receipt["created_at"], int) or isinstance(receipt["created_at"], bool)
            or receipt["created_at"] != body["issued_at_ms"] // 1000):
        raise CommissioningError("inconsistent receipt times")
    for name in ("witness_policy_digest", "authorization_event_id"):
        value = body[name]
        if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise CommissioningError("invalid receipt evidence reference")
    if (body["event_id"] != subject["id"] or body["signed_event_digest"] != digest
            or receipt["tags"] != receipt_tags(subject)):
        raise CommissioningError("receipt does not bind this exact signed subject")
    return body
