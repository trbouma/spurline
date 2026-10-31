import io
import json
import time
from types import SimpleNamespace

import pytest
from spurline import operator_signing as signing
from spurline.cli import main
from spurline.commissioning import CommissioningError, create_commissioning_request, verify_operator_attestation
from spurline.service import ServiceCommissioning
from spurline.witness import WitnessAuthorization
from test_commissioning import SERVICE_NSEC, SERVICE_NPUB, OPERATOR_KEYS, complete_service, settings_for


class Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def setup(tmp_path, monkeypatch):
    now = int(time.time()) - 5
    request = create_commissioning_request(SERVICE_NSEC, OPERATOR_KEYS.public_key_bech32(),
                                         'mainstay-managed', now=now)
    path = tmp_path / 'request.json'
    path.write_text(json.dumps({'commissioning_request': request}))
    args = SimpleNamespace(operator_action='sign-commissioning', file=path, service_npub=SERVICE_NPUB)
    monkeypatch.setattr('sys.stdin', Terminal('yes\n'))
    monkeypatch.setattr(signing.getpass, 'getpass', lambda prompt: '33' * 32)
    return args, request


def test_commissioning_signs_verified_output(setup, capsys):
    args, request = setup
    event = signing.sign(args)
    verify_operator_attestation(request, event, service_npub=SERVICE_NPUB, management='mainstay-managed')
    output = capsys.readouterr()
    assert not output.out
    assert request['id'] in output.err
    assert '33' * 32 not in output.err


def test_pending_service_show_wrapper(setup):
    args, request = setup
    args.file.write_text(json.dumps({'state': 'commissioning-pending',
                                     'evidence': {'commissioning_request': request}}))
    assert signing.sign(args)['pubkey'] == OPERATOR_KEYS.public_key_hex()


def test_cli_independent_of_relay_environment(setup, monkeypatch, capsys):
    args, _ = setup
    monkeypatch.setenv('SPURLINE_SERVICE_NSEC', 'invalid')
    monkeypatch.setenv('SPURLINE_WITNESS_ENABLED', 'true')
    monkeypatch.setattr('sys.argv', ['spurline', 'operator', 'sign-commissioning',
                        '--file', str(args.file), '--service-npub', SERVICE_NPUB])
    main()
    event = json.loads(capsys.readouterr().out)
    assert event['kind'] == 30078


@pytest.mark.parametrize('failure', ['wrong-key', 'wrong-service', 'cancel', 'noninteractive', 'expired', 'tampered'])
def test_rejects_without_output(setup, monkeypatch, capsys, failure):
    args, request = setup
    if failure == 'wrong-key':
        monkeypatch.setattr(signing.getpass, 'getpass', lambda prompt: '44' * 32)
    elif failure == 'wrong-service':
        args.service_npub = OPERATOR_KEYS.public_key_bech32()
    elif failure == 'cancel':
        monkeypatch.setattr('sys.stdin', Terminal('no\n'))
    elif failure == 'noninteractive':
        monkeypatch.setattr('sys.stdin', io.StringIO('yes\n'))
    elif failure == 'expired':
        monkeypatch.setattr('time.time', lambda: request['created_at'] + 86401)
    else:
        request['sig'] = '00' * 64
        args.file.write_text(json.dumps(request))
    with pytest.raises(CommissioningError):
        signing.sign(args)
    assert not capsys.readouterr().out


def test_expiry_rechecked_after_approval(setup, monkeypatch):
    args, request = setup
    def prompt(_):
        monkeypatch.setattr('time.time', lambda: request['created_at'] + 86401)
        return '33' * 32
    monkeypatch.setattr(signing.getpass, 'getpass', prompt)
    with pytest.raises(CommissioningError, match='expired'):
        signing.sign(args)


def test_no_insecure_getpass_fallback(setup, monkeypatch):
    import warnings
    args, _ = setup
    def prompt(_):
        warnings.warn('cannot hide', signing.getpass.GetPassWarning)
    monkeypatch.setattr(signing.getpass, 'getpass', prompt)
    with pytest.raises(CommissioningError, match='hidden'):
        signing.sign(args)


def test_witness_signer_and_policy_binding(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    complete_service(settings)
    policy = tmp_path / 'policy.txt'
    policy.write_bytes(b'Public policy\r\n')
    witness = WitnessAuthorization(settings)
    result = witness.request(policy, valid_for=3600, kinds=[1415, 1416])
    # A malicious unsigned template is ignored, never signed.
    result['unsigned_authorization']['content'] = 'malicious'
    path = tmp_path / 'witness.json'
    path.write_text(json.dumps(result))
    chain = tmp_path / 'commissioning.json'
    chain.write_text(json.dumps(ServiceCommissioning(settings).show()))
    args = SimpleNamespace(operator_action='sign-witness', file=path, service_npub=SERVICE_NPUB,
                           commissioning_file=chain, policy=policy)
    monkeypatch.setattr('sys.stdin', Terminal('yes\n'))
    monkeypatch.setattr(signing.getpass, 'getpass', lambda prompt: '33' * 32)
    signed = signing.sign(args)
    assert witness.authorize(signed)['state'] == 'authorized'
    # A valid signed request does not authorize signing without the complete chain.
    saved_chain = chain.read_text()
    chain.write_text('{}')
    with pytest.raises(CommissioningError, match='complete commissioning'):
        signing.sign(args)
    chain.write_text(saved_chain)
    policy.write_text('different policy')
    with pytest.raises(CommissioningError, match='policy'):
        signing.sign(args)
    policy.write_bytes(b'Public policy\r\n')
    renewal = witness.request(policy, valid_for=3600, kinds=[1415], renew=True)
    path.write_text(json.dumps(renewal))
    with pytest.raises(CommissioningError, match='initial witness grants only'):
        signing.sign(args)


def test_future_request_is_not_backdated(setup, monkeypatch):
    args, request = setup
    monkeypatch.setattr('time.time', lambda: request['created_at'] - 1)
    with pytest.raises(CommissioningError, match='future-dated'):
        signing.sign(args)
