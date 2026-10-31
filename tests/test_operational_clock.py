import json
import os
import subprocess
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from spurline import clock_monitor
from spurline.automatic_witness import AutomaticWitness, ClockUnavailable, WitnessClock, OPERATIONAL_POLICY_MARKER
from spurline.commissioning import CommissioningError
from spurline.main import create_app
from spurline.receipts import receipt_tags, signed_event_digest, verify_receipt
from test_automatic_witness import runtime, subject
from test_receipts import example, sign
from test_witness import signed_authorization


def operational_health(now):
    return dict(mode='operational', source='systemd-timesyncd', synchronized=True,
                checked_at_ms=int(now * 1000), uncertainty_ms=None,
                last_sync_at_ms=int((now - 2100) * 1000))


def enable_operational(worker, authority, tmp_path):
    policy = tmp_path / 'operational.txt'
    policy.write_text(OPERATIONAL_POLICY_MARKER + '\nNo precision guarantee.\n')
    authority.authorize(signed_authorization(authority.request(
        policy, valid_for=3600, kinds=[1415, 1416], renew=True)))
    worker.settings.witness_clock_file.write_text(json.dumps(operational_health(time.time())))
    return AutomaticWitness(replace(worker.settings, witness_clock_mode='operational'), worker.store)


def test_v2_explicit_unspecified_accuracy():
    event, body = example()
    body.update(schema_version=2, clock_uncertainty_ms=None, clock_accuracy='unspecified',
                clock_basis='ntp-synchronized-system-clock')
    receipt = sign(event, body, tags=receipt_tags(event, 2))
    assert verify_receipt(receipt, event) == body


@pytest.mark.parametrize('change', [dict(clock_uncertainty_ms=0), dict(clock_uncertainty_ms=1000),
    dict(clock_uncertainty_ms=False), dict(clock_accuracy='precise'), dict(clock_basis='author-clock'),
    dict(schema_version=1), dict(schema_version=True), dict(schema_version=3)])
def test_v2_rejects_conflicting_accuracy(change):
    event, body = example()
    body.update(schema_version=2, clock_uncertainty_ms=None, clock_accuracy='unspecified',
                clock_basis='ntp-synchronized-system-clock')
    body.update(change)
    with pytest.raises(CommissioningError):
        verify_receipt(sign(event, body, tags=receipt_tags(event, 2)), event)


def test_v1_does_not_accept_unknown_and_version_tags_are_strict():
    event, body = example()
    body['clock_uncertainty_ms'] = None
    with pytest.raises(CommissioningError):
        verify_receipt(sign(event, body), event)
    body.update(schema_version=2, clock_accuracy='unspecified', clock_basis='ntp-synchronized-system-clock')
    with pytest.raises(CommissioningError, match='exact signed subject'):
        verify_receipt(sign(event, body), event)


def test_operational_receipt_persists_and_verifies(runtime, tmp_path):
    worker, authority, _ = runtime
    worker = enable_operational(worker, authority, tmp_path)
    event = subject()
    worker.accept(event)
    digest = signed_event_digest(event.to_dict())
    restarted = AutomaticWitness(worker.settings, worker.store)
    restarted.issue(digest)
    row = worker.store.witness_rows(digest)[0]
    receipt = json.loads(row['receipt'])
    body = verify_receipt(receipt, event.to_dict())
    assert body['schema_version'] == 2
    assert body['clock_uncertainty_ms'] is None
    assert body['clock_accuracy'] == 'unspecified'
    restarted.issue(digest)
    assert worker.store.witness_rows(digest)[0]['receipt'] == row['receipt']


def test_operational_receipt_delivered_by_application(runtime, tmp_path):
    worker, authority, _ = runtime
    worker = enable_operational(worker, authority, tmp_path)
    event = subject()
    with TestClient(create_app(worker.settings)) as client:
        info = client.get('/info').json()['automatic_witness']
        assert info['clock_mode'] == 'operational'
        assert info['receipt_version'] == 2
        with client.websocket_connect('/') as ws:
            ws.send_json(['REQ', 'receipt', {'kinds': [1418], '#e': [event.id]}])
            assert ws.receive_json()[0] == 'EOSE'
            ws.send_json(['EVENT', event.to_dict()])
            assert ws.receive_json()[:3] == ['OK', event.id, True]
            receipt = ws.receive_json()[2]
            assert verify_receipt(receipt, event.to_dict())['clock_uncertainty_ms'] is None


def test_clock_mode_configuration_is_explicit(runtime, monkeypatch):
    from spurline.config import Settings
    worker, _, _ = runtime
    assert worker.settings.witness_clock_mode == 'bounded'
    with pytest.raises(ValueError, match='CLOCK_MODE'):
        replace(worker.settings, witness_clock_mode='anything')
    monkeypatch.setenv('SPURLINE_WITNESS_CLOCK_MODE', 'operational')
    assert Settings.from_env().witness_clock_mode == 'operational'


def test_operational_requires_approved_policy_marker(runtime):
    worker, _, _ = runtime
    worker.settings.witness_clock_file.write_text(json.dumps(operational_health(time.time())))
    worker = AutomaticWitness(replace(worker.settings, witness_clock_mode='operational'), worker.store)
    assert worker.accept(subject())
    assert not worker.store.witness_rows()


