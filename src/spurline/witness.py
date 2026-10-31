"""Operator authorization for a witness role; does not issue observation receipts."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path

from stroma import Event, Keys

from .commissioning import (
    CommissioningError, MAX_CLOCK_SKEW_SECONDS, REQUEST_TTL_SECONDS,
    _content, _require_tag, _valid_event, canonical_json,
)
from .service import ServiceCommissioning

REQUEST_SCHEMA = "org.spurline.witness-authorization-request"
AUTHORIZATION_SCHEMA = "org.spurline.witness-authorization"
ROLE = "observation-witness"
MAX_POLICY_BYTES = 256 * 1024
MAX_VALIDITY_SECONDS = 365 * 24 * 60 * 60
SUPPORTED_KINDS = {1415, 1416}


def _witness_content(event, schema):
    try:
        body = json.loads(event.content)
        if (not isinstance(body, dict) or body.get("schema") != schema
                or type(body.get("schema_version")) is not int
                or body["schema_version"] not in (1, 2)
                or canonical_json(body) != event.content):
            raise ValueError
        return body
    except (ValueError, TypeError) as exc:
        raise CommissioningError("invalid witness schema or canonical content") from exc


def _integer(value, label):
    if type(value) is not int:
        raise CommissioningError(f"{label} must be an integer")
    return value


def _verify_request(data, commissioning, settings, policy, *, now, current):
    request = _valid_event(data, label="witness request")
    content = _witness_content(request, REQUEST_SCHEMA)
    service_hex = Keys(pub_k=settings.service_npub).public_key_hex()
    operator_hex = Keys(pub_k=commissioning["operator_npub"]).public_key_hex()
    if request.kind != 78 or request.pub_key != service_hex:
        raise CommissioningError("witness request must be signed by this service")
    issued = _integer(content.get("issued_at"), "issued_at")
    expires = _integer(content.get("expires_at"), "expires_at")
    start = _integer(content.get("not_before"), "not_before")
    end = _integer(content.get("not_after"), "not_after")
    if issued != request.created_at or issued > now + MAX_CLOCK_SKEW_SECONDS:
        raise CommissioningError("invalid witness request issue time")
    if start != issued or not 0 < end - start <= MAX_VALIDITY_SECONDS:
        raise CommissioningError("invalid witness authorization validity interval")
    if expires != min(issued + REQUEST_TTL_SECONDS, end):
        raise CommissioningError("invalid witness request deadline")
    if current and now >= expires:
        raise CommissioningError("witness request has expired")
    kinds = content.get("subject_kinds")
    if (not isinstance(kinds, list) or not kinds
            or any(type(kind) is not int or kind not in SUPPORTED_KINDS for kind in kinds)
            or kinds != sorted(set(kinds))):
        raise CommissioningError("witness kinds must be a sorted subset of 1415 and 1416")
    nonce = content.get("nonce")
    if (not isinstance(nonce, str) or len(nonce) != 64
            or any(ch not in "0123456789abcdef" for ch in nonce)):
        raise CommissioningError("invalid witness request nonce")
    if not isinstance(policy, str) or not 0 < len(policy.encode("utf-8")) <= MAX_POLICY_BYTES:
        raise CommissioningError("invalid retained witness policy")
    expected = {
        "schema": REQUEST_SCHEMA, "schema_version": content["schema_version"],
        "role": ROLE, "service": {"pubkey": service_hex, "type": "nostr-relay"},
        "requested_operator": operator_hex, "management": settings.service_management,
        "commissioning_attestation": commissioning["operator_attestation_event_id"],
        "issued_at": issued, "expires_at": expires, "nonce": nonce,
        "not_before": start, "not_after": end, "subject_kinds": kinds,
        "policy_sha256": hashlib.sha256(policy.encode("utf-8")).hexdigest(),
    }
    if content["schema_version"] == 2:
        sequence = _integer(content.get("sequence"), "sequence")
        previous = content.get("previous")
        if (sequence < 2 or not isinstance(previous, str) or len(previous) != 64
                or any(ch not in "0123456789abcdef" for ch in previous)):
            raise CommissioningError("invalid renewal predecessor")
        expected.update(action="renew", sequence=sequence, previous=previous)
    if canonical_json(content) != canonical_json(expected):
        raise CommissioningError("witness request does not match commissioning or policy")
    for tag in (
        ["p", operator_hex, "", "operator"],
        ["e", commissioning["operator_attestation_event_id"], "", "commissioning-attestation"],
        ["expiration", str(expires)], ["role", ROLE],
    ):
        _require_tag(request, tag)
    return request, content


def authorization_template(request):
    """Unsigned template only; the operator must review and sign independently."""
    content = json.loads(request["content"])
    issued = int(time.time())
    body = {
        "schema": AUTHORIZATION_SCHEMA, "schema_version": content["schema_version"],
        "action": content.get("action", "authorize"), "role": ROLE,
        "service": content["service"], "operator": content["requested_operator"],
        "management": content["management"],
        "commissioning_attestation": content["commissioning_attestation"],
        "request_event_id": request["id"], "issued_at": issued,
        "not_before": content["not_before"], "not_after": content["not_after"],
        "subject_kinds": content["subject_kinds"], "policy_sha256": content["policy_sha256"],
        "sequence": content.get("sequence", 1), "previous": content.get("previous"),
    }
    return {
        "kind": 30078, "pubkey": content["requested_operator"], "created_at": issued,
        "content": canonical_json(body),
        "tags": [
            ["d", f"{AUTHORIZATION_SCHEMA}:{content['service']['pubkey']}" +
             (f":{request['id']}" if content["schema_version"] == 2 else "")],
            ["p", content["service"]["pubkey"], "", "service"],
            ["e", request["id"], "", "authorization-request"],
            ["e", content["commissioning_attestation"], "", "commissioning-attestation"],
            ["role", ROLE],
        ],
    }


def _verify_authorization(data, request, content, *, now):
    event = _valid_event(data, label="witness authorization")
    body = _witness_content(event, AUTHORIZATION_SCHEMA)
    if event.kind != 30078 or event.pub_key != content["requested_operator"]:
        raise CommissioningError("witness authorization must be signed by the commissioned operator")
    if not request.created_at <= event.created_at < content["expires_at"]:
        raise CommissioningError("witness authorization was signed outside the request window")
    if event.created_at > now + MAX_CLOCK_SKEW_SECONDS:
        raise CommissioningError("witness authorization is dated too far in the future")
    template = authorization_template(request.data())
    expected = json.loads(template["content"])
    expected["issued_at"] = event.created_at
    if canonical_json(body) != canonical_json(expected):
        raise CommissioningError("witness authorization does not match the request")
    for tag in template["tags"]:
        _require_tag(event, tag)
    return event


class WitnessAuthorization:
    def __init__(self, settings):
        self.settings = settings
        self.service = ServiceCommissioning(settings)

    def _load(self, db):
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='witness_authorization'").fetchone()
        if not exists:
            return {}
        row = db.execute("SELECT evidence FROM witness_authorization WHERE id=1").fetchone()
        if not row:
            return {}
        try:
            value = json.loads(row[0])
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (TypeError, ValueError) as exc:
            raise CommissioningError("invalid stored witness authorization") from exc

    def _write(self, db, evidence):
        db.execute("CREATE TABLE IF NOT EXISTS witness_authorization (id INTEGER PRIMARY KEY CHECK(id=1), evidence TEXT NOT NULL)")
        db.execute("INSERT INTO witness_authorization VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET evidence=excluded.evidence",
                   (canonical_json(evidence),))

    def _check(self, evidence, commissioning, *, current=False):
        required = {"request", "policy"}
        if set(evidence) not in (required, required | {"authorization"}):
            raise CommissioningError("incomplete witness evidence")
        now = int(time.time())
        request, content = _verify_request(
            evidence["request"], commissioning, self.settings, evidence["policy"],
            now=now, current=current,
        )
        state = "pending" if now < content["expires_at"] else "request-expired"
        authorization_id = None
        if "authorization" in evidence:
            authorization = _verify_authorization(evidence["authorization"], request, content, now=now)
            authorization_id = authorization.id
            if now < max(content["not_before"], authorization.created_at):
                state = "not-yet-valid"
            elif now >= content["not_after"]:
                state = "expired"
            else:
                state = "authorized"
        return {
            "state": state, "role": ROLE, "receipt_issuance_enabled": False,
            "operator_npub": commissioning["operator_npub"],
            "authorization_event_id": authorization_id,
            "request_event_id": request.id, "policy_sha256": content["policy_sha256"],
            "subject_kinds": content["subject_kinds"],
            "not_before": content["not_before"], "not_after": content["not_after"],
        }

    def _history(self, db):
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='witness_history'").fetchone()
        if not exists:
            old = self._load(db)
            return [old] if "authorization" in old else []
        rows = db.execute("SELECT evidence FROM witness_history ORDER BY sequence").fetchall()
        try:
            history = [json.loads(row[0]) for row in rows]
            if any(not isinstance(entry, dict) for entry in history):
                raise ValueError
            return history
        except (TypeError, ValueError) as exc:
            raise CommissioningError("invalid witness history") from exc

    def _append(self, db, history, entry):
        db.execute("CREATE TABLE IF NOT EXISTS witness_history (sequence INTEGER PRIMARY KEY, evidence TEXT NOT NULL)")
        # Import legacy initial authorization unchanged, once, in this transaction.
        for index, old in enumerate(history, 1):
            db.execute("INSERT OR IGNORE INTO witness_history VALUES (?, ?)", (index, canonical_json(old)))
        db.execute("INSERT INTO witness_history VALUES (?, ?)", (len(history) + 1, canonical_json(entry)))

    @staticmethod
    def _event(entry):
        return entry.get("authorization", entry.get("revocation"))

    def _revocation_template(self, head, commissioning, reason, *, issued=None):
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 512:
            raise CommissioningError("revocation reason must contain 1..512 characters")
        issued = int(time.time()) if issued is None else issued
        previous = self._event(head)
        previous_body = json.loads(previous["content"])
        pubkey = Keys(pub_k=self.settings.service_npub).public_key_hex()
        operator = Keys(pub_k=commissioning["operator_npub"]).public_key_hex()
        body = {
            "schema": AUTHORIZATION_SCHEMA, "schema_version": 2,
            "action": "revoke", "role": ROLE,
            "service": {"pubkey": pubkey, "type": "nostr-relay"},
            "operator": operator, "management": self.settings.service_management,
            "commissioning_attestation": commissioning["operator_attestation_event_id"],
            "issued_at": issued, "effective_at": issued, "reason": reason,
            "sequence": previous_body["sequence"] + 1, "previous": previous["id"],
        }
        return {"kind": 30078, "pubkey": operator, "created_at": issued,
                "content": canonical_json(body), "tags": [
                    ["d", f"{AUTHORIZATION_SCHEMA}:{pubkey}:revoke:{previous['id']}"],
                    ["p", pubkey, "", "service"],
                    ["e", previous["id"], "", "previous-authorization"],
                    ["e", commissioning["operator_attestation_event_id"], "", "commissioning-attestation"],
                    ["role", ROLE],
                ]}

    def _validate_history(self, db, commissioning):
        history = self._history(db)
        previous = None
        for index, entry in enumerate(history, 1):
            event_data = self._event(entry)
            event = _valid_event(event_data, label="witness lifecycle event")
            body = _witness_content(event, AUTHORIZATION_SCHEMA)
            if (type(body.get("sequence")) is not int or body["sequence"] != index
                    or body.get("previous") != (previous["id"] if previous else None)):
                raise CommissioningError("witness history has a gap or conflicting predecessor")
            if previous and event.created_at < previous["created_at"]:
                raise CommissioningError("witness lifecycle time moved backwards")
            if "authorization" in entry:
                self._check(entry, commissioning)
                if body["action"] != ("authorize" if index == 1 else "renew"):
                    raise CommissioningError("invalid witness lifecycle action")
            else:
                if set(entry) != {"revocation"} or previous is None:
                    raise CommissioningError("invalid revocation history")
                if "revocation" in history[index - 2]:
                    raise CommissioningError("cannot revoke an already revoked chain")
                template = self._revocation_template(history[index - 2], commissioning,
                                                     body.get("reason"), issued=event.created_at)
                if (event.kind != template["kind"] or event.pub_key != template["pubkey"]
                        or event.content != template["content"] or event.tags.as_list() != template["tags"]):
                    raise CommissioningError("revocation does not match commissioned operator or chain")
            previous = event_data
        current = self._load(db)
        if "authorization" in current and history:
            latest_grant = next(entry for entry in reversed(history) if "authorization" in entry)
            if current != latest_grant:
                raise CommissioningError("current witness policy or evidence differs from retained history")
        return history

    def _controls(self, db):
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='witness_controls'").fetchone():
            return []
        return [dict(action=row[0], reason=row[1], recorded_at=row[2]) for row in
                db.execute("SELECT action, reason, recorded_at FROM witness_controls ORDER BY id")]

    def _view(self, db, commissioning):
        history = self._validate_history(db, commissioning)
        current = self._load(db)
        pending = current if current and "authorization" not in current else None
        pending_status = self._check(pending, commissioning) if pending else None
        grant = next((entry for entry in reversed(history) if "authorization" in entry), None)
        status = self._check(grant, commissioning) if grant else (pending_status or {
            "state": "not-authorized", "role": ROLE, "receipt_issuance_enabled": False,
        })
        if history and "revocation" in history[-1]:
            status["state"] = "revoked"
        controls = self._controls(db)
        suspended = bool(controls and controls[-1]["action"] == "suspend")
        authorization_state = status["state"]
        if suspended:
            status["state"] = "suspended"
        return {**status, "authorization_state": authorization_state,
                "receipt_issuance_enabled": self.settings.witness_enabled,
                "locally_suspended": suspended,
                "witnessing_permitted": authorization_state == "authorized" and not suspended,
                "head_event_id": self._event(history[-1])["id"] if history else None,
                "sequence": len(history), "evidence": grant or pending or {},
                "history": history, "pending": pending, "pending_status": pending_status,
                "local_controls": controls}

    def request(self, policy_path: Path, *, valid_for: int, kinds: list[int], renew=False):
        _integer(valid_for, "valid-for")
        if not 0 < valid_for <= MAX_VALIDITY_SECONDS:
            raise CommissioningError("valid-for must be 1..31536000 seconds")
        # Read bytes so the commitment preserves line endings and exact UTF-8 bytes.
        with policy_path.open("rb") as stream:
            raw = stream.read(MAX_POLICY_BYTES + 1)
        if not raw or len(raw) > MAX_POLICY_BYTES:
            raise CommissioningError("policy must be nonempty and at most 256 KiB")
        policy = raw.decode("utf-8")
        with self.service.connection() as db:
            commissioning = self.service._verify(self.service._load(db))
            history = self._validate_history(db, commissioning)
            if history and not renew:
                raise CommissioningError("witness authorization already exists; use renewal")
            if renew and not history:
                raise CommissioningError("renewal requires a prior authorization")
            now = int(time.time())
            operator = Keys(pub_k=commissioning["operator_npub"]).public_key_hex()
            keys = Keys(priv_k=self.settings.service_nsec)
            body = {
                "schema": REQUEST_SCHEMA, "schema_version": 1, "role": ROLE,
                "service": {"pubkey": keys.public_key_hex(), "type": "nostr-relay"},
                "requested_operator": operator, "management": self.settings.service_management,
                "commissioning_attestation": commissioning["operator_attestation_event_id"],
                "issued_at": now, "expires_at": min(now + REQUEST_TTL_SECONDS, now + valid_for),
                "nonce": secrets.token_hex(32), "not_before": now, "not_after": now + valid_for,
                "subject_kinds": sorted(set(kinds)), "policy_sha256": hashlib.sha256(raw).hexdigest(),
            }
            if renew:
                head = self._event(history[-1])
                if now < head["created_at"]:
                    raise CommissioningError("clock precedes witness lifecycle head")
                body.update(schema_version=2, action="renew", sequence=len(history) + 1, previous=head["id"])
            event = Event(kind=78, created_at=now, content=canonical_json(body), tags=[
                ["p", operator, "", "operator"],
                ["e", commissioning["operator_attestation_event_id"], "", "commissioning-attestation"],
                ["expiration", str(body["expires_at"])], ["role", ROLE],
            ])
            event.sign(keys)
            evidence = {"request": event.data(), "policy": policy}
            status = self._check(evidence, commissioning, current=True)
            # Materialize legacy history before replacing the current/pending row.
            if history and not db.execute("SELECT 1 FROM sqlite_master WHERE name='witness_history'").fetchone():
                self._append(db, [], history[0])
            self._write(db, evidence)
        return {**status, "evidence": evidence, "unsigned_authorization": authorization_template(event.data())}

    def authorize(self, event):
        with self.service.connection() as db:
            commissioning = self.service._verify(self.service._load(db))
            history = self._validate_history(db, commissioning)
            if any(entry.get("authorization") == event for entry in history):
                return self._view(db, commissioning)
            evidence = self._load(db)
            if not evidence:
                raise CommissioningError("no witness request is pending")
            if "authorization" in evidence:
                if evidence["authorization"] != event:
                    raise CommissioningError("witness authorization already exists")
                status = self._check(evidence, commissioning)
            else:
                evidence["authorization"] = event
                status = self._check(evidence, commissioning, current=True)
                body = json.loads(event["content"])
                expected_previous = self._event(history[-1])["id"] if history else None
                if body["sequence"] != len(history) + 1 or body["previous"] != expected_previous:
                    raise CommissioningError("stale or conflicting authorization predecessor")
                if history and event["created_at"] < self._event(history[-1])["created_at"]:
                    raise CommissioningError("authorization predates lifecycle head")
                self._append(db, history, evidence)
                self._write(db, evidence)
            return self._view(db, commissioning)

    def revocation_request(self, reason):
        with self.service.connection() as db:
            commissioning = self.service._verify(self.service._load(db))
            history = self._validate_history(db, commissioning)
            if not history or "revocation" in history[-1]:
                raise CommissioningError("no unrevoked authorization to revoke")
            return {"unsigned_revocation": self._revocation_template(history[-1], commissioning, reason)}

    def revoke(self, event):
        with self.service.connection() as db:
            commissioning = self.service._verify(self.service._load(db))
            history = self._validate_history(db, commissioning)
            if any(entry.get("revocation") == event for entry in history):
                return self._view(db, commissioning)
            verified = _valid_event(event, label="revocation")
            # Revocation imports cannot be scheduled in the future.
            if verified.created_at > int(time.time()):
                raise CommissioningError("revocation cannot be future-dated")
            self._append(db, history, {"revocation": event})
            self._validate_history(db, commissioning)
            # A signed revocation invalidates any outstanding renewal request.
            latest = next(entry for entry in reversed(history) if "authorization" in entry)
            self._write(db, latest)
            return self._view(db, commissioning)

    def control(self, action, reason):
        if action not in ("suspend", "resume") or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 512:
            raise CommissioningError("a suspend/resume action and 1..512 character reason are required")
        with self.service.connection() as db:
            commissioning = self.service._verify(self.service._load(db))
            view = self._view(db, commissioning)
            if action == "resume" and view["authorization_state"] != "authorized":
                raise CommissioningError("resume requires currently valid authorization")
            db.execute("CREATE TABLE IF NOT EXISTS witness_controls (id INTEGER PRIMARY KEY, action TEXT NOT NULL, reason TEXT NOT NULL, recorded_at INTEGER NOT NULL)")
            db.execute("INSERT INTO witness_controls(action, reason, recorded_at) VALUES (?, ?, ?)",
                       (action, reason, int(time.time())))
            return self._view(db, commissioning)

    def show(self):
        evidence = {}
        if self.service.path.exists():
            with self.service.connection(write=False) as db:
                evidence = self._load(db)
                if evidence or self._controls(db):
                    commissioning = self.service._verify(self.service._load(db))
                    return self._view(db, commissioning)
        return {"state": "not-authorized", "role": ROLE, "receipt_issuance_enabled": self.settings.witness_enabled,
                "witnessing_permitted": False, "evidence": {}, "history": [], "local_controls": []}

    def verify(self):
        result = self.show()
        if "authorization" not in result["evidence"]:
            raise CommissioningError("no witness authorization is retained")
        return {**result, "evidence_verified": True}
