"""
Case Adapter Interface and Implementation for DFAP Case Integration.
"""
from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

@dataclass
class CaseContext:
    case_id: str
    case_number: str
    title: str
    is_active: bool
    lead_investigator_id: str
    assigned_members: List[str]


class CaseAdapter(ABC):
    """Abstract interface to the DFAP Case subsystem."""

    @abstractmethod
    def get_case(self, case_id: str) -> Optional[CaseContext]:
        """Fetch case metadata."""
        pass

    @abstractmethod
    def validate_case_active(self, case_id: str) -> bool:
        """Verify that a case exists and is currently active."""
        pass

    @abstractmethod
    def attach_request_to_case(self, case_id: str, request_id: str) -> None:
        """Register a lawful request association in the case workspace."""
        pass

    @abstractmethod
    def user_has_case_access(self, user_id: str, case_id: str, required_permission: str = "VIEW") -> bool:
        """Verify investigator/user authorization for a specific case."""
        pass


class MockCaseAdapter(CaseAdapter):
    """
    Default in-memory / service-backed implementation of CaseAdapter.
    """

    def __init__(self):
        # In-memory case store for demonstration & isolated integration
        self._cases: Dict[str, CaseContext] = {
            "CASE-2026-001": CaseContext(
                case_id="CASE-2026-001",
                case_number="FIR-402/2026",
                title="Operation High Sierra - Telecom Fraud",
                is_active=True,
                lead_investigator_id="inv-001",
                assigned_members=["inv-001", "inv-002", "legal-001", "sup-001", "admin-001"],
            ),
            "CASE-2026-002": CaseContext(
                case_id="CASE-2026-002",
                case_number="FIR-405/2026",
                title="Project Shadowgate - Cross-Border Money Laundering",
                is_active=True,
                lead_investigator_id="inv-002",
                assigned_members=["inv-002", "legal-001", "admin-001"],
            ),
            "CASE-CLOSED-999": CaseContext(
                case_id="CASE-CLOSED-999",
                case_number="FIR-100/2025",
                title="Archived Investigation",
                is_active=False,
                lead_investigator_id="inv-001",
                assigned_members=["inv-001"],
            ),
        }
        self._case_requests: Dict[str, List[str]] = {}

    def get_case(self, case_id: str) -> Optional[CaseContext]:
        if case_id not in self._cases and case_id.startswith("CASE-") and "CLOSED" not in case_id:
            self._cases[case_id] = CaseContext(
                case_id=case_id,
                case_number=case_id,
                title=f"Dynamic Test Case {case_id}",
                is_active=True,
                lead_investigator_id="inv-001",
                assigned_members=["inv-001", "inv-002", "legal-001", "sup-001", "admin-001"],
            )
        return deepcopy(self._cases.get(case_id))

    def validate_case_active(self, case_id: str) -> bool:
        case = self.get_case(case_id)
        return bool(case and case.is_active)

    def attach_request_to_case(self, case_id: str, request_id: str) -> None:
        if case_id not in self._case_requests:
            self._case_requests[case_id] = []
        if request_id not in self._case_requests[case_id]:
            self._case_requests[case_id].append(request_id)

    def user_has_case_access(self, user_id: str, case_id: str, required_permission: str = "VIEW") -> bool:
        case = self.get_case(case_id)
        if not case:
            return False
        return user_id in case.assigned_members

# Compatibility alias for the explicit test double.
DefaultCaseAdapter = MockCaseAdapter
