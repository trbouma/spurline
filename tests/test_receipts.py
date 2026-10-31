import json

import pytest
from stroma import Event, Keys

from spurline.commissioning import canonical_json, CommissioningError
from spurline.events import EventValidationError
from spurline.receipts import (
    WITNESS_KIND, RECEIPT_SCHEMA, SUBJECT_PROFILE, receipt_tags,
    signed_event_digest, verify_receipt,
)

AUTHOR = Keys(priv_k="11" * 32)
WITNESS = Keys(priv_k="22" * 32)


def example():
    subject = Event(kind=1415, content="fixture anchor", created_at=1700000000, tags=[])
    subject.sign(AUTHOR)
    subject = subject.data()
    body = {
        "schema": RECEIPT_SCHEMA, "schema_version": 1, "subject_profile": SUBJECT_PROFILE,
        "event_id": subject["id"], "signed_event_digest": signed_event_digest(subject),
        "observed_at_ms": 1700000001000, "issued_at_ms": 1700000002000,
        "clock_uncertainty_ms": 1000, "validation": "event-id-and-signature",
        "observation_mode": "live", "witness_policy_digest": "33" * 32,
        "authorization_event_id": "44" * 32,
    }
    return subject, body


def sign(subject, body, *, tags=None, kind=WITNESS_KIND):
    event = Event(kind=kind, content=canonical_json(body), tags=receipt_tags(subject) if tags is None else tags,
                  created_at=1700000002)
    event.sign(WITNESS)
    return event.data()


def test_receipt_profile_binding():
    subject, body = example()
    assert verify_receipt(sign(subject, body), subject) == body
    # Placeholder authority references do not confer trust: this is only wire validation.
    assert body["authorization_event_id"] == "44" * 32


def test_frozen_fixture():
    from pathlib import Path
    fixture = json.loads((Path(__file__).parent / "fixtures/observation-receipt-v1.json").read_text())
    assert verify_receipt(fixture["receipt"], fixture["subject"])["schema_version"] == 1


@pytest.mark.parametrize("change", [
    {"schema_version": True}, {"schema_version": 2}, {"observed_at_ms": -1},
    {"observed_at_ms": 1700000003000}, {"clock_uncertainty_ms": True},
    {"clock_uncertainty_ms": 2**53}, {"issued_at_ms": 1700000004000},
    {"authorization_event_id": "bad"}, {"extra": 1}, {"subject_profile": "pq"},
    {"signed_event_digest": "00" * 32}, {"observation_mode": "unknown"},
])
def test_malformed_signed_receipts(change):
    subject, body = example()
    body.update(change)
    with pytest.raises(CommissioningError):
        verify_receipt(sign(subject, body), subject)


def test_invalid_signature_and_duplicate_tags():
    subject, body = example()
    receipt = sign(subject, body)
    receipt["sig"] = "00" * 64
    with pytest.raises(EventValidationError):
        verify_receipt(receipt, subject)
    with pytest.raises(CommissioningError):
        verify_receipt(sign(subject, body, tags=receipt_tags(subject) * 2), subject)


def test_same_id_different_valid_signature_cannot_reuse_receipt():
    from coincurve import PrivateKey
    subject, body = example()
    receipt = sign(subject, body)
    other = dict(subject)
    other["sig"] = PrivateKey(bytes.fromhex("11" * 32)).sign_schnorr(
        bytes.fromhex(subject["id"]), aux_randomness=b"\x01" * 32).hex()
    assert other["sig"] != subject["sig"]
    assert other["id"] == subject["id"]
    assert signed_event_digest(other) != body["signed_event_digest"]
    with pytest.raises(CommissioningError, match="exact signed subject"):
        verify_receipt(receipt, other)
