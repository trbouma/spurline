from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spurline import __version__
from spurline.config import Settings
from spurline.events import event_id
from spurline.identity import fips_ipv6_address, service_npub
from spurline.main import create_app

SERVICE_NSEC = "11" * 32
SERVICE_NSEC_BECH32 = (
    "nsec1zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zygs4rm7hz"
)
SERVICE_NPUB = (
    "npub1fu64hh9hes90w2808n8tjc2ajp5yhddjef0ctx4s7zmsgp6cwx4qgy4eg9"
)
SERVICE_FIPS_IPV6_ADDRESS = "fd34:da5e:3969:3577:9c48:835a:7f60:8b56"


def test_health_response(tmp_path: Path) -> None:
    client = TestClient(create_test_app(tmp_path))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "spurline",
        "version": __version__,
    }


def test_info_response_includes_relay_metadata(tmp_path: Path) -> None:
    client = TestClient(create_test_app(tmp_path))

    response = client.get("/info")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Spurline"
    assert body["software"] == "spurline"
    assert body["supported_nips"] == [1]
    assert body["relay"]["websocket_url"] == "ws://127.0.0.1:8080"
    assert body["service_identity"]["state"] == "unconfigured"


def test_info_response_uses_public_relay_url(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            database_path=tmp_path / "relay.sqlite3",
            public_url="wss://relay.example.com",
        )
    )
    client = TestClient(app)

    response = client.get("/info")

    assert response.status_code == 200
    assert response.json()["relay"]["websocket_url"] == "wss://relay.example.com"


def test_browser_homepage_is_friendly_and_keeps_json_api(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            database_path=tmp_path / "relay.sqlite3",
            public_url="wss://spurline.example",
        )
    )
    client = TestClient(app)

    homepage = client.get("/", headers={"Accept": "text/html"})
    information = client.get("/", headers={"Accept": "application/nostr+json"})
    logo = client.get("/assets/spurline-logo.svg")

    assert homepage.status_code == 200
    assert homepage.headers["content-type"].startswith("text/html")
    assert "Spurline" in homepage.text
    assert "wss://spurline.example" in homepage.text
    assert "Copy relay URL" in homepage.text
    assert "Local-first Nostr infrastructure" in homepage.text
    assert information.status_code == 200
    assert information.json()["software"] == "spurline"
    assert logo.status_code == 200
    assert logo.headers["content-type"].startswith("image/svg+xml")


def test_service_identity_accepts_hex_and_nsec_encoding() -> None:
    assert service_npub(SERVICE_NSEC) == SERVICE_NPUB
    assert service_npub(SERVICE_NSEC_BECH32) == SERVICE_NPUB
    assert fips_ipv6_address(SERVICE_NPUB) == SERVICE_FIPS_IPV6_ADDRESS


def test_service_identity_is_reported_and_bound_to_relay_data(tmp_path: Path) -> None:
    configured = Settings(
        database_path=tmp_path / "data" / "spurline.sqlite3",
        service_nsec=SERVICE_NSEC,
    )
    with TestClient(create_app(configured)) as client:
        information = client.get("/info")
        homepage = client.get("/", headers={"Accept": "text/html"})

    assert information.json()["service_identity"] == {
        "npub": SERVICE_NPUB,
        "fips_ipv6_address": SERVICE_FIPS_IPV6_ADDRESS,
        "type": "nostr-relay",
        "management": "independent",
        "state": "uncommissioned",
        "descriptor_event_id": None,
        "operator": None,
    }
    assert "Service identity" in homepage.text
    assert SERVICE_NPUB in homepage.text
    assert "FIPS IPv6 address" in homepage.text
    assert SERVICE_FIPS_IPV6_ADDRESS in homepage.text
    assert "Management" in homepage.text
    assert "independent" in homepage.text
    assert "Identity state" in homepage.text
    assert "uncommissioned" in homepage.text
    assert 'href="health"' in homepage.text
    assert 'href="/health"' not in homepage.text
    sentinel = json.loads(
        (configured.database_path.parent / "service-identity.json").read_text(
            encoding="utf-8"
        )
    )
    assert sentinel["npub"] == SERVICE_NPUB
    assert SERVICE_NSEC not in information.text


def test_service_identity_cannot_change_for_existing_relay_data(tmp_path: Path) -> None:
    database_path = tmp_path / "data" / "spurline.sqlite3"
    with TestClient(
        create_app(Settings(database_path=database_path, service_nsec=SERVICE_NSEC))
    ):
        pass

    app = create_app(Settings(database_path=database_path, service_nsec="22" * 32))
    with (
        pytest.raises(RuntimeError, match="does not match the recorded"),
        TestClient(app),
    ):
        pass


def test_recorded_service_identity_requires_private_key(tmp_path: Path) -> None:
    database_path = tmp_path / "data" / "spurline.sqlite3"
    with TestClient(
        create_app(Settings(database_path=database_path, service_nsec=SERVICE_NSEC))
    ):
        pass

    app = create_app(Settings(database_path=database_path))
    with (
        pytest.raises(RuntimeError, match="SPURLINE_SERVICE_NSEC is required"),
        TestClient(app),
    ):
        pass


def test_mainstay_managed_service_requires_private_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires SPURLINE_SERVICE_NSEC"):
        Settings(
            database_path=tmp_path / "relay.sqlite3",
            service_management="mainstay-managed",
        )


def test_websocket_replays_matching_events(tmp_path: Path) -> None:
    client = TestClient(create_test_app(tmp_path, verify_signatures=False))
    event = {
        "pubkey": "0" * 64,
        "created_at": 1,
        "kind": 1,
        "tags": [["p", "friend"]],
        "content": "hello",
        "sig": "0" * 128,
    }
    event["id"] = event_id(event)

    with client.websocket_connect("/") as websocket:
        websocket.send_text(json.dumps(["EVENT", event]))
        assert websocket.receive_json() == ["OK", event["id"], True, ""]

        websocket.send_text(json.dumps(["REQ", "sub-1", {"#p": ["friend"]}]))
        assert websocket.receive_json() == ["EVENT", "sub-1", event]
        assert websocket.receive_json() == ["EOSE", "sub-1"]


def create_test_app(tmp_path: Path, *, verify_signatures: bool = True):
    return create_app(
        Settings(
            database_path=tmp_path / "relay.sqlite3",
            verify_signatures=verify_signatures,
        )
    )
