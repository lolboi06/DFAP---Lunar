from typing import Optional, List, Any, Dict
from dfap.ldrm_subsystem.integration.auth_adapter import AuthAdapter, UserContext, MockAuthAdapter
from dfap.ldrm_subsystem.integration.case_adapter import CaseAdapter, CaseContext
from dfap.investigation.workspace import InvestigationCase, InvestigationWorkspaceBackend

class DFAPAuthAdapter(MockAuthAdapter):
    pass

class DFAPCaseAdapter(CaseAdapter):
    def __init__(self, backend: InvestigationWorkspaceBackend):
        self.backend = backend

    def get_case(self, case_id: str) -> Optional[CaseContext]:
        case = self.backend.cases.get(case_id)
        if not case:
            return None
        return CaseContext(
            case_id=case.case_id,
            case_number=case.case_id,
            title=f"Investigation {case.case_id}",
            is_active=case.status == "OPEN",
            lead_investigator_id="inv-001",
            assigned_members=["inv-001", "inv-002", "legal-001", "sup-001", "admin-001"]
        )

    def validate_case_active(self, case_id: str) -> bool:
        case = self.get_case(case_id)
        return bool(case and case.is_active)

    def attach_request_to_case(self, case_id: str, request_id: str) -> None:
        case = self.backend.cases.get(case_id)
        if case:
            if "ldrm_requests" not in case.search_context:
                case.search_context["ldrm_requests"] = []
            if request_id not in case.search_context["ldrm_requests"]:
                case.search_context["ldrm_requests"].append(request_id)

    def user_has_case_access(self, user_id: str, case_id: str, required_permission: str = "VIEW") -> bool:
        case = self.get_case(case_id)
        if not case:
            return False
        return user_id in case.assigned_members
