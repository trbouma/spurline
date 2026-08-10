from __future__ import annotations

import pytest

from spurline.events import EventValidationError, event_id, validate_event


def test_event_id_uses_nostr_canonical_payload() -> None:
    event = {
        "pubkey": "0" * 64,
        "created_at": 1,
        "kind": 1,
        "tags": [],
        "content": "hello",
    }

    assert event_id(event) == "a39ca3f39d0c087f87f7a94f431f81f6ebf9ec606d975703b687eb5f3929eef4"


def test_validate_event_rejects_mismatched_id() -> None:
    event = {
        "id": "0" * 64,
        "pubkey": "0" * 64,
        "created_at": 1,
        "kind": 1,
        "tags": [],
        "content": "hello",
        "sig": "0" * 128,
    }

    with pytest.raises(EventValidationError, match="id does not match"):
        validate_event(event, verify_signature=False)
