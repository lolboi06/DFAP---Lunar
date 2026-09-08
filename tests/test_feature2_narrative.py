import pytest
from dfap.investigation.workspace import InvestigationWorkspaceBackend
from dfap.investigation.four_domain_fixture import register_four_domain_fixture, FND_4DOM_FUSED
from dfap.investigation.narrative_generator import (
    NarrativeGeneratorService, NarrativeTemplate, Claim, ClaimType, SourceModule
)

@pytest.fixture
def backend():
    b = InvestigationWorkspaceBackend(output_dir="output", canonical_dir="data/canonical", cases_dir="data/cases")
    register_four_domain_fixture(b)
    return b

def test_generate_narrative_internal_brief(backend):
    gen = NarrativeGeneratorService(backend)
    nar = gen.generate_narrative(FND_4DOM_FUSED, NarrativeTemplate.INTERNAL_BRIEF)
    
    assert nar.finding_id == FND_4DOM_FUSED
    assert nar.template == NarrativeTemplate.INTERNAL_BRIEF
    # Abstention claim should be forced due to M11 conflict
    abstained = [c for c in nar.claims if c.claim_type == ClaimType.ABSTAINED]
    assert len(abstained) == 1
    assert "ABSTENTION REQUIRED" in abstained[0].text
    
def test_invalid_citation_rejection(backend):
    gen = NarrativeGeneratorService(backend)
    bad_claim = Claim(
        text="A fabricated claim with bad evidence.",
        claim_type=ClaimType.DIRECTLY_EVIDENCED,
        evidence_refs=["FAKE_EVID_999"],
        confidence=0.9,
        source_module=SourceModule.M9
    )
    valid_ev_ids = {e['evidence_id'] for e in gen._get_evidence_context(FND_4DOM_FUSED)}
    
    # 2 retries
    validated = gen._validate_and_retry_claim(bad_claim, valid_ev_ids, FND_4DOM_FUSED, max_retries=2)
    assert validated.manual_drafting_required == True

def test_repeated_evidence_flag(backend):
    gen = NarrativeGeneratorService(backend)
    nar = gen.generate_narrative(FND_4DOM_FUSED, NarrativeTemplate.INTERNAL_BRIEF)
    # Manually inject a claim repeating evidence
    valid_ev_ids = list({e['evidence_id'] for e in gen._get_evidence_context(FND_4DOM_FUSED)})
    if valid_ev_ids:
        c1 = Claim(
            text="Claim 1", claim_type=ClaimType.DIRECTLY_EVIDENCED, evidence_refs=[valid_ev_ids[0]],
            confidence=0.9, source_module=SourceModule.M9
        )
        c2 = Claim(
            text="Claim 2", claim_type=ClaimType.DIRECTLY_EVIDENCED, evidence_refs=[valid_ev_ids[0]],
            confidence=0.9, source_module=SourceModule.M9
        )
        nar.claims.insert(0, c1)
        nar.claims.insert(1, c2)
        
        rendered = gen.render_narrative(nar)
        assert "[Warning: Repeated citation usage" in rendered

def test_court_summary_separation(backend):
    gen = NarrativeGeneratorService(backend)
    nar = gen.generate_narrative(FND_4DOM_FUSED, NarrativeTemplate.COURT_SUMMARY)
    
    c1 = Claim(
        text="AI synth claim", claim_type=ClaimType.AI_SYNTHESIZED, evidence_refs=[],
        confidence=0.9, source_module=SourceModule.M9
    )
    nar.claims.append(c1)
    
    rendered = gen.render_narrative(nar)
    assert "--- Investigative Interpretation ---" in rendered
    assert "AI synth claim" in rendered.split("--- Investigative Interpretation ---")[1]

def test_m4_m12_immutability(backend):
    # Simply ensures we don't modify the graph
    edges_before = len(backend.evidence_engine.graph.edges)
    gen = NarrativeGeneratorService(backend)
    gen.generate_narrative(FND_4DOM_FUSED, NarrativeTemplate.INTERNAL_BRIEF)
    edges_after = len(backend.evidence_engine.graph.edges)
    assert edges_before == edges_after
