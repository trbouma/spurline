import json
import time

import pytest
from stroma import Event, Keys
from fastapi.testclient import TestClient

from spurline.commissioning import CommissioningError, canonical_json
from spurline.main import create_app
from spurline.witness import WitnessAuthorization
from test_commissioning import OPERATOR_KEYS, complete_service, settings_for
from test_witness import signed_authorization


@pytest.fixture
def lifecycle(tmp_path):
    settings = settings_for(tmp_path)
    complete_service(settings)
    policy = tmp_path / "policy"
    policy.write_text("Public clock and retention policy")
    witness = WitnessAuthorization(settings)
    request = witness.request(policy, valid_for=3600, kinds=[1415, 1416])
    first = signed_authorization(request)
    witness.authorize(first)
    return witness, policy, first


def sign_template(template, *, keys=OPERATOR_KEYS, changes=None):
    body = json.loads(template["content"])
    body.update(changes or {})
    event = Event(kind=template["kind"], created_at=template["created_at"],
                  content=canonical_json(body), tags=template["tags"])
    event.sign(keys)
    return event.data()


def revoke(witness):
    event = sign_template(witness.revocation_request("operator maintenance")["unsigned_revocation"])
    return event, witness.revoke(event)


def test_renew_preserves_old_authority_until_accepted(lifecycle):
    witness, policy, first = lifecycle
    request = witness.request(policy, valid_for=7200, kinds=[1415], renew=True)
    assert witness.show()["authorization_event_id"] == first["id"]
    assert witness.show()["state"] == "authorized"
    assert witness.show()["pending_status"]["state"] == "pending"
    renewal = signed_authorization(request)
    state = witness.authorize(renewal)
    assert state["sequence"] == 2
    assert state["head_event_id"] == renewal["id"]
    assert state["subject_kinds"] == [1415]
    assert state["history"][0]["authorization"] == first
    assert state["pending"] is None
    # Replaying earlier accepted evidence must not roll back the head.
    assert witness.authorize(first)["head_event_id"] == renewal["id"]


def test_revoke_clears_pending_and_requires_explicit_renewal(lifecycle):
    witness, policy, first = lifecycle
    request = witness.request(policy, valid_for=7200, kinds=[1415], renew=True)
    stale = signed_authorization(request)
    event, state = revoke(witness)
    assert state["state"] == "revoked"
    assert not state["witnessing_permitted"]
    assert state["pending"] is None
    assert witness.revoke(event)["sequence"] == 2
    with pytest.raises(CommissioningError):
        witness.authorize(stale)
    with pytest.raises(CommissioningError):
        witness.control("resume", "cannot override revocation")
    renewal_request = witness.request(policy, valid_for=7200, kinds=[1415], renew=True)
    assert json.loads(renewal_request["evidence"]["request"]["content"])["previous"] == event["id"]
    restored = witness.authorize(signed_authorization(renewal_request))
    assert restored["sequence"] == 3
    assert restored["state"] == "authorized"
    assert restored["history"][1]["revocation"] == event


def test_suspension_persists_through_renewal_and_restart(lifecycle):
    witness, policy, _ = lifecycle
    witness.control("suspend", "private operational reason")
    renewed = witness.request(policy, valid_for=7200, kinds=[1415], renew=True)
    state = witness.authorize(signed_authorization(renewed))
    assert state["state"] == "suspended"
    assert state["authorization_state"] == "authorized"
    assert not state["witnessing_permitted"]
    fresh = WitnessAuthorization(witness.settings)
    assert fresh.show()["state"] == "suspended"
    with TestClient(create_app(witness.settings)) as client:
        assert "private operational reason" not in client.get("/info").text
        assert "private operational reason" not in client.get("/v1/witness-authorization").text
    state = fresh.control("resume", "clock health independently restored")
    assert state["state"] == "authorized"
    assert state["witnessing_permitted"]
    assert not state["receipt_issuance_enabled"]
    assert len(state["local_controls"]) == 2


