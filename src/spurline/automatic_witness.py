"""Opt-in local receipt issuance. No remote publishing or historical backfill."""

import asyncio
import json
import logging
import threading
import time

from stroma import Event, Keys

from .commissioning import CommissioningError, canonical_json
from .events import EventValidationError, StoredEvent, validate_event
from .receipts import (RECEIPT_SCHEMA, SUBJECT_PROFILE, WITNESS_KIND,
                       receipt_tags, signed_event_digest, verify_receipt)
from .witness import WitnessAuthorization

logger = logging.getLogger(__name__)
OPERATIONAL_POLICY_MARKER = 'Spurline-Clock-Profile: operational-v1'


class ClockUnavailable(ValueError):
    pass


class WitnessClock:
    """Trust an operator-managed time monitor; fail closed on stale/unknown time.

    The monitor must atomically replace a small JSON file. This is an explicit
    trust boundary, not an NTP implementation or a proof of accurate time.
    """

    def __init__(self, path, mode='bounded'):
        self.path = path
        if mode not in ('bounded', 'operational'):
            raise ValueError('unsupported clock mode')
        self.mode = mode
        self.previous = (time.time(), time.monotonic())
        self.failed = False

    def sample(self):
        wall, monotonic = time.time(), time.monotonic()
        old_wall, old_monotonic = self.previous
        self.previous = wall, monotonic
        if abs((wall - old_wall) - (monotonic - old_monotonic)) > .250:
            self.failed = True
        if self.failed:
            raise ClockUnavailable("clock discontinuity; restart after correcting time")
        try:
            with self.path.open('rb') as stream:
                data = json.loads(stream.read(4097))
            now = int(wall * 1000)
            checked, uncertainty = data['checked_at_ms'], data['uncertainty_ms']
            if (data['synchronized'] is not True or type(checked) is not int
                    or not 0 <= now - checked <= 30000):
                raise ValueError("unhealthy clock")
            if self.mode == 'bounded':
                if type(uncertainty) is not int or not 0 <= uncertainty <= 1000:
                    raise ValueError('bounded mode requires a numeric uncertainty')
            else:
                last_sync = data['last_sync_at_ms']
                if (data.get('mode') != 'operational' or uncertainty is not None
                        or data.get('source') != 'systemd-timesyncd'
                        or type(last_sync) is not int or not 0 <= checked - last_sync <= 7200000
                        or not 0 <= now - last_sync <= 7200000):
                    raise ValueError('invalid operational clock health')
            return now, uncertainty
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ClockUnavailable("fresh synchronized clock evidence unavailable") from exc


