from dfap.ldrm_subsystem.integration.audit_adapter import AuditAdapter
import json
import os

class DFAPAuditAdapter(AuditAdapter):
    def __init__(self, log_path: str = "data/ldrm_audit.jsonl"):
        self.log_path = log_path
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)

    def log_event(self, action, entity_type, entity_id, actor_id, metadata=None):
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "actor_id": actor_id,
                "metadata": metadata or {}
            }) + "\n")

    def log_security_violation(self, reason, actor_id, context=None):
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "action": "SECURITY_VIOLATION",
                "entity_type": "GLOBAL",
                "entity_id": "GLOBAL",
                "actor_id": actor_id,
                "metadata": {"reason": reason, **(context or {})}
            }) + "\n")

    def get_events_for_entity(self, entity_id):
        events = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        if data["entity_id"] == entity_id:
                            events.append(data)
        except FileNotFoundError:
            pass
        return events
