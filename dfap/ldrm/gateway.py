from dfap.ldrm_subsystem.module import LawfulDataRequestModule
from dfap.ldrm_subsystem.integration.evidence_adapter import DefaultEvidenceAdapter
from dfap.ldrm_subsystem.integration.audit_adapter import DefaultAuditAdapter
from dfap.ldrm_subsystem.persistence.repositories import SQLiteRepository
from dfap.ldrm_subsystem.config import LDRMConfig
from dfap.ldrm.adapter import DFAPAuthAdapter, DFAPCaseAdapter
from dfap.ldrm.audit import DFAPAuditAdapter
from dfap.ldrm.ingestion import DFAPIngestionAdapter
from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.ldrm_subsystem.domain.provider import Provider, ProviderCategory, DatasetType, TransmissionMethod, ProviderDestination
from pathlib import Path
import os
import json

def initialize_ldrm(backend: InvestigationWorkspaceBackend) -> LawfulDataRequestModule:
    config = LDRMConfig(DEMO_MODE=True, USE_MOCK_PROVIDERS_ONLY=True, ENABLED=True)
    
    root = Path(config.STORAGE_DIR)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    repository = SQLiteRepository(root / 'ldrm.sqlite3')
    
    import secrets
    try:
        with open(root / 'audit.key', 'rb') as f:
            audit_key = f.read()
    except FileNotFoundError:
        audit_key = secrets.token_bytes(32)
        with open(root / 'audit.key', 'wb') as f:
            f.write(audit_key)

    auth_adapter = DFAPAuthAdapter(tokens={"012345678901234567890123": "inv-001"})
    case_adapter = DFAPCaseAdapter(backend)
    evidence_adapter = DefaultEvidenceAdapter(repository)
    audit_shim = DFAPAuditAdapter()
    ingestion_adapter = DFAPIngestionAdapter(canonical_dir=backend.canonical_dir)

    module = LawfulDataRequestModule(
        config=config,
        repository=repository,
        auth_adapter=auth_adapter,
        case_adapter=case_adapter,
        audit_adapter=audit_shim,
        evidence_adapter=evidence_adapter,
        ingestion_adapter=ingestion_adapter, audit_key=audit_key,
        tokens={"012345678901234567890123": "inv-001"}
    )
    
    # Ensure authorized institutional sender is configured and authorized via LDRM communication service
    try:
        sender = module.repository.get("email_sender", "institution")
        if not sender.get("authorized_by") or not sender.get("identity", "").strip():
            module.communication.configure_sender("admin-001", "requests@dfap.test", "DFAP Law Enforcement Authority")
    except KeyError:
        module.communication.configure_sender("admin-001", "requests@dfap.test", "DFAP Law Enforcement Authority")

    # Load synthetic providers
    existing = module.service.provider_registry.list_providers("admin-001")
    if not existing:
        p_bank = Provider(
            id="prov-bank-001", name="Example National Bank", category=ProviderCategory.BANK,
            supported_datasets=[DatasetType.BANK], submission_methods=[TransmissionMethod.OFFICIAL_EMAIL],
            destinations=[ProviderDestination("dst-bank", TransmissionMethod.OFFICIAL_EMAIL, "compliance@example-bank.test")]
        )
        module.service.provider_registry.register_provider(p_bank, "admin-001")
        module.service.provider_registry.verify_provider(p_bank.id, "admin-001", "Auto-verified")
        module.service.provider_registry.verify_destination(p_bank.id, "dst-bank", "admin-001")

        p_telecom = Provider(
            id="prov-telco-001", name="National Telecom", category=ProviderCategory.TELECOM,
            supported_datasets=[DatasetType.CDR], submission_methods=[TransmissionMethod.PROVIDER_PORTAL],
            destinations=[ProviderDestination("dst-telco", TransmissionMethod.PROVIDER_PORTAL, "https://portal.nat-telecom.test")]
        )
        module.service.provider_registry.register_provider(p_telecom, "admin-001")
        module.service.provider_registry.verify_provider(p_telecom.id, "admin-001", "Auto-verified")
        module.service.provider_registry.verify_destination(p_telecom.id, "dst-telco", "admin-001")

        p_isp = Provider(
            id="prov-isp-001", name="National ISP", category=ProviderCategory.ISP,
            supported_datasets=[DatasetType.IPDR], submission_methods=[TransmissionMethod.OFFICIAL_EMAIL],
            destinations=[ProviderDestination("dst-isp", TransmissionMethod.OFFICIAL_EMAIL, "legal@isp.test")]
        )
        module.service.provider_registry.register_provider(p_isp, "admin-001")
        module.service.provider_registry.verify_provider(p_isp.id, "admin-001", "Auto-verified")
        module.service.provider_registry.verify_destination(p_isp.id, "dst-isp", "admin-001")

        p_social = Provider(
            id="prov-social-001", name="Global Social", category=ProviderCategory.SOCIAL_PLATFORM,
            supported_datasets=[DatasetType.SOCIAL], submission_methods=[TransmissionMethod.OFFICIAL_API],
            destinations=[ProviderDestination("dst-social", TransmissionMethod.OFFICIAL_API, "https://api.social.test/requests")]
        )
        module.service.provider_registry.register_provider(p_social, "admin-001")
        module.service.provider_registry.verify_provider(p_social.id, "admin-001", "Auto-verified")
        module.service.provider_registry.verify_destination(p_social.id, "dst-social", "admin-001")

    return module
