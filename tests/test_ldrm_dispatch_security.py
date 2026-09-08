from datetime import datetime
import pytest
from dfap.ldrm.gateway import initialize_ldrm
from dfap.ldrm_subsystem.domain.enums import TargetType, DatasetType, AuthorityType, RequestStatus
from dfap.ldrm_subsystem.domain.models import RequestTarget
from dfap.investigation.workspace import InvestigationWorkspaceBackend, InvestigationCase


def _setup_signed_request(backend, case_id="CASE-DFAP-LDRM-TEST"):
    backend.cases[case_id] = InvestigationCase(
        case_id=case_id,
        canonical_entity_id="ENT_LDRM_TEST",
        status="OPEN",
        finding_ids=[],
    )
    module = initialize_ldrm(backend)
    actor_id = "inv-001"
    
    target = RequestTarget(
        target_type=TargetType.BANK_ACCOUNT,
        target_value="+919876543210",
        start_time=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        end_time=datetime.fromisoformat("2026-01-31T23:59:59+00:00"),
        justification="Investigating transaction anomalies",
        requested_categories=["all"],
    )
    req = module.service.create_request(case_id, "prov-bank-001", DatasetType.BANK, [target], actor_id)
    req_id = req.id
    
    # 1. Validation -> transitions to LEGAL_REVIEW
    module.service.submit_for_validation(req_id, actor_id)
    req = module.repository.get_request(req_id)
    assert req.status == RequestStatus.LEGAL_REVIEW
    
    # 2. Complete Legal Review -> transitions to AUTHORIZATION_PENDING
    module.service.complete_legal_review(req_id, "legal-001", True, "Approved for court warrant")
    
    # 3. Authorize -> transitions to AUTHORIZED
    req = module.repository.get_request(req_id)
    module.service.authorize_request(
        req_id, "legal-001", AuthorityType.COURT_ORDER,
        "WARRANT-2026-LDRM", "DISTRICT_COURT", "Approved",
        expected_version=req.request_version, expected_hash=req.canonical_hash
    )
    
    # 4. Sign -> transitions to SIGNED
    req = module.repository.get_request(req_id)
    module.service.sign_request(req_id, "sup-001", expected_hash=req.canonical_hash)
    
    return module, req_id


def test_authorized_sender_dispatch_succeeds(tmp_path):
    backend = InvestigationWorkspaceBackend(
        output_dir=str(tmp_path / "output"),
        canonical_dir=str(tmp_path / "canonical"),
        cases_dir=str(tmp_path / "cases"),
    )
    module, req_id = _setup_signed_request(backend, "CASE-DFAP-LDRM-AUTH-001")
    
    # Dispatch with authorized sender configured
    module.service.dispatch_request(req_id, "sup-001")
    
    req = module.repository.get_request(req_id)
    assert req.status == RequestStatus.SENT
    
    # Verify email was captured by test transport with authorized sender
    messages = module.communication.captured_messages(req_id, "inv-001")
    assert len(messages) == 1
    assert messages[0]["message"]["sender"] == "requests@dfap.test"
    assert messages[0]["receipt"]["delivery_status"] == "CAPTURED_TEST_ONLY"


def test_unauthorized_sender_dispatch_rejected(tmp_path):
    backend = InvestigationWorkspaceBackend(
        output_dir=str(tmp_path / "output"),
        canonical_dir=str(tmp_path / "canonical"),
        cases_dir=str(tmp_path / "cases"),
    )
    module, req_id = _setup_signed_request(backend, "CASE-DFAP-LDRM-UNAUTH-001")
    
    # Simulate an unauthorized sender (missing authorization)
    unauthorized_sender = {
        "address": "unauthorized@dfap.test",
        "identity": "Unauthorized Sender",
        "authorized_by": None,  # No authorized_by attribute
    }
    module.repository.put("email_sender", "institution", unauthorized_sender)
    
    # Dispatch must fail with ValueError('Institutional sender is not authorized')
    with pytest.raises(ValueError, match="Institutional sender is not authorized"):
        module.service.dispatch_request(req_id, "sup-001")
    
    # Confirm request was not dispatched
    req = module.repository.get_request(req_id)
    assert req.status == RequestStatus.SIGNED


def test_missing_sender_dispatch_rejected(tmp_path):
    backend = InvestigationWorkspaceBackend(
        output_dir=str(tmp_path / "output"),
        canonical_dir=str(tmp_path / "canonical"),
        cases_dir=str(tmp_path / "cases"),
    )
    module, req_id = _setup_signed_request(backend, "CASE-DFAP-LDRM-MISSING-001")
    
    # Delete the sender entirely
    module.repository.connection.execute("DELETE FROM objects WHERE kind='email_sender'")
    
    # Dispatch must fail with ValueError('An authorized institutional test sender must be configured')
    with pytest.raises(ValueError, match="An authorized institutional test sender must be configured"):
        module.service.dispatch_request(req_id, "sup-001")
    
    req = module.repository.get_request(req_id)
    assert req.status == RequestStatus.SIGNED


def test_non_admin_cannot_configure_sender(tmp_path):
    backend = InvestigationWorkspaceBackend(
        output_dir=str(tmp_path / "output"),
        canonical_dir=str(tmp_path / "canonical"),
        cases_dir=str(tmp_path / "cases"),
    )
    module = initialize_ldrm(backend)
    
    # Investigator 'inv-001' cannot configure institutional sender
    with pytest.raises(PermissionError):
        module.communication.configure_sender("inv-001", "forged@dfap.test", "Forged Identity")
