"""Offline operator signing; never reads relay settings or stores private keys."""

import getpass
import json
import sys
import time
import warnings
from types import SimpleNamespace

from stroma import Event, Keys

from .commissioning import (
    ATTESTATION_SCHEMA, CommissioningError, canonical_json,
    normalize_public_key, verify_commissioning_request,
    verify_operator_attestation, verify_service_descriptor,
)
from .witness import MAX_POLICY_BYTES, _verify_request, _verify_authorization, authorization_template


def read_json(path):
    with path.open('rb') as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise CommissioningError('input exceeds 1 MiB')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise CommissioningError('expected a JSON object')
    return value


def prepare(action, data, service_npub, *, evidence=None, policy=None):
    """Validate supplied public evidence and construct our own signing template."""
    now = int(time.time())
    service_hex, _ = normalize_public_key(service_npub, label='expected service')
    container = data.get('evidence', data)
    if not isinstance(container, dict):
        raise CommissioningError('invalid request wrapper')
    request = container.get('commissioning_request', data) if action == 'sign-commissioning' else container.get('request', data)
    if not isinstance(request, dict):
        raise CommissioningError('missing signed request')
    try:
        content = json.loads(request['content'])
        management = content['management']
    except (KeyError, TypeError, ValueError) as exc:
        raise CommissioningError('invalid request content') from exc
    if management not in ('independent', 'mainstay-managed'):
        raise CommissioningError('unsupported management mode')
    context = dict(service_npub=service_npub, management=management)
    if action == 'sign-commissioning':
        verified, content = verify_commissioning_request(request, **context)
        operator = content['requested_operator']
        body = dict(schema=ATTESTATION_SCHEMA, schema_version=1, action='authorize',
                    commissioning_request=verified.id, installation=operator,
                    issued_at=now, management=management, previous=None,
                    relationship='operates', sequence=1,
                    service={'pubkey': service_hex, 'type': 'nostr-relay'})
        template = dict(kind=30078, created_at=now, content=canonical_json(body), tags=[
            ['d', f'{ATTESTATION_SCHEMA}:{service_hex}'], ['p', service_hex, '', 'service'],
            ['e', verified.id, '', 'commissioning-request'],
            ['t', 'mainstay-service-operator'], ['service-type', 'nostr-relay']])
    else:
        chain = (evidence or {}).get('evidence', evidence or {})
        if not isinstance(chain, dict):
            raise CommissioningError('invalid commissioning evidence wrapper')
        try:
            verified_chain = verify_operator_attestation(chain['commissioning_request'],
                chain['operator_attestation'], **context, require_current_request=False)
            verify_service_descriptor(chain['service_descriptor'], chain['operator_attestation'], **context)
        except KeyError as exc:
            raise CommissioningError('complete commissioning evidence is required') from exc
        commissioning = dict(operator_npub=verified_chain.operator_npub,
                             operator_attestation_event_id=verified_chain.attestation.id)
        verified, content = _verify_request(request, commissioning, SimpleNamespace(
            service_npub=service_npub, service_management=management), policy, now=now, current=True)
        # Renewal signing needs the complete authorization history and a distinct
        # review flow. Do not imply that checking a predecessor ID verifies it.
        if content['schema_version'] != 1:
            raise CommissioningError('this signer supports initial witness grants only, not renewals')
        operator = content['requested_operator']
        template = authorization_template(request)
    if now < verified.created_at:
        raise CommissioningError('request is future-dated; wait until its issue time')
    review = dict(action=action, expected_service_pubkey=service_hex,
                  requested_operator=operator, request_event_id=verified.id,
                  request_expires_at=content['expires_at'], terms=json.loads(template['content']))
    if policy is not None:
        review['policy_utf8'] = policy
    return request, operator, template, review, context


def sign(args):
    if not sys.stdin.isatty():
        raise CommissioningError('operator signing requires an interactive terminal; use --file for the request')
    data = read_json(args.file)
    evidence = read_json(args.commissioning_file) if args.operator_action == 'sign-witness' else None
    policy = None
    if args.operator_action == 'sign-witness':
        with args.policy.open('rb') as stream:
            raw = stream.read(MAX_POLICY_BYTES + 1)
        if not 0 < len(raw) <= MAX_POLICY_BYTES:
            raise CommissioningError('policy must be nonempty and at most 256 KiB')
        policy = raw.decode('utf-8')
    request, operator, template, review, context = prepare(
        args.operator_action, data, args.service_npub, evidence=evidence, policy=policy)
    # JSON escapes terminal controls in untrusted service content and policy.
    print(json.dumps(review, indent=2, ensure_ascii=True), file=sys.stderr)
    print('Confirm the service identity independently and review all terms above.', file=sys.stderr)
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        try:
            secret = getpass.getpass('Operator private key (hidden): ')
        except getpass.GetPassWarning as exc:
            raise CommissioningError('secure hidden key input is unavailable') from exc
    try:
        keys = Keys(priv_k=secret.strip())
    except Exception:
        raise CommissioningError('invalid operator private key') from None
    finally:
        secret = None
    if keys.public_key_hex() != operator:
        raise CommissioningError('operator key does not match the requested operator')
    print('Sign these terms? Type yes to approve: ', end='', file=sys.stderr, flush=True)
    if sys.stdin.readline().strip() != 'yes':
        raise CommissioningError('signing cancelled')
    # Recheck expiry after the user interaction; do not trust unsigned templates
    # supplied by the relay. Only the signing timestamp is refreshed.
    request, _, template, _, context = prepare(
        args.operator_action, data, args.service_npub, evidence=evidence, policy=policy)
    event = Event(kind=template['kind'], created_at=template['created_at'],
                  tags=template['tags'], content=template['content'])
    event.sign(keys)
    result = event.data()
    if args.operator_action == 'sign-commissioning':
        verify_operator_attestation(request, result, **context)
    else:
        _verify_authorization(result, Event.load(request, validate=True),
                              json.loads(request['content']), now=int(time.time()))
    return result
