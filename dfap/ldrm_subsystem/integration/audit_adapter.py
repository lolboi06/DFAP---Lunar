"""Durable audit journal and transactional delivery to host audit infrastructure."""
import hashlib
import hmac
import json
import secrets
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict
from dfap.ldrm_subsystem.domain.utils import utc_now
from dfap.ldrm_subsystem.persistence.repositories import SQLiteRepository, encode, hydrate


@dataclass(frozen=True)
class AuditEvent:
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    action: str = ''
    entity_type: str = 'LawfulDataRequest'
    entity_id: str = ''
    actor_id: str = ''
    timestamp: datetime = field(default_factory=utc_now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_security_alert: bool = False


class AuditAdapter(ABC):
    @abstractmethod
    def log_event(self, action, entity_type, entity_id, actor_id, metadata=None): ...

    @abstractmethod
    def log_security_violation(self, reason, actor_id, context=None): ...

    @abstractmethod
    def get_events_for_entity(self, entity_id): ...


class JournalAuditAdapter(AuditAdapter):
    """HMAC chain plus append-only storage; host delivery is retryable.

    The host must deduplicate by metadata['ldrm_event_id']. Key custody and
    external retention/checkpoints remain the deployment's responsibility.
    """
    def __init__(self, repository=None, key=None, host=None):
        self.repository = repository or SQLiteRepository()
        self.key = key or secrets.token_bytes(32)
        self.host = host
        if not self.verify_integrity():
            raise ValueError('Audit integrity failure or incorrect audit key')

    def _digest(self, sequence, previous, payload):
        return hmac.new(self.key, f'{sequence}:{previous}:{payload}'.encode(), hashlib.sha256).hexdigest()

    def _append(self, event):
        with self.repository.transaction():
            if not self.verify_integrity():
                raise ValueError('Audit integrity failure')
            db = self.repository.connection
            last = db.execute('SELECT sequence,hash FROM audit ORDER BY sequence DESC LIMIT 1').fetchone()
            sequence, previous = (last[0] + 1, last[1]) if last else (1, '0' * 64)
            payload = encode(event)
            digest = self._digest(sequence, previous, payload)
            db.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)',
                       (sequence, event.event_id, event.entity_id, payload, previous, digest))
            db.execute("INSERT INTO metadata VALUES('audit_head',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (f'{sequence}:{digest}',))
        return hydrate(AuditEvent, json.loads(payload))

    def log_event(self, action, entity_type, entity_id, actor_id, metadata=None):
        return self._append(AuditEvent(action=action, entity_type=entity_type, entity_id=entity_id,
                                       actor_id=actor_id, metadata=metadata or {}))

    def log_security_violation(self, reason, actor_id, context=None):
        context = context or {}
        return self._append(AuditEvent(action='SECURITY_VIOLATION', entity_id=context.get('target_id') or 'GLOBAL',
                                       actor_id=actor_id, metadata={'reason': reason, **context}, is_security_alert=True))

    def verify_integrity(self):
        with self.repository.lock:
            previous, sequence = '0' * 64, 0
            for row in self.repository.connection.execute('SELECT * FROM audit ORDER BY sequence'):
                sequence += 1
                try:
                    data = json.loads(row['payload'])
                    if data['event_id'] != row['event_id'] or data['entity_id'] != row['entity_id']:
                        return False
                except (ValueError, KeyError, TypeError):
                    return False
                if row['sequence'] != sequence or row['previous_hash'] != previous:
                    return False
                if not hmac.compare_digest(row['hash'], self._digest(sequence, previous, row['payload'])):
                    return False
                previous = row['hash']
            head = self.repository.connection.execute("SELECT value FROM metadata WHERE key='audit_head'").fetchone()
            return (head is None and sequence == 0) or (head is not None and head[0] == f'{sequence}:{previous}')

    @property
    def all_events(self):
        with self.repository.lock:
            if not self.verify_integrity():
                raise ValueError('Audit integrity failure')
            return [hydrate(AuditEvent, json.loads(r[0])) for r in self.repository.connection.execute('SELECT payload FROM audit ORDER BY sequence')]

    def get_events_for_entity(self, entity_id):
        return [event for event in self.all_events if event.entity_id == entity_id]

    def flush(self):
        if self.host is None:
            return
        # At-least-once delivery. A host failure leaves the event pending.
        for event in self.all_events:
            with self.repository.lock:
                delivered = self.repository.connection.execute('SELECT 1 FROM audit_delivery WHERE event_id=?', (event.event_id,)).fetchone()
            if delivered:
                continue
            metadata = {**event.metadata, 'ldrm_event_id': event.event_id, 'ldrm_timestamp': event.timestamp.isoformat()}
            if event.is_security_alert:
                self.host.log_security_violation(metadata.get('reason', event.action), event.actor_id, metadata)
            else:
                self.host.log_event(event.action, event.entity_type, event.entity_id, event.actor_id, metadata)
            with self.repository.transaction():
                self.repository.connection.execute('INSERT OR IGNORE INTO audit_delivery VALUES(?)', (event.event_id,))


DefaultAuditAdapter = JournalAuditAdapter
