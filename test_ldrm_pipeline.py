import sys
from datetime import datetime
from dfap.ldrm.gateway import initialize_ldrm
from dfap.ldrm_subsystem.domain.enums import TargetType, DatasetType, AuthorityType
from dfap.ldrm_subsystem.domain.models import RequestTarget
from dfap.investigation.workspace import InvestigationWorkspaceBackend, InvestigationCase

def main():
    backend = InvestigationWorkspaceBackend(
        output_dir="output",
        canonical_dir="data/canonical",
        cases_dir="data/cases",
    )
    case_id = "CASE-DFAP-LDRM-001"
    backend.cases[case_id] = InvestigationCase(case_id=case_id, canonical_entity_id="ENT_LDRM_TEST", status="OPEN", finding_ids=[])
    
    module = initialize_ldrm(backend)
    actor_id = "inv-001"
    
    target = RequestTarget(target_type=TargetType.BANK_ACCOUNT, target_value="+919876543210", start_time=datetime.fromisoformat("2026-01-01T00:00:00+00:00"), end_time=datetime.fromisoformat("2026-01-31T23:59:59+00:00"), justification="Investigating...", requested_categories=["all"])
    req = module.service.create_request(case_id, "prov-bank-001", DatasetType.BANK, [target], actor_id)
    req_id = req.id
    
    module.service.submit_for_validation(req_id, actor_id)
    req = module.repository.get_request(req_id)
    print("Status after validation:", req.status.value)
    
    if req.status.value == "NEEDS_CORRECTION":
        print("Correction notes:", module.audit_adapter.get_events_for_entity(req_id)[-1].metadata)
        return
        
    module.service.complete_legal_review(req_id, "legal-001", True, "Approved")
    
    req = module.repository.get_request(req_id)
    module.service.authorize_request(
        req_id, "legal-001", AuthorityType.COURT_ORDER,
        "WARRANT-2026-LDRM", "DISTRICT_COURT", "Approved",
        expected_version=req.request_version, expected_hash=req.canonical_hash
    )
    req = module.repository.get_request(req_id)
    
    module.service.sign_request(req_id, "sup-001", expected_hash=req.canonical_hash)
    module.service.dispatch_request(req_id, "sup-001")
    
    print("Pipeline Complete! SUCCESS!")

if __name__ == "__main__":
    main()
