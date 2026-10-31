import json
import time
from dataclasses import replace

import pytest
from stroma import Event, Keys
from fastapi.testclient import TestClient

from spurline.automatic_witness import AutomaticWitness, ClockUnavailable, WitnessClock
from spurline.events import validate_event
from spurline.main import create_app
from spurline.receipts import signed_event_digest, verify_receipt
from spurline.store import EventStore
from spurline.witness import WitnessAuthorization
from test_commissioning import settings_for, complete_service
from test_witness import signed_authorization


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    clock = [1800000000.0]
    real_time, real_monotonic = time.time, time.monotonic
    wall_start, mono_start = real_time(), real_monotonic()
    monkeypatch.setattr('time.time', lambda: clock[0] + real_time() - wall_start)
    monkeypatch.setattr('time.monotonic', lambda: clock[0] + real_monotonic() - mono_start)
    settings = replace(settings_for(tmp_path), witness_enabled=True,
                       witness_clock_file=tmp_path / 'clock.json')
    complete_service(settings)
    policy = tmp_path / 'policy.txt'
    policy.write_text('Public test policy')
    authority = WitnessAuthorization(settings)
    authority.authorize(signed_authorization(authority.request(policy, valid_for=3600, kinds=[1415, 1416])))
    clock[0] += 2
    settings.witness_clock_file.write_text(json.dumps(dict(synchronized=True,
        checked_at_ms=int(clock[0]*1000), uncertainty_ms=10)))
    store = EventStore(settings.database_path)
    yield AutomaticWitness(settings, store), authority, clock
    store.close()


def subject(content='anchor', kind=1415):
    event = Event(kind=kind, content=content, tags=[], created_at=1700000000)
    event.sign(Keys(priv_k='11' * 32))
    return validate_event(event.data(), verify_signature=True)


def test_issue_deduplicate_and_restart(runtime):
    worker, _, clock = runtime
    event = subject()
    digest = signed_event_digest(event.to_dict())
    assert worker.accept(event)
    assert not worker.accept(event)
    original = json.loads(worker.store.witness_rows(digest)[0]['inputs'])
    clock[0] += 1
    restarted = AutomaticWitness(worker.settings, worker.store)
    restarted.issue(digest)
    row = worker.store.witness_rows(digest)[0]
    receipt = json.loads(row['receipt'])
    body = verify_receipt(receipt, event.to_dict())
    assert body['observed_at_ms'] == original['observed_at_ms']
    assert body['issued_at_ms'] > body['observed_at_ms']
    restarted.issue(digest)
    assert worker.store.witness_rows(digest)[0]['receipt'] == row['receipt']
    assert worker.store.query([{'kinds': [1418], '#e': [event.id]}])[0].id == receipt['id']
    assert restarted.status(digest)['state'] == 'issued'
    assert not worker.accept(event)


@pytest.mark.parametrize('change', ['suspend', 'revoke', 'renew', 'stale', 'deadline'])
def test_fail_closed_before_issuance(runtime, change, tmp_path):
    worker, authority, clock = runtime
    event = subject()
    digest = signed_event_digest(event.to_dict())
    worker.accept(event)
    if change == 'suspend':
        authority.control('suspend', 'test')
    elif change == 'revoke':
        from test_commissioning import OPERATOR_KEYS
        template = authority.revocation_request('test')['unsigned_revocation']
        signed = Event(kind=template['kind'], created_at=template['created_at'],
                       tags=template['tags'], content=template['content'])
        signed.sign(OPERATOR_KEYS)
        authority.revoke(signed.data())
    elif change == 'renew':
        policy = tmp_path / 'new-policy.txt'
        policy.write_text('new policy')
        authority.authorize(signed_authorization(authority.request(policy, valid_for=3600, kinds=[1415], renew=True)))
    else:
        clock[0] += 61 if change == 'deadline' else 31
        if change == 'deadline':
            worker.settings.witness_clock_file.write_text(json.dumps(dict(synchronized=True,
                checked_at_ms=int(clock[0]*1000), uncertainty_ms=10)))
    worker.issue(digest)
    assert worker.status(digest)['state'] == 'unavailable'
    assert worker.store.query([{'kinds': [1418]}]) == []


def test_queue_bound_and_nonrecursive(runtime):
    worker, _, _ = runtime
    worker.settings = replace(worker.settings, witness_queue_limit=1)
    worker.accept(subject('one'))
    second = subject('two')
    assert worker.accept(second)
    assert worker.status(signed_event_digest(second.to_dict()))['state'] == 'unavailable'
    assert worker.accept(subject('receipt-like', 1418))
    assert len(worker.store.witness_rows()) == 1


