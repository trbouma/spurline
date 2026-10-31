from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from stroma import Event, Keys

from spurline.config import Settings
from spurline.main import create_app
from spurline.commissioning import (
    ADDRESSABLE_APPLICATION_EVENT_KIND,
    ATTESTATION_SCHEMA,
    SERVICE_TYPE,
    canonical_json,
    create_commissioning_request,
    create_service_descriptor,
    verify_operator_attestation,
    verify_service_descriptor,
)
from spurline.commissioning import CommissioningError

SERVICE_NSEC = "22" * 32
SERVICE_KEYS = Keys(priv_k=SERVICE_NSEC)
SERVICE_NPUB = SERVICE_KEYS.public_key_bech32()
OPERATOR_KEYS = Keys(priv_k="33" * 32)
OPERATOR_NPUB = OPERATOR_KEYS.public_key_bech32()
NOW = 1_788_700_000


def operator_attestation(request_data: dict, *, keys=OPERATOR_KEYS) -> dict:
    request = Event.load(request_data, validate=True)
    assert request is not None
    issued_at = request.created_at + 1
    content = {
        "action": "authorize",
        "commissioning_request": request.id,
        "installation": keys.public_key_hex(),
        "issued_at": issued_at,
        "management": "mainstay-managed",
        "previous": None,
        "relationship": "operates",
        "schema": ATTESTATION_SCHEMA,
        "schema_version": 1,
        "sequence": 1,
        "service": {
            "pubkey": SERVICE_KEYS.public_key_hex(),
            "type": SERVICE_TYPE,
        },
    }
    event = Event(
        kind=ADDRESSABLE_APPLICATION_EVENT_KIND,
        content=canonical_json(content),
        tags=[
            [
                "d",
                f"{ATTESTATION_SCHEMA}:{SERVICE_KEYS.public_key_hex()}",
            ],
            ["p", SERVICE_KEYS.public_key_hex(), "", "service"],
            ["e", request.id, "", "commissioning-request"],
            ["t", "mainstay-service-operator"],
            ["service-type", SERVICE_TYPE],
        ],
        created_at=issued_at,
    )
    event.sign(keys)
    return event.data()


def commissioning_request() -> dict:
    return create_commissioning_request(
        SERVICE_NSEC,
        OPERATOR_NPUB,
        "mainstay-managed",
        now=NOW,
        nonce="44" * 32,
    )


def test_reciprocal_commissioning_evidence_verifies() -> None:
    request = commissioning_request()
    attestation = operator_attestation(request)

    verified = verify_operator_attestation(
        request,
        attestation,
        service_npub=SERVICE_NPUB,
        management="mainstay-managed",
        now=NOW + 2,
    )
    descriptor = create_service_descriptor(
        SERVICE_NSEC,
        attestation,
        management="mainstay-managed",
        now=NOW + 2,
    )
    verified_descriptor = verify_service_descriptor(
        descriptor,
        attestation,
        service_npub=SERVICE_NPUB,
        management="mainstay-managed",
    )

    assert verified.operator_npub == OPERATOR_NPUB
    assert verified.request.id == request["id"]
    assert verified.attestation.id == attestation["id"]
    assert verified_descriptor.id == descriptor["id"]


def settings_for(tmp_path):
    return Settings(database_path=tmp_path / "relay.sqlite3", service_nsec=SERVICE_NSEC,
                    service_management="mainstay-managed")


def complete_service(settings):
    from spurline.service import ServiceCommissioning
    service = ServiceCommissioning(settings)
    request = service.request(OPERATOR_NPUB)["commissioning_request"]
    service.commission(operator_attestation(request))
    return service


