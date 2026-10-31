"""Local administrative commissioning state, separate from relay event storage."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

from .commissioning import (
    CommissioningError, create_commissioning_request, create_service_descriptor,
    verify_commissioning_request, verify_operator_attestation, verify_service_descriptor,
)
from .config import Settings
from .identity import bind_service_identity


class ServiceCommissioning:
    def __init__(self, settings: Settings):
        self.settings = settings
        # Keep administrative evidence out of the deletable public event store.
        self.path = settings.database_path.parent / (settings.database_path.name + ".service.sqlite3")

    @contextmanager
    def connection(self, *, write=True):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = (sqlite3.connect(self.path, timeout=10) if write else
              sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10))
        try:
            if write:
                db.execute("CREATE TABLE IF NOT EXISTS commissioning (id INTEGER PRIMARY KEY CHECK(id=1), evidence TEXT NOT NULL)")
                db.commit()
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _load(self, db):
        row = db.execute("SELECT evidence FROM commissioning WHERE id=1").fetchone()
        if row is None:
            return {}
        try:
            data = json.loads(row[0])
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (ValueError, TypeError) as exc:
            raise CommissioningError("stored commissioning evidence is invalid") from exc

    def _write(self, db, evidence):
        db.execute("INSERT INTO commissioning VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET evidence=excluded.evidence",
                   (json.dumps(evidence, sort_keys=True, separators=(",", ":")),))

    def _identity(self):
        if not self.settings.service_npub:
            raise CommissioningError("SPURLINE_SERVICE_NSEC is required")
        bind_service_identity(self.settings.database_path, npub=self.settings.service_npub)
        return dict(service_npub=self.settings.service_npub, management=self.settings.service_management)

    def _verify(self, evidence):
        identity = self._identity()
        if set(evidence) != {"commissioning_request", "operator_attestation", "service_descriptor"}:
            raise CommissioningError("service is not commissioned or evidence is incomplete")
        verified = verify_operator_attestation(
            evidence["commissioning_request"], evidence["operator_attestation"],
            **identity, require_current_request=False,
        )
        descriptor = verify_service_descriptor(evidence["service_descriptor"],
                                               evidence["operator_attestation"], **identity)
        return {
            "state": "commissioned",
            "service_key_control": "verified",
            "operator_authorship": "verified",
            "reciprocal_relationship": "verified",
            "operator_npub": verified.operator_npub,
            "commissioning_request_event_id": verified.request.id,
            "operator_attestation_event_id": verified.attestation.id,
            "service_descriptor_event_id": descriptor.id,
        }

    def show(self):
        evidence = {}
        if self.path.exists():
            with self.connection(write=False) as db:
                evidence = self._load(db)
        if "operator_attestation" in evidence or "service_descriptor" in evidence:
            result = self._verify(evidence)
        elif evidence:
            verify_commissioning_request(evidence.get("commissioning_request"),
                                         **self._identity(), require_current=False)
            result = {"state": "commissioning-pending"}
        else:
            result = {"state": "uncommissioned" if self.settings.service_npub else "unconfigured"}
        return {**result, "evidence": evidence}

    def request(self, operator):
        self._identity()
        with self.connection() as db:
            existing = self._load(db)
            if "operator_attestation" in existing:
                raise CommissioningError("service is already commissioned")
            event = create_commissioning_request(self.settings.service_nsec, operator,
                                                 self.settings.service_management)
            self._write(db, {"commissioning_request": event})
        return {"state": "commissioning-pending", "commissioning_request": event}

    def commission(self, attestation):
        identity = self._identity()
        with self.connection() as db:
            evidence = self._load(db)
            if "operator_attestation" in evidence:
                if evidence["operator_attestation"] != attestation:
                    raise CommissioningError("service is already commissioned")
                return {**self._verify(evidence), "evidence": evidence}
            if "commissioning_request" not in evidence:
                raise CommissioningError("no service commissioning request is pending")
            verified = verify_operator_attestation(evidence["commissioning_request"],
                                                   attestation, **identity)
            descriptor = create_service_descriptor(self.settings.service_nsec, attestation,
                management=self.settings.service_management, now=verified.attestation.created_at)
            evidence.update(operator_attestation=attestation, service_descriptor=descriptor)
            result = self._verify(evidence)
            self._write(db, evidence)
        return {**result, "evidence": evidence}

    def verify(self):
        if not self.path.exists():
            raise CommissioningError("service is not commissioned")
        with self.connection(write=False) as db:
            return self._verify(self._load(db))
