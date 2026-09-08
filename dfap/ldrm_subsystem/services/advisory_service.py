"""
Advisory Service for Lawful Data Request Module (LDRM).
Provides advisory guidance for duplicate/overlapping request detection and scope minimization.
All advisory findings are non-blocking advisory recommendations and are logged immutably.
"""
import uuid
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

from dfap.ldrm_subsystem.domain.utils import utc_now


class AdvisoryService:
    def __init__(self, repository):
        self.repository = repository

    def check_duplicates(self, request_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scans existing non-cancelled/non-rejected requests for potential duplicate or overlapping requests.
        Returns advisory evaluation containing warnings, overlap types, and matching request IDs.
        """
        provider_id = request_payload.get("provider_id")
        dataset_type = request_payload.get("dataset_type")
        targets = request_payload.get("targets", [])
        start_date = request_payload.get("start_date")
        end_date = request_payload.get("end_date")
        request_id = request_payload.get("id")

        target_values = {t.get("target_value") for t in targets if t.get("target_value")}
        
        matches = []
        highest_severity = "INFO"
        overlap_type = "NONE"

        # Search existing requests in repository
        all_requests = self.repository.list_requests() if hasattr(self.repository, "list_requests") else []
        
        for existing in all_requests:
            # Handle domain object vs dict representation
            ext_id = getattr(existing, "id", None) if not isinstance(existing, dict) else existing.get("id")
            ext_status = getattr(existing, "status", None) if not isinstance(existing, dict) else existing.get("status")
            if hasattr(ext_status, "value"):
                ext_status_str = ext_status.value
            else:
                ext_status_str = str(ext_status or "")

            ext_dataset = getattr(existing, "dataset_type", None) if not isinstance(existing, dict) else existing.get("dataset_type")
            if hasattr(ext_dataset, "value"):
                ext_dataset_str = ext_dataset.value
            else:
                ext_dataset_str = str(ext_dataset or "")

            ext_provider = getattr(existing, "provider_id", None) if not isinstance(existing, dict) else existing.get("provider_id")
            ext_targets_raw = getattr(existing, "targets", []) if not isinstance(existing, dict) else existing.get("targets", [])
            
            ext_targets = []
            for t in ext_targets_raw:
                val = getattr(t, "target_value", None) if not isinstance(t, dict) else t.get("target_value")
                if val:
                    ext_targets.append(val)

            # Skip current request if checking existing one
            if request_id and ext_id == request_id:
                continue
            
            # Ignore terminal negative states
            if ext_status_str in ("CANCELLED", "REJECTED", "EXPIRED"):
                continue

            # Compare target values
            existing_target_set = set(ext_targets)
            matching_targets = target_values.intersection(existing_target_set)
            
            if not matching_targets:
                continue

            dataset_type_str = dataset_type.value if hasattr(dataset_type, "value") else str(dataset_type or "")
            # Compare dataset types
            same_dataset = ext_dataset_str == dataset_type_str
            same_provider = ext_provider == provider_id

            if matching_targets and same_dataset:
                overlap_type = "EXACT_DUPLICATE" if (same_provider and matching_targets) else "OVERLAPPING_SCOPE"
                highest_severity = "WARNING"
                matches.append({
                    "request_id": ext_id,
                    "reference_number": getattr(existing, "request_number", "") if not isinstance(existing, dict) else existing.get("reference_number"),
                    "status": ext_status_str,
                    "overlap_type": overlap_type,
                    "matching_targets": list(matching_targets),
                })

        findings = {
            "advisory_type": "DUPLICATE_CHECK",
            "has_warnings": len(matches) > 0,
            "severity": highest_severity,
            "overlap_type": overlap_type,
            "matches": matches,
            "message": f"Found {len(matches)} overlapping/duplicate request(s)" if matches else "No duplicates detected",
        }

        # Log evaluation immutably
        if request_id:
            self._log_advisory(request_id, "DUPLICATE_CHECK", findings)

        return findings

    def minimize_scope(
        self,
        requested_start: str,
        requested_end: str,
        investigative_start: Optional[str] = None,
        investigative_end: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates requested date range against investigative parameters and recommends scope minimization.
        Returns non-blocking advisory suggestions.
        """
        recommendations = []
        is_overbroad = False

        try:
            req_s = datetime.fromisoformat(requested_start.replace("Z", "+00:00"))
            req_e = datetime.fromisoformat(requested_end.replace("Z", "+00:00"))
            duration_days = (req_e - req_s).days

            if duration_days > 90:
                is_overbroad = True
                recommendations.append(
                    f"Requested duration spans {duration_days} days (>90 days). Consider splitting into phased 30-day windows."
                )

            if investigative_start and investigative_end:
                inv_s = datetime.fromisoformat(investigative_start.replace("Z", "+00:00"))
                inv_e = datetime.fromisoformat(investigative_end.replace("Z", "+00:00"))

                if req_s < inv_s or req_e > inv_e:
                    is_overbroad = True
                    recommendations.append(
                        f"Requested scope [{requested_start} to {requested_end}] exceeds investigative timeframe [{investigative_start} to {investigative_end}]."
                    )
        except Exception:
            pass

        findings = {
            "advisory_type": "SCOPE_MINIMIZATION",
            "is_overbroad": is_overbroad,
            "requested_start": requested_start,
            "requested_end": requested_end,
            "suggested_start": investigative_start or requested_start,
            "suggested_end": investigative_end or requested_end,
            "recommendations": recommendations,
            "message": "Scope minimization review complete" if not is_overbroad else "Scope exceeds recommended bounds",
        }

        if request_id:
            self._log_advisory(request_id, "SCOPE_MINIMIZATION", findings)

        return findings

    def _log_advisory(self, request_id: str, advisory_type: str, findings: Dict[str, Any]):
        """Persists advisory log entry into immutable storage table."""
        entry = {
            "id": f"ADV-{uuid.uuid4().hex[:12]}",
            "request_id": request_id,
            "advisory_type": advisory_type,
            "findings": json.dumps(findings, sort_keys=True),
            "evaluated_at": utc_now(),
        }
        if hasattr(self.repository, "insert_advisory_log"):
            self.repository.insert_advisory_log(entry)
