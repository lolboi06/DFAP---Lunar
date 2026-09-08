"""
Clarification Service for Lawful Data Request Module (LDRM).
Manages provider queries (PROVIDER_QUERY state), clarification responses, and scope mutation invalidation.
"""
import uuid
from typing import Dict, Any, Optional

from dfap.ldrm_subsystem.domain.enums import RequestStatus
from dfap.ldrm_subsystem.domain.utils import utc_now
from dfap.ldrm_subsystem.policy.state_machine import transition_request


class ClarificationService:
    def __init__(self, repository, request_service=None):
        self.repository = repository
        self.request_service = request_service

    def receive_provider_query(
        self,
        request_id: str,
        provider_id: str,
        query_text: str,
        actor: str = "PROVIDER_COMMUNICATION",
    ) -> Dict[str, Any]:
        """
        Records an inbound clarification query from provider and transitions request to PROVIDER_QUERY state.
        """
        request = self.repository.get_request(request_id)
        
        # Transition state to PROVIDER_QUERY
        transition_request(request, RequestStatus.PROVIDER_QUERY, actor=actor, note=query_text)
        self.repository.save_request(request)

        query_id = f"QRY-{uuid.uuid4().hex[:12]}"
        query_data = {
            "id": query_id,
            "request_id": request_id,
            "provider_id": provider_id,
            "query_text": query_text,
            "received_at": utc_now(),
            "response_text": None,
            "responded_by": None,
            "responded_at": None,
            "scope_modified": False,
        }
        
        if hasattr(self.repository, "insert_provider_query"):
            self.repository.insert_provider_query(query_data)

        return query_data

    def respond_to_query(
        self,
        query_id: str,
        request_id: str,
        response_text: str,
        actor: str,
        scope_modified: bool = False,
    ) -> Dict[str, Any]:
        """
        Submits investigator response to provider query.
        If scope_modified is True (scope mutated), invalidates current legal authorization and resets request state to NEEDS_CORRECTION.
        Otherwise resumes provider processing.
        """
        request = self.repository.get_request(request_id)
        now = utc_now()

        if scope_modified:
            # Invalidate legal authorization cryptographic binding and return to correction flow
            request.authorization = None
            transition_request(
                request,
                RequestStatus.NEEDS_CORRECTION,
                actor=actor,
                note=f"Scope mutated during provider query response: {response_text}. Legal re-authorization required.",
            )
        else:
            # Return to provider processing
            transition_request(
                request,
                RequestStatus.PROVIDER_PROCESSING,
                actor=actor,
                note=f"Clarification provided: {response_text}",
            )

        self.repository.save_request(request)

        if hasattr(self.repository, "update_provider_query"):
            self.repository.update_provider_query(
                query_id=query_id,
                response_text=response_text,
                responded_by=actor,
                responded_at=now,
                scope_modified=scope_modified,
            )

        return {
            "query_id": query_id,
            "request_id": request_id,
            "status": request.status.value,
            "scope_modified": scope_modified,
            "authorization_invalidated": scope_modified,
        }

    def list_queries(self, request_id: str):
        """Lists all provider clarification queries for a request."""
        if hasattr(self.repository, "list_provider_queries"):
            return self.repository.list_provider_queries(request_id)
        return []