def test_state_persists_and_public_discovery_updates(tmp_path):
    from spurline.service import ServiceCommissioning
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        assert client.get("/info").json()["service_identity"]["state"] == "uncommissioned"
        service = complete_service(settings)
        info = client.get("/info").json()["service_identity"]
        assert info["state"] == "commissioned"
        assert info["operator"] == OPERATOR_NPUB
        assert info["descriptor_event_id"] == service.verify()["service_descriptor_event_id"]
        public = client.get("/v1/service-identity").json()
        assert len(public["evidence"]) == 3
        assert SERVICE_NSEC not in json.dumps(public)
        assert "commissioned" in client.get("/", headers={"Accept": "text/html"}).text
        assert client.post("/v1/operator/service/request", json={}).status_code == 404
    with TestClient(create_app(settings)) as client:
        assert client.get("/info").json()["service_identity"]["state"] == "commissioned"
    assert ServiceCommissioning(settings).verify()["operator_npub"] == OPERATOR_NPUB


def test_pending_and_replay_guards(tmp_path):
    from spurline.service import ServiceCommissioning
    service = ServiceCommissioning(settings_for(tmp_path))
    with pytest.raises(CommissioningError, match="pending"):
        service.commission({})
    old = service.request(OPERATOR_NPUB)["commissioning_request"]
    current = service.request(OPERATOR_NPUB)["commissioning_request"]
    with pytest.raises(CommissioningError, match="does not match"):
        service.commission(operator_attestation(old))
    assert service.show()["state"] == "commissioning-pending"
    event = operator_attestation(current)
    service.commission(event)
    assert service.commission(event)["state"] == "commissioned"
    with pytest.raises(CommissioningError, match="already commissioned"):
        service.request(OPERATOR_NPUB)
    with pytest.raises(CommissioningError, match="already commissioned"):
        service.commission(operator_attestation(old))


def test_invalid_evidence_does_not_commission_even_with_relay_validation_disabled(tmp_path):
    from dataclasses import replace
    from spurline.service import ServiceCommissioning
    service = ServiceCommissioning(replace(settings_for(tmp_path), verify_signatures=False))
    request = service.request(OPERATOR_NPUB)["commissioning_request"]
    event = operator_attestation(request)
    event["sig"] = "00" * 64
    with pytest.raises(CommissioningError, match="valid Nostr event"):
        service.commission(event)
    assert service.show()["state"] == "commissioning-pending"


def test_identity_or_management_change_rejected(tmp_path):
    from dataclasses import replace
    from spurline.service import ServiceCommissioning
    settings = settings_for(tmp_path)
    complete_service(settings)
    with pytest.raises(RuntimeError, match="does not match"):
        ServiceCommissioning(replace(settings, service_nsec="55" * 32)).verify()
    with pytest.raises(CommissioningError, match="management"):
        ServiceCommissioning(replace(settings, service_management="independent")).verify()


def test_cli_uses_environment_and_reads_attestation(tmp_path, monkeypatch, capsys):
    import io
    from spurline.cli import main
    monkeypatch.setenv("SPURLINE_DATABASE", str(tmp_path / "relay.sqlite3"))
    monkeypatch.setenv("SPURLINE_SERVICE_NSEC", SERVICE_NSEC)
    monkeypatch.setenv("SPURLINE_SERVICE_MANAGEMENT", "mainstay-managed")
    monkeypatch.setattr("sys.argv", ["spurline", "service", "request", OPERATOR_NPUB])
    main()
    request = json.loads(capsys.readouterr().out)["commissioning_request"]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(operator_attestation(request))))
    monkeypatch.setattr("sys.argv", ["spurline", "service", "commission"])
    main()
    assert json.loads(capsys.readouterr().out)["state"] == "commissioned"
    monkeypatch.setattr("sys.argv", ["spurline", "service", "verify"])
    main()
    assert json.loads(capsys.readouterr().out)["operator_npub"] == OPERATOR_NPUB