def test_mode_change_does_not_reinterpret_pending_job(runtime, tmp_path):
    worker, authority, _ = runtime
    worker = enable_operational(worker, authority, tmp_path)
    event = subject()
    worker.accept(event)
    worker.settings.witness_clock_file.write_text(json.dumps(dict(synchronized=True,
        checked_at_ms=int(time.time()*1000), uncertainty_ms=10)))
    other = AutomaticWitness(replace(worker.settings, witness_clock_mode='bounded'), worker.store)
    digest = signed_event_digest(event.to_dict())
    other.issue(digest)
    assert other.status(digest)['state'] == 'unavailable'


def test_sync_loss_stops_pending_issuance(runtime, tmp_path):
    worker, authority, _ = runtime
    worker = enable_operational(worker, authority, tmp_path)
    event = subject()
    worker.accept(event)
    health = operational_health(time.time())
    health['synchronized'] = False
    worker.settings.witness_clock_file.write_text(json.dumps(health))
    digest = signed_event_digest(event.to_dict())
    worker.issue(digest)
    assert worker.status(digest)['state'] == 'unavailable'


def test_policy_rejects_mode_mismatch_and_excess_delay(runtime, tmp_path):
    worker, authority, _ = runtime
    worker = enable_operational(worker, authority, tmp_path)
    worker.settings = replace(worker.settings, witness_max_delay_seconds=61)
    assert worker.accept(subject())
    assert not worker.store.witness_rows()
    worker.settings.witness_clock_file.write_text(json.dumps(dict(synchronized=True,
        checked_at_ms=int(time.time()*1000), uncertainty_ms=10)))
    worker = AutomaticWitness(replace(worker.settings, witness_clock_mode='bounded'), worker.store)
    assert worker.accept(subject('bounded under operational policy'))
    assert not worker.store.witness_rows()


def test_operational_step_detection_still_latches(runtime, tmp_path, monkeypatch):
    worker, authority, clock = runtime
    worker = enable_operational(worker, authority, tmp_path)
    worker.clock.sample()
    monkeypatch.setattr('time.monotonic', lambda: clock[0] - 1)
    worker.check_clock()
    assert worker.clock.failed is True
    with pytest.raises(ClockUnavailable):
        worker.clock.sample()


def test_operational_checks_local_authorization_window(runtime, tmp_path):
    worker, authority, _ = runtime
    worker = enable_operational(worker, authority, tmp_path)
    view = authority.show()
    assert worker._within(view, view['not_before'] * 1000, None)
    assert not worker._within(view, view['not_before'] * 1000 - 1, None)
    assert not worker._within(view, view['not_after'] * 1000, None)


@pytest.mark.parametrize('change', [dict(synchronized=False), dict(synchronized='yes'),
    dict(uncertainty_ms=0), dict(source='fake'), dict(mode='bounded'),
    dict(last_sync_at_ms=0), dict(last_sync_at_ms=True), dict(checked_at_ms=0),
    dict(last_sync_at_ms=2**53), dict(checked_at_ms=2**53)])
def test_operational_clock_fails_closed(tmp_path, change):
    path = tmp_path / 'clock.json'
    data = operational_health(time.time())
    data.update(change)
    path.write_text(json.dumps(data))
    with pytest.raises(ClockUnavailable):
        WitnessClock(path, 'operational').sample()


def test_monitor_collects_actual_sync_age_and_writes_atomically(tmp_path):
    sync = tmp_path / 'synchronized'
    sync.touch()
    now = time.time()
    os.utime(sync, (now - 2100, now - 2100))
    calls = []
    def run(argv):
        calls.append(argv)
        return 'active' if argv[0] == 'systemctl' else 'yes'
    data = clock_monitor.collect(sync_file=sync, run=run)
    assert data['synchronized'] is True
    assert data['uncertainty_ms'] is None
    assert data['checked_at_ms'] - data['last_sync_at_ms'] >= 2100000
    assert len(calls) == 2
    path = tmp_path / 'health.json'
    clock_monitor.write_health(path, data)
    assert json.loads(path.read_text()) == data
    assert path.stat().st_mode & 0o777 == 0o644
    assert not list(tmp_path.glob('.clock-*'))
    assert WitnessClock(path, 'operational').sample()[1] is None
    with pytest.raises(ClockUnavailable):
        WitnessClock(path).sample()


@pytest.mark.parametrize('failure', ['stopped', 'unsynced', 'timeout', 'missing', 'old', 'future'])
def test_monitor_failures_report_unhealthy(tmp_path, failure):
    sync = tmp_path / 'synchronized'
    sync.touch()
    if failure == 'missing':
        sync.unlink()
    if failure in ('old', 'future'):
        timestamp = time.time() + (10 if failure == 'future' else -7201)
        os.utime(sync, (timestamp, timestamp))
    def run(argv):
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(argv, 5)
        if argv[0] == 'systemctl':
            return 'inactive' if failure == 'stopped' else 'active'
        return 'no' if failure == 'unsynced' else 'yes'
    assert clock_monitor.collect(sync_file=sync, run=run)['synchronized'] is False


def test_atomic_write_failure_preserves_old_status(tmp_path, monkeypatch):
    path = tmp_path / 'health.json'
    clock_monitor.write_health(path, {'synchronized': False})
    def fail(*args):
        raise OSError('injected failure')
    monkeypatch.setattr(clock_monitor.os, 'replace', fail)
    with pytest.raises(OSError):
        clock_monitor.write_health(path, {'synchronized': True})
    assert json.loads(path.read_text()) == {'synchronized': False}
    assert not list(tmp_path.glob('.clock-*'))
