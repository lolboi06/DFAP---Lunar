"""
Scope Validator for Lawful Data Requests.
"""
from datetime import datetime
from typing import List, Dict, Any
import re
import ipaddress

from dfap.ldrm_subsystem.domain.enums import DatasetType, TargetType
from dfap.ldrm_subsystem.domain.models import LawfulDataRequest, RequestTarget

class ScopeValidationError(Exception):
    """Raised when request scope validation fails."""
    def __init__(self, message: str, errors: List[str] = None):
        self.message = message
        self.errors = errors or [message]
        super().__init__(self.message)


class ScopeValidator:
    """
    Validates that a request scope conforms to legal, temporal, and dataset constraints.
    """

    DATASET_TARGET_COMPATIBILITY: Dict[DatasetType, List[TargetType]] = {
        DatasetType.CDR: [TargetType.PHONE_NUMBER, TargetType.IMSI, TargetType.IMEI],
        DatasetType.IPDR: [TargetType.IP_ADDRESS, TargetType.IP_SUBNET, TargetType.PHONE_NUMBER, TargetType.ACCOUNT_ID],
        DatasetType.BANK: [TargetType.BANK_ACCOUNT, TargetType.UPI_ID, TargetType.ACCOUNT_ID, TargetType.PHONE_NUMBER],
        DatasetType.SOCIAL: [TargetType.SOCIAL_HANDLE, TargetType.ACCOUNT_ID, TargetType.PHONE_NUMBER],
    }

    @classmethod
    def validate_target(cls, target: RequestTarget, dataset_type: DatasetType) -> List[str]:
        """Validates a single target specification against dataset rules."""
        errors: List[str] = []

        if not target.target_value or not target.target_value.strip():
            errors.append("Target identifier value cannot be empty.")

        # Check dataset type vs target type compatibility
        compatible_targets = cls.DATASET_TARGET_COMPATIBILITY.get(dataset_type, [])
        if target.target_type not in compatible_targets:
            errors.append(
                f"Target type '{target.target_type.value}' is not valid for dataset '{dataset_type.value}'. "
                f"Allowed types: {[t.value for t in compatible_targets]}"
            )

        # Explicit bounded, timezone-aware intervals and record categories.
        if not target.start_time or not target.end_time:
            errors.append("Both start_time and end_time are required.")
        elif not target.start_time.tzinfo or not target.end_time.tzinfo:
            errors.append("Target dates must include timezones.")
        elif target.start_time >= target.end_time:
            errors.append("Target start_time must precede end_time.")
        if not target.requested_categories or any(not c.strip() for c in target.requested_categories):
            errors.append("Explicit record categories are required.")
        if not target.justification.strip():
            errors.append("Target justification is required.")

        # Basic format checks
        val = target.target_value.strip()
        if target.target_type == TargetType.PHONE_NUMBER:
            # Clean non-digits for validation check
            digits_only = re.sub(r"[^\d+]", "", val)
            if len(digits_only) < 7 or len(digits_only) > 16:
                errors.append(f"Invalid phone number format: '{val}'. Expected 7-15 digits.")
        elif target.target_type in (TargetType.IP_ADDRESS, TargetType.IP_SUBNET):
            try:
                if target.target_type == TargetType.IP_ADDRESS:
                    ipaddress.ip_address(val)
                else:
                    ipaddress.ip_network(val, strict=True)
            except ValueError:
                errors.append("Invalid IP address or subnet.")
        elif target.target_type == TargetType.UPI_ID:
            if "@" not in val:
                errors.append(f"Invalid UPI ID format: '{val}'. Must contain '@'.")

        return errors

    @classmethod
    def validate_request_scope(cls, request: LawfulDataRequest) -> None:
        """Validates the entire scope of a lawful data request."""
        all_errors: List[str] = []

        if not request.case_id or not request.case_id.strip():
            all_errors.append("Request must be associated with a valid Case ID.")

        if not request.provider_id or not request.provider_id.strip():
            all_errors.append("Request must specify a target Provider ID.")

        if not request.targets:
            all_errors.append("Request must specify at least one target identifier.")
        else:
            for idx, target in enumerate(request.targets):
                target_errors = cls.validate_target(target, request.dataset_type)
                for err in target_errors:
                    all_errors.append(f"Target #{idx+1} ({target.target_value}): {err}")

        if all_errors:
            raise ScopeValidationError(
                f"Scope validation failed with {len(all_errors)} errors.",
                errors=all_errors
            )