def test_cli_publish_failure_is_nonzero_and_keeps_evidence(tmp_path, monkeypatch, capsys):
    from stroma import RelayError
    from spurline.cli import main
    settings = settings_for(tmp_path)
    service = complete_service(settings)
    monkeypatch.setenv("SPURLINE_DATABASE", str(settings.database_path))
    monkeypatch.setenv("SPURLINE_SERVICE_NSEC", SERVICE_NSEC)
    monkeypatch.setenv("SPURLINE_SERVICE_MANAGEMENT", "mainstay-managed")
    async def fail(*args, **kwargs):
        raise RelayError("relay rejected publication")
    monkeypatch.setattr("spurline.cli.publish_evidence", fail)
    monkeypatch.setattr("sys.argv", ["spurline", "service", "publish", "--relay", "wss://example.com"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "relay rejected" in capsys.readouterr().err
    assert service.verify()["state"] == "commissioned"


def test_attestation_from_another_operator_is_rejected() -> None:
    request = commissioning_request()
    attestation = operator_attestation(request, keys=Keys(priv_k="55" * 32))

    with pytest.raises(CommissioningError, match="requested operator"):
        verify_operator_attestation(
            request,
            attestation,
            service_npub=SERVICE_NPUB,
            management="mainstay-managed",
            now=NOW + 2,
        )


def test_attestation_for_another_service_is_rejected() -> None:
    request = commissioning_request()
    attestation = operator_attestation(request)
    event = Event.load(attestation)
    assert event is not None
    content = json.loads(event.content)
    content["service"]["pubkey"] = Keys(priv_k="66" * 32).public_key_hex()
    event.content = canonical_json(content)
    event.sign(OPERATOR_KEYS)

    with pytest.raises(CommissioningError, match="does not match the request"):
        verify_operator_attestation(
            request,
            event.data(),
            service_npub=SERVICE_NPUB,
            management="mainstay-managed",
            now=NOW + 2,
        )


def test_expired_request_is_rejected() -> None:
    request = commissioning_request()
    attestation = operator_attestation(request)

    with pytest.raises(CommissioningError, match="expired"):
        verify_operator_attestation(
            request,
            attestation,
            service_npub=SERVICE_NPUB,
            management="mainstay-managed",
            now=NOW + 24 * 60 * 60 + 1,
        )


def test_historical_attestation_remains_verifiable_after_request_expiry() -> None:
    request = commissioning_request()
    attestation = operator_attestation(request)

    verified = verify_operator_attestation(
        request,
        attestation,
        service_npub=SERVICE_NPUB,
        management="mainstay-managed",
        now=NOW + 365 * 24 * 60 * 60,
        require_current_request=False,
    )

    assert verified.attestation.id == attestation["id"]


@pytest.mark.parametrize("event", [None, [], {}, {"id": "bad"}])
def test_malformed_attestation_rejected(tmp_path, event):
    from spurline.service import ServiceCommissioning
    service = ServiceCommissioning(settings_for(tmp_path))
    service.request(OPERATOR_NPUB)
    with pytest.raises(CommissioningError):
        service.commission(event)
    assert service.show()["state"] == "commissioning-pending"


def test_corrupt_retained_evidence_fails_startup(tmp_path):
    settings = settings_for(tmp_path)
    service = complete_service(settings)
    with service.connection() as db:
        evidence = service._load(db)
        evidence["service_descriptor"]["content"] = "{}"
        service._write(db, evidence)
    with pytest.raises(CommissioningError):
        with TestClient(create_app(settings)):
            pass


def test_publish_verifiable_events_requires_all_relays(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from spurline.cli import publish_evidence
    evidence = complete_service(settings_for(tmp_path)).show()["evidence"]
    seen = []
    class Pool:
        def __init__(self, relays, timeout):
            assert timeout == 2
        async def publish(self, event, *, require):
            assert require == 2
            assert Event.load(event.data(), validate=True) is not None
            seen.append(event.id)
            return [SimpleNamespace(relay="ws://one"), SimpleNamespace(relay="ws://two")]
    monkeypatch.setattr("stroma.RelayPool", Pool)
    result = asyncio.run(publish_evidence(evidence, ["ws://one", "ws://two", "ws://one"], 2))
    assert result["state"] == "published"
    assert seen == [evidence[name]["id"] for name in
                    ("commissioning_request", "operator_attestation", "service_descriptor")]