def test_unhealthy_and_invalid_signature_not_witnessed(runtime):
    worker, _, _ = runtime
    broken = subject().to_dict()
    broken['sig'] = '00' * 64
    assert worker.accept(validate_event(broken, verify_signature=False))
    assert not worker.store.witness_rows()
    worker.settings.witness_clock_file.unlink()
    assert worker.accept(subject('no clock'))
    assert not worker.store.witness_rows()


def test_atomic_subject_and_job_rollback(runtime, monkeypatch):
    worker, _, _ = runtime
    def fail(*args):
        raise RuntimeError('injected storage failure')
    monkeypatch.setattr(worker.store, '_index_tags', fail)
    with pytest.raises(RuntimeError):
        worker.accept(subject())
    assert not worker.store.witness_rows()
    assert not worker.store.query([{'kinds': [1415]}])


def test_clock_discontinuity_latches(runtime, monkeypatch):
    worker, _, clock = runtime
    worker.clock.sample()
    monkeypatch.setattr('time.monotonic', lambda: clock[0] - 1)
    with pytest.raises(ClockUnavailable):
        worker.clock.sample()
    monkeypatch.setattr('time.monotonic', lambda: clock[0])
    with pytest.raises(ClockUnavailable):
        worker.clock.sample()


def test_application_worker_publishes(runtime):
    worker, _, _ = runtime
    event = subject()
    digest = signed_event_digest(event.to_dict())
    with TestClient(create_app(worker.settings)) as client:
        with client.websocket_connect('/') as ws:
            ws.send_json(['REQ', 'witness', {'kinds': [1418], '#e': [event.id]}])
            assert ws.receive_json()[0] == 'EOSE'
            ws.send_json(['EVENT', event.to_dict()])
            assert ws.receive_json()[:3] == ['OK', event.id, True]
            received = ws.receive_json()
            assert received[:2] == ['EVENT', 'witness']
            verify_receipt(received[2], event.to_dict())
            assert client.get('/v1/witness-status/' + digest).json()['state'] == 'issued'


def test_alternative_valid_signature_has_separate_receipt(runtime):
    from coincurve import PrivateKey
    worker, _, _ = runtime
    first = subject()
    other = first.to_dict()
    other['sig'] = PrivateKey(bytes.fromhex('11' * 32)).sign_schnorr(
        bytes.fromhex(first.id), aux_randomness=b'\x01' * 32).hex()
    second = validate_event(other, verify_signature=True)
    worker.accept(first)
    assert not worker.accept(second)  # Same ordinary event ID, distinct signed observation.
    assert len(worker.store.witness_rows()) == 2
    for event in (first, second):
        digest = signed_event_digest(event.to_dict())
        worker.issue(digest)
        row = worker.store.witness_rows(digest)[0]
        verify_receipt(json.loads(row['receipt']), event.to_dict())
    assert len(worker.store.query([{'kinds': [1418], '#e': [first.id]}])) == 2


def test_receipt_commit_failure_keeps_job_pending(runtime, monkeypatch):
    worker, _, _ = runtime
    event = subject()
    worker.accept(event)
    digest = signed_event_digest(event.to_dict())
    original = worker.store._index_tags
    monkeypatch.setattr(worker.store, '_index_tags', lambda *args: (_ for _ in ()).throw(RuntimeError('failure')))
    with pytest.raises(RuntimeError):
        worker.issue(digest)
    assert worker.status(digest)['state'] == 'pending'
    assert not worker.store.query([{'kinds': [1418]}])
    monkeypatch.setattr(worker.store, '_index_tags', original)
    worker.issue(digest)
    assert worker.status(digest)['state'] == 'issued'


def test_disabled_default_and_required_configuration(tmp_path):
    settings = settings_for(tmp_path)
    assert settings.witness_enabled is False
    with pytest.raises(ValueError, match='clock|CLOCK'):
        replace(settings, witness_enabled=True)
    with TestClient(create_app(settings)) as client:
        assert client.get('/v1/witness-status/' + '00' * 32).json()['state'] == 'disabled'
        assert client.get('/info').json()['automatic_witness']['configured'] is False


def test_expired_authority_does_not_issue(runtime):
    worker, _, clock = runtime
    event = subject()
    worker.accept(event)
    clock[0] += 3600
    worker.issue(signed_event_digest(event.to_dict()))
    assert not worker.store.query([{'kinds': [1418]}])


def test_fresh_instance_without_authorization_still_accepts(tmp_path):
    settings = replace(settings_for(tmp_path), witness_enabled=True,
                       witness_clock_file=tmp_path / 'missing.json')
    store = EventStore(settings.database_path)
    try:
        worker = AutomaticWitness(settings, store)
        assert worker.accept(subject())
        assert not store.witness_rows()
    finally:
        store.close()