class AutomaticWitness:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store
        self.authority = WitnessAuthorization(settings)
        self.clock = WitnessClock(settings.witness_clock_file, settings.witness_clock_mode)
        self.lock = threading.Lock()
        self.stopping = asyncio.Event()

    def _view(self, db):
        service = self.authority.service
        return self.authority._view(db, service._verify(service._load(db)))

    @staticmethod
    def _within(view, now, uncertainty):
        grant = json.loads(view['evidence']['authorization']['content'])
        if uncertainty is None:
            # Operational mode checks the LOCAL clock only. This is not an
            # uncertainty interval and must never be presented as UTC assurance.
            return max(grant['issued_at'], view['not_before']) * 1000 <= now < view['not_after'] * 1000
        return (now - uncertainty >= max(grant['issued_at'], view['not_before']) * 1000
                and now + uncertainty < view['not_after'] * 1000)

    def _policy_allows_mode(self, view):
        operational_policy = OPERATIONAL_POLICY_MARKER in view['evidence'].get('policy', '').splitlines()
        operational_mode = self.settings.witness_clock_mode == 'operational'
        return (operational_policy == operational_mode
                and (not operational_mode or self.settings.witness_max_delay_seconds <= 60))

    def accept(self, event):
        if event.kind not in (1415, 1416):
            return self.store.save(event)
        # Independent verification even when ordinary relay checks are disabled.
        try:
            digest = signed_event_digest(event.to_dict())
        except (EventValidationError, CommissioningError):
            return self.store.save(event)
        with self.lock, self.authority.service.connection() as db:
            try:
                view = self._view(db)
                now, uncertainty = self.clock.sample()
                if (not view['witnessing_permitted'] or event.kind not in view['subject_kinds']
                        or not self._policy_allows_mode(view)
                        or not self._within(view, now, uncertainty)):
                    return self.store.save(event)
            except (CommissioningError, ClockUnavailable):
                return self.store.save(event)
            job = dict(subject=event.to_dict(), signed_event_digest=digest,
                       receipt_version=2 if self.settings.witness_clock_mode == 'operational' else 1,
                       observed_at_ms=now, clock_uncertainty_ms=uncertainty,
                       authorization_event_id=view['authorization_event_id'],
                       witness_policy_digest=view['policy_sha256'],
                       witness_pubkey=Keys(priv_k=self.settings.service_nsec).public_key_hex())
            return self.store.save(event, witness_job=job, queue_limit=self.settings.witness_queue_limit)

    def issue(self, digest):
        # Serialize with administrative authorization/suspension changes, including
        # other processes. Keep that lock until the receipt transaction commits.
        with self.lock, self.authority.service.connection() as db:
            row = self.store.witness_rows(digest)[0]
            if row['state'] != 'pending':
                return
            job = json.loads(row['inputs'])
            try:
                view = self._view(db)
                now, uncertainty = self.clock.sample()
                if (not view['witnessing_permitted']
                        or not self._policy_allows_mode(view)
                        or job.get('receipt_version', 1) != (2 if self.settings.witness_clock_mode == 'operational' else 1)
                        or view['authorization_event_id'] != job['authorization_event_id']
                        or job['witness_pubkey'] != Keys(priv_k=self.settings.service_nsec).public_key_hex()
                        or not self._within(view, now, uncertainty)
                        or now < job['observed_at_ms']
                        or now - job['observed_at_ms'] > self.settings.witness_max_delay_seconds * 1000):
                    self.store.witness_update(digest, unavailable=True)
                    return
            except (CommissioningError, ClockUnavailable):
                # No signing on unknown time or invalid authority. Never refresh
                # the original observation timestamp to make an old job eligible.
                self.store.witness_update(digest, unavailable=True)
                return
            subject = job['subject']
            body = {key: job[key] for key in ('signed_event_digest', 'observed_at_ms',
                    'clock_uncertainty_ms', 'authorization_event_id', 'witness_policy_digest')}
            version = job.get('receipt_version', 1)
            body.update(schema=RECEIPT_SCHEMA, schema_version=version, subject_profile=SUBJECT_PROFILE,
                        event_id=subject['id'], issued_at_ms=now,
                        validation='event-id-and-signature', observation_mode='live')
            if version == 2:
                body.update(clock_accuracy='unspecified', clock_basis='ntp-synchronized-system-clock')
            event = Event(kind=WITNESS_KIND, created_at=now // 1000,
                          content=canonical_json(body), tags=receipt_tags(subject, version))
            event.sign(Keys(priv_k=self.settings.service_nsec))
            receipt = event.data()
            verify_receipt(receipt, subject)
            self.store.save(validate_event(receipt, verify_signature=True), completed=digest)

    async def run(self, broadcast):
        failures = 0
        while not self.stopping.is_set():
            delay = .25
            try:
                await asyncio.to_thread(self.check_clock)
                rows = await asyncio.to_thread(self.store.witness_rows)
                for row in rows:
                    if self.stopping.is_set():
                        break
                    if row['state'] == 'pending':
                        await asyncio.to_thread(self.issue, row['digest'])
                    else:
                        # Durable local publication already happened. Broadcast is
                        # at-least-once; reconnecting clients query normal REQ.
                        await asyncio.wait_for(broadcast(StoredEvent.from_dict(json.loads(row['receipt']))), 5)
                        await asyncio.to_thread(self.store.witness_update, row['digest'])
                failures = 0
            except Exception:
                logger.exception('Automatic witness processing failed; durable work retained')
                failures = min(failures + 1, 5)
                delay = min(2 ** failures, 30)
            try:
                await asyncio.wait_for(self.stopping.wait(), delay)
            except TimeoutError:
                pass

    def check_clock(self):
        # Detect steps even while no subjects are arriving. Lost synchronization
        # is checked again on every acquisition and issuance.
        with self.lock:
            try:
                self.clock.sample()
            except ClockUnavailable:
                pass

    def status(self, digest):
        rows = self.store.witness_rows(digest)
        if not rows:
            return {'state': 'not-observed', 'receipt_event_id': None}
        row = rows[0]
        return {'state': row['state'], 'receipt_event_id':
                json.loads(row['receipt'])['id'] if row['receipt'] else None}
