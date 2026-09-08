"""
Backend-Enforced State Machine for Lawful Data Request Lifecycle.
"""
from typing import Set, Dict, Optional, List
from dfap.ldrm_subsystem.domain.enums import RequestStatus

class InvalidStateTransitionError(Exception):
    """Raised when an illegal state transition is attempted."""
    def __init__(self, current_status: RequestStatus, target_status: RequestStatus, reason: Optional[str] = None):
        self.current_status = current_status
        self.target_status = target_status
        self.reason = reason or f"Transition from {current_status.value} to {target_status.value} is not permitted."
        super().__init__(self.reason)


class RequestStateMachine:
    """
    Guarantees strict lifecycle transition enforcement for Lawful Data Requests.
    """
    
    # Map of State -> Set of Allowed Next States
    _ALLOWED_TRANSITIONS: Dict[RequestStatus, Set[RequestStatus]] = {
        RequestStatus.DRAFT: {
            RequestStatus.VALIDATION_PENDING,
            RequestStatus.CANCELLED,
        },
        RequestStatus.VALIDATION_PENDING: {
            RequestStatus.LEGAL_REVIEW,
            RequestStatus.NEEDS_CORRECTION,
            RequestStatus.CANCELLED,
        },
        RequestStatus.LEGAL_REVIEW: {
            RequestStatus.AUTHORIZATION_PENDING,
            RequestStatus.NEEDS_CORRECTION,
            RequestStatus.REJECTED,
            RequestStatus.CANCELLED,
        },
        RequestStatus.AUTHORIZATION_PENDING: {
            RequestStatus.AUTHORIZED,
            RequestStatus.NEEDS_CORRECTION,
            RequestStatus.REJECTED,
            RequestStatus.CANCELLED,
        },
        RequestStatus.AUTHORIZED: {
            RequestStatus.SIGNED,
            RequestStatus.NEEDS_CORRECTION,  # Occurs if modified post-auth
            RequestStatus.CANCELLED,
            RequestStatus.EXPIRED,
        },
        RequestStatus.SIGNED: {
            RequestStatus.READY_TO_SEND,
            RequestStatus.READY_FOR_MANUAL_SUBMISSION,
            RequestStatus.NEEDS_CORRECTION,
            RequestStatus.CANCELLED,
            RequestStatus.EXPIRED,
        },
        RequestStatus.READY_TO_SEND: {
            RequestStatus.SENT,
            RequestStatus.NEEDS_CORRECTION,
            RequestStatus.CANCELLED,
            RequestStatus.EXPIRED,
        },
        RequestStatus.READY_FOR_MANUAL_SUBMISSION: {
            RequestStatus.SENT,
            RequestStatus.ACKNOWLEDGED,
            RequestStatus.NEEDS_CORRECTION,
            RequestStatus.CANCELLED,
            RequestStatus.EXPIRED,
        },
        RequestStatus.SENT: {
            RequestStatus.ACKNOWLEDGED,
            RequestStatus.PROVIDER_PROCESSING,
            RequestStatus.RESPONSE_PENDING,
            RequestStatus.PROVIDER_QUERY,
            RequestStatus.REJECTED,
            RequestStatus.CANCELLED,
            RequestStatus.EXPIRED,
        },
        RequestStatus.ACKNOWLEDGED: {
            RequestStatus.PROVIDER_PROCESSING,
            RequestStatus.RESPONSE_PENDING,
            RequestStatus.RESPONSE_RECEIVED,
            RequestStatus.PARTIAL_RESPONSE,
            RequestStatus.PROVIDER_QUERY,
            RequestStatus.REJECTED,
            RequestStatus.CANCELLED,
            RequestStatus.EXPIRED,
        },
        RequestStatus.PROVIDER_PROCESSING: {
            RequestStatus.RESPONSE_PENDING,
            RequestStatus.RESPONSE_RECEIVED,
            RequestStatus.PARTIAL_RESPONSE,
            RequestStatus.PROVIDER_QUERY,
            RequestStatus.REJECTED,
            RequestStatus.CANCELLED,
            RequestStatus.EXPIRED,
        },
        RequestStatus.RESPONSE_PENDING: {
            RequestStatus.RESPONSE_RECEIVED,
            RequestStatus.PARTIAL_RESPONSE,
            RequestStatus.PROVIDER_QUERY,
            RequestStatus.REJECTED,
            RequestStatus.EXPIRED,
            RequestStatus.CANCELLED,
        },
        RequestStatus.PROVIDER_QUERY: {
            RequestStatus.PROVIDER_PROCESSING,
            RequestStatus.SENT,
            RequestStatus.RESPONSE_PENDING,
            RequestStatus.NEEDS_CORRECTION,
            RequestStatus.CANCELLED,
        },
        RequestStatus.PARTIAL_RESPONSE: {
            RequestStatus.RESPONSE_RECEIVED,
            RequestStatus.EVIDENCE_VERIFIED,
            RequestStatus.RESPONSE_PENDING,
            RequestStatus.PROVIDER_QUERY,
            RequestStatus.CANCELLED,
            RequestStatus.EXPIRED,
        },
        RequestStatus.RESPONSE_RECEIVED: {
            RequestStatus.EVIDENCE_VERIFIED,
        },
        RequestStatus.EVIDENCE_VERIFIED: {
            RequestStatus.INGESTED,
        },
        RequestStatus.INGESTED: {
            RequestStatus.CLOSED,
        },
        RequestStatus.NEEDS_CORRECTION: {
            RequestStatus.DRAFT,
            RequestStatus.VALIDATION_PENDING,
            RequestStatus.CANCELLED,
        },
        # Terminal states have no forward transitions
        RequestStatus.REJECTED: set(),
        RequestStatus.EXPIRED: set(),
        RequestStatus.CANCELLED: set(),
        RequestStatus.CLOSED: set(),
    }

    @classmethod
    def can_transition(cls, from_status: RequestStatus, to_status: RequestStatus) -> bool:
        """Check if transition is valid without raising an exception."""
        allowed = cls._ALLOWED_TRANSITIONS.get(from_status, set())
        return to_status in allowed

    @classmethod
    def validate_transition(cls, from_status: RequestStatus, to_status: RequestStatus) -> None:
        """Validate transition, raising InvalidStateTransitionError if illegal."""
        if not cls.can_transition(from_status, to_status):
            raise InvalidStateTransitionError(from_status, to_status)

    @classmethod
    def get_allowed_next_states(cls, current_status: RequestStatus) -> List[RequestStatus]:
        """Return all legal next states from the current status."""
        return sorted(list(cls._ALLOWED_TRANSITIONS.get(current_status, set())), key=lambda x: x.value)


def transition(request, target, actor_id, audit, reason=""):
    RequestStateMachine.validate_transition(request.status, target)
    previous = request.status
    request.status = target
    from dfap.ldrm_subsystem.domain.utils import utc_now
    request.updated_at = utc_now()
    if audit:
        audit.log_event("STATE_CHANGED", "LawfulDataRequest", request.id, actor_id,
                        {"from": previous.value, "to": target.value, "reason": reason,
                         "case_id": request.case_id, "version": request.request_version})


def transition_request(request, target_status, actor="SYSTEM", note="", audit=None):
    if isinstance(target_status, str):
        target_status = RequestStatus(target_status)
    transition(request, target_status, actor, audit, reason=note)

