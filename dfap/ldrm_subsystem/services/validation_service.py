"""
Validation Service for Lawful Data Request Module.
"""
from typing import Optional, List

from dfap.ldrm_subsystem.domain.models import LawfulDataRequest
from dfap.ldrm_subsystem.domain.enums import RequestStatus
from dfap.ldrm_subsystem.policy.scope_validator import ScopeValidator, ScopeValidationError
from dfap.ldrm_subsystem.policy.state_machine import RequestStateMachine
from dfap.ldrm_subsystem.providers.registry import ProviderRegistry, ProviderRegistryError
from dfap.ldrm_subsystem.integration.case_adapter import CaseAdapter
from dfap.ldrm_subsystem.integration.audit_adapter import AuditAdapter

class ValidationServiceError(Exception):
    """Raised when validation service encounters fatal verification errors."""
    pass


class ValidationService:
    """
    Orchestrates business rule, scope, case boundary, and provider compatibility validation.
    """

    def __init__(
        self,
        case_adapter: CaseAdapter,
        provider_registry: ProviderRegistry,
        audit_adapter: AuditAdapter,
    ):
        self.case_adapter = case_adapter
        self.provider_registry = provider_registry
        self.audit_adapter = audit_adapter

    def validate_for_submission(self, request: LawfulDataRequest, actor_id: str) -> None:
        """
        Validates request when moving from DRAFT to VALIDATION_PENDING.
        Checks case active status, scope rules, and provider registry.
        """
        errors: List[str] = []

        # 1. Case validation
        if not self.case_adapter.validate_case_active(request.case_id):
            errors.append(f"Case '{request.case_id}' does not exist or is closed/inactive.")

        # 2. Case access check
        if not self.case_adapter.user_has_case_access(actor_id, request.case_id, required_permission="EDIT"):
            errors.append(f"User '{actor_id}' is not authorized to submit requests for Case '{request.case_id}'.")

        # 3. Scope validation
        try:
            ScopeValidator.validate_request_scope(request)
        except ScopeValidationError as e:
            errors.extend(e.errors)

        # 4. Provider validation
        try:
            self.provider_registry.validate_provider_for_dispatch(request.provider_id, request.dataset_type)
        except ProviderRegistryError as e:
            errors.append(str(e))

        if errors:
            self.audit_adapter.log_event(
                action="VALIDATION_FAILED",
                entity_type="LawfulDataRequest",
                entity_id=request.id,
                actor_id=actor_id,
                metadata={"error_count": len(errors), "errors": errors},
            )
            raise ValidationServiceError(f"Validation failed: {'; '.join(errors)}")

        self.audit_adapter.log_event(
            action="VALIDATION_PASSED",
            entity_type="LawfulDataRequest",
            entity_id=request.id,
            actor_id=actor_id,
            metadata={"status": RequestStatus.LEGAL_REVIEW.value},
        )