def test_expired_grant_cannot_resume_but_can_renew(lifecycle, monkeypatch):
    witness, policy, _ = lifecycle
    witness.control("suspend", "maintenance")
    end = witness.show()["not_after"]
    monkeypatch.setattr("time.time", lambda: end)
    with pytest.raises(CommissioningError, match="currently valid"):
        witness.control("resume", "attempt")
    result = witness.request(policy, valid_for=7200, kinds=[1415], renew=True)
    assert witness.authorize(signed_authorization(result))["state"] == "suspended"


@pytest.mark.parametrize("changes", [{"previous": "00" * 32}, {"sequence": 99},
                                     {"effective_at": 1}, {"role": "other"}])
def test_invalid_revocations_roll_back(lifecycle, changes):
    witness, _, first = lifecycle
    template = witness.revocation_request("review")["unsigned_revocation"]
    with pytest.raises(CommissioningError):
        witness.revoke(sign_template(template, changes=changes))
    assert witness.show()["head_event_id"] == first["id"]
    assert witness.show()["sequence"] == 1


def test_wrong_signer_and_conflicting_revocation(lifecycle):
    witness, _, first = lifecycle
    template = witness.revocation_request("review")["unsigned_revocation"]
    with pytest.raises(CommissioningError):
        witness.revoke(sign_template(template, keys=Keys(priv_k="88" * 32)))
    witness.revoke(sign_template(template))
    with pytest.raises(CommissioningError):
        witness.revoke(sign_template(template, changes={"reason": "different signed fork"}))
    assert witness.show()["sequence"] == 2


def test_legacy_authorization_migration(lifecycle):
    witness, policy, first = lifecycle
    with witness.service.connection() as db:
        db.execute("DROP TABLE witness_history")
    assert witness.verify()["history"][0]["authorization"] == first
    result = witness.request(policy, valid_for=7200, kinds=[1415], renew=True)
    state = witness.authorize(signed_authorization(result))
    assert state["history"][0]["authorization"] == first
    assert state["sequence"] == 2


def test_history_tampering_detected(lifecycle):
    witness, policy, _ = lifecycle
    request = witness.request(policy, valid_for=7200, kinds=[1415], renew=True)
    witness.authorize(signed_authorization(request))
    with witness.service.connection() as db:
        db.execute("DELETE FROM witness_history WHERE sequence=1")
    with pytest.raises(CommissioningError, match="gap"):
        witness.verify()


def test_cli_lifecycle_commands(lifecycle, monkeypatch, capsys):
    import io
    from spurline.cli import main
    from test_commissioning import SERVICE_NSEC
    witness, policy, _ = lifecycle
    monkeypatch.setenv("SPURLINE_DATABASE", str(witness.settings.database_path))
    monkeypatch.setenv("SPURLINE_SERVICE_NSEC", SERVICE_NSEC)
    monkeypatch.setenv("SPURLINE_SERVICE_MANAGEMENT", "mainstay-managed")
    def run(*args):
        monkeypatch.setattr("sys.argv", ["spurline", "service", "witness", *args])
        main()
        return json.loads(capsys.readouterr().out)
    assert run("suspend", "--reason", "check")["state"] == "suspended"
    request = run("renew", "--policy", str(policy), "--valid-for", "7200")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(signed_authorization(request))))
    assert run("authorize")["state"] == "suspended"
    assert run("resume", "--reason", "checked")["state"] == "authorized"
    template = run("revocation-request", "--reason", "withdraw")["unsigned_revocation"]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(sign_template(template))))
    assert run("revoke")["state"] == "revoked"
    assert run("history")["sequence"] == 3
    sent = []
    async def publish(evidence, relays, timeout, *, names):
        sent.extend(evidence[name] for name in names)
        return {"state": "published"}
    monkeypatch.setattr("spurline.cli.publish_evidence", publish)
    assert run("publish", "--relay", "ws://localhost:8080")["state"] == "published"
    assert len(sent) == 5  # Two requests, two grants, one revocation.


def test_concurrent_reimport_is_idempotent(lifecycle):
    from concurrent.futures import ThreadPoolExecutor
    witness, policy, _ = lifecycle
    request = witness.request(policy, valid_for=7200, kinds=[1415], renew=True)
    event = signed_authorization(request)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: WitnessAuthorization(witness.settings).authorize(event), range(2)))
    assert all(result["sequence"] == 2 for result in results)
    assert witness.verify()["sequence"] == 2
