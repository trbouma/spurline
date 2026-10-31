import hashlib
import io
import json
import time

import pytest
from fastapi.testclient import TestClient
from stroma import Event, Keys

from spurline.cli import main
from spurline.commissioning import CommissioningError, canonical_json
from spurline.main import create_app
from spurline.witness import WitnessAuthorization
from test_commissioning import (
    SERVICE_NSEC, OPERATOR_KEYS, complete_service, settings_for,
)


@pytest.fixture
def configured(tmp_path):
    settings = settings_for(tmp_path)
    complete_service(settings)
    policy = tmp_path / "policy.txt"
    policy.write_bytes(b"Public witness policy\r\nTest clock requirements.\r\n")
    return settings, policy


def signed_authorization(result, *, keys=OPERATOR_KEYS, change=None):
    template = result["unsigned_authorization"]
    content = json.loads(template["content"])
    if change:
        content.update(change)
    event = Event(kind=template["kind"], created_at=template["created_at"],
                  content=canonical_json(content), tags=template["tags"])
    event.sign(keys)
    return event.data()


def test_authorize_persist_discover_and_expire(configured, monkeypatch):
    settings, policy = configured
    witness = WitnessAuthorization(settings)
    result = witness.request(policy, valid_for=3600, kinds=[1415, 1416])
    assert result["state"] == "pending"
    assert result["policy_sha256"] == hashlib.sha256(policy.read_bytes()).hexdigest()
    event = signed_authorization(result)
    authorized = witness.authorize(event)
    assert authorized["state"] == "authorized"
    assert authorized["receipt_issuance_enabled"] is False
    assert witness.authorize(event) == authorized
    with TestClient(create_app(settings)) as client:
        info = client.get("/info").json()["witness_authorization"]
        assert info["authorization_event_id"] == event["id"]
        assert "evidence" not in info
        evidence = client.get("/v1/witness-authorization").json()
        assert evidence == {key: value for key, value in authorized.items() if key != "local_controls"}
        assert SERVICE_NSEC not in json.dumps(evidence)
    assert WitnessAuthorization(settings).verify()["evidence_verified"]
    monkeypatch.setattr("time.time", lambda: result["not_after"])
    assert witness.verify()["state"] == "expired"
    assert witness.show()["evidence"]["authorization"] == event
    with pytest.raises(CommissioningError, match="renewal"):
        witness.request(policy, valid_for=3600, kinds=[1415])


def test_uncommissioned_cannot_request(tmp_path):
    policy = tmp_path / "policy.txt"
    policy.write_text("public policy")
    with pytest.raises(CommissioningError, match="not commissioned"):
        WitnessAuthorization(settings_for(tmp_path)).request(policy, valid_for=3600, kinds=[1415])


@pytest.mark.parametrize("change", [
    {"role": "something-else"}, {"policy_sha256": "00" * 32},
    {"subject_kinds": [1]}, {"commissioning_attestation": "00" * 32},
    {"not_after": 1}, {"request_event_id": "00" * 32},
    {"sequence": True}, {"service": {"pubkey": "00" * 32, "type": "nostr-relay"}},
])
def test_operator_cannot_change_requested_terms(configured, change):
    settings, policy = configured
    witness = WitnessAuthorization(settings)
    result = witness.request(policy, valid_for=3600, kinds=[1415])
    with pytest.raises(CommissioningError, match="does not match"):
        witness.authorize(signed_authorization(result, change=change))
    assert witness.show()["state"] == "pending"


def test_wrong_operator_and_tampered_signature(configured):
    settings, policy = configured
    witness = WitnessAuthorization(settings)
    result = witness.request(policy, valid_for=3600, kinds=[1415])
    with pytest.raises(CommissioningError, match="commissioned operator"):
        witness.authorize(signed_authorization(result, keys=Keys(priv_k="77" * 32)))
    event = signed_authorization(result)
    event["sig"] = "00" * 64
    with pytest.raises(CommissioningError, match="valid Nostr"):
        witness.authorize(event)


def test_expired_request_and_stale_request(configured, monkeypatch):
    settings, policy = configured
    witness = WitnessAuthorization(settings)
    first = witness.request(policy, valid_for=3600, kinds=[1415])
    event = signed_authorization(first)
    second = witness.request(policy, valid_for=3600, kinds=[1415])
    with pytest.raises(CommissioningError, match="does not match"):
        witness.authorize(event)
    event = signed_authorization(second)
    monkeypatch.setattr("time.time", lambda: second["not_after"])
    assert witness.show()["state"] == "request-expired"
    with pytest.raises(CommissioningError, match="expired"):
        witness.authorize(event)


@pytest.mark.parametrize("duration,kinds", [(0, [1415]), (31536001, [1415]), (True, [1415]), (3600, [1]), (3600, [])])
def test_invalid_request_parameters(configured, duration, kinds):
    settings, policy = configured
    with pytest.raises(CommissioningError):
        WitnessAuthorization(settings).request(policy, valid_for=duration, kinds=kinds)


def test_policy_tampering_fails_verification(configured):
    settings, policy = configured
    witness = WitnessAuthorization(settings)
    result = witness.request(policy, valid_for=3600, kinds=[1415])
    witness.authorize(signed_authorization(result))
    with witness.service.connection() as db:
        evidence = witness._load(db)
        evidence["policy"] += "Changed"
        witness._write(db, evidence)
    with pytest.raises(CommissioningError, match="policy"):
        witness.verify()


def test_cli_roundtrip_and_publication(configured, monkeypatch, capsys):
    settings, policy = configured
    monkeypatch.setenv("SPURLINE_DATABASE", str(settings.database_path))
    monkeypatch.setenv("SPURLINE_SERVICE_NSEC", SERVICE_NSEC)
    monkeypatch.setenv("SPURLINE_SERVICE_MANAGEMENT", "mainstay-managed")
    monkeypatch.setattr("sys.argv", ["spurline", "service", "witness", "request", "--policy", str(policy), "--valid-for", "3600"])
    main()
    request = json.loads(capsys.readouterr().out)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(signed_authorization(request))))
    monkeypatch.setattr("sys.argv", ["spurline", "service", "witness", "authorize"])
    main()
    assert json.loads(capsys.readouterr().out)["state"] == "authorized"
    monkeypatch.setattr("sys.argv", ["spurline", "service", "witness", "verify"])
    main()
    assert json.loads(capsys.readouterr().out)["evidence_verified"]
    calls = []
    async def publish(evidence, relays, timeout, *, names):
        calls.append((evidence, relays, names))
        return {"state": "published"}
    monkeypatch.setattr("spurline.cli.publish_evidence", publish)
    monkeypatch.setattr("sys.argv", ["spurline", "service", "witness", "publish", "--relay", "ws://localhost:8080"])
    main()
    assert json.loads(capsys.readouterr().out)["state"] == "published"
    assert calls[0][2] == ("0:request", "0:authorization")


def test_existing_commissioning_without_witness_table_works(configured):
    settings, _ = configured
    status = WitnessAuthorization(settings).show()
    assert status["state"] == "not-authorized"
    assert status["receipt_issuance_enabled"] is False
