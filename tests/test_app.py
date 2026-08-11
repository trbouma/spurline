from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from spurline import __version__
from spurline.config import Settings
from spurline.events import event_id
from spurline.main import create_app


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
