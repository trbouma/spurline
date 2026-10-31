import json
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from spurline.automatic_witness import AutomaticWitness, WitnessClock, ClockUnavailable, SYSTEM_POLICY_MARKER
from spurline.commissioning import CommissioningError
from spurline.main import create_app
from spurline.receipts import receipt_tags, verify_receipt, signed_event_digest
from test_automatic_witness import runtime, subject
from test_receipts import example, sign
from test_witness import signed_authorization


def system_worker(worker, authority, tmp_path):
    policy = tmp_path / 'system-policy.txt'
    policy.write_text(SYSTEM_POLICY_MARKER + '\nUnverified local clock, unspecified accuracy.\n')
    authority.authorize(signed_authorization(authority.request(
        policy, valid_for=3600, kinds=[1415, 1416], renew=True)))
    return AutomaticWitness(replace(worker.settings, witness_clock_mode='system',
                                    witness_clock_file=None), worker.store)


def test_system_clock_never_reads_health_file():
    class Unreadable:
        def open(self, *args):
            raise AssertionError('system mode must not read a health file')
    before = int(time.time() * 1000)
    now, bound = WitnessClock(Unreadable(), 'system').sample()
    assert before <= now <= int(time.time() * 1000)
    assert bound is None


def test_system_worker_without_file_publishes(runtime, tmp_path):
    worker, authority, _ = runtime
    worker = system_worker(worker, authority, tmp_path)
    event = subject()
    with TestClient(create_app(worker.settings)) as client:
        info = client.get('/info').json()['automatic_witness']
        assert info['clock_health_required'] is False
        assert info['clock_mode'] == 'system'
        assert info['receipt_version'] == 3
        with client.websocket_connect('/') as ws:
            ws.send_json(['REQ', 'receipt', {'kinds': [1418], '#e': [event.id]}])
            assert ws.receive_json()[0] == 'EOSE'
            ws.send_json(['EVENT', event.to_dict()])
            assert ws.receive_json()[:3] == ['OK', event.id, True]
            receipt = ws.receive_json()[2]
            body = verify_receipt(receipt, event.to_dict())
            assert body['clock_uncertainty_ms'] is None
            assert body['clock_basis'] == 'system-clock'
            assert body['clock_accuracy'] == 'unspecified'


@pytest.mark.parametrize('change', [dict(clock_basis='ntp-synchronized-system-clock'),
    dict(clock_uncertainty_ms=0), dict(clock_accuracy='precise'), dict(schema_version=2)])
def test_system_receipt_cannot_claim_synchronization(change):
    event, body = example()
    body.update(schema_version=3, clock_uncertainty_ms=None, clock_accuracy='unspecified',
                clock_basis='system-clock')
    body.update(change)
    with pytest.raises(CommissioningError):
        verify_receipt(sign(event, body, tags=receipt_tags(event, 3)), event)


def test_system_clock_step_latches(runtime, tmp_path, monkeypatch):
    worker, authority, clock = runtime
    worker = system_worker(worker, authority, tmp_path)
    worker.clock.sample()
    monkeypatch.setattr('time.monotonic', lambda: clock[0] - 1)
    with pytest.raises(ClockUnavailable):
        worker.clock.sample()
    assert worker.accept(subject())  # Normal storage continues.
    assert not worker.store.witness_rows()


def test_existing_authorization_does_not_silently_allow_system_clock(runtime):
    worker, _, _ = runtime
    worker = AutomaticWitness(replace(worker.settings, witness_clock_mode='system',
                                       witness_clock_file=None), worker.store)
    assert worker.accept(subject())
    assert not worker.store.witness_rows()


def test_restart_preserves_system_receipt(runtime, tmp_path):
    worker, authority, _ = runtime
    worker = system_worker(worker, authority, tmp_path)
    event = subject()
    digest = signed_event_digest(event.to_dict())
    worker.accept(event)
    restart = AutomaticWitness(worker.settings, worker.store)
    restart.issue(digest)
    row = worker.store.witness_rows(digest)[0]
    restart.issue(digest)
    assert restart.store.witness_rows(digest)[0]['receipt'] == row['receipt']
    assert verify_receipt(json.loads(row['receipt']), event.to_dict())['schema_version'] == 3


def test_suspension_still_blocks_system_issuance(runtime, tmp_path):
    worker, authority, _ = runtime
    worker = system_worker(worker, authority, tmp_path)
    event = subject()
    worker.accept(event)
    authority.control('suspend', 'test')
    digest = signed_event_digest(event.to_dict())
    worker.issue(digest)
    assert worker.status(digest)['state'] == 'unavailable'


def test_pending_mode_changes_and_conflicting_policy_markers(runtime, tmp_path):
    worker, authority, _ = runtime
    worker = system_worker(worker, authority, tmp_path)
    event = subject()
    worker.accept(event)
    from test_operational_clock import operational_health
    clock_file = tmp_path / 'clock.json'
    clock_file.write_text(json.dumps(operational_health(time.time())))
    switched = AutomaticWitness(replace(worker.settings, witness_clock_mode='operational',
                                         witness_clock_file=clock_file), worker.store)
    digest = signed_event_digest(event.to_dict())
    switched.issue(digest)
    assert switched.status(digest)['state'] == 'unavailable'
    view = authority.show()
    view['evidence']['policy'] += '\nSpurline-Clock-Profile: operational-v1\n'
    assert not worker._policy_allows_mode(view)


def test_system_settings_still_require_key(runtime):
    worker, _, _ = runtime
    settings = replace(worker.settings, witness_clock_mode='system', witness_clock_file=None)
    assert settings.witness_enabled
    with pytest.raises(ValueError, match='service key'):
        replace(settings, service_nsec=None)
