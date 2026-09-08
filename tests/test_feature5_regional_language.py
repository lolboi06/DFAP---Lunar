# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Feature 5 - Regional Language (Hindi + Punjabi) Test Suite (Tests 1-12)

import pytest
from dfap.investigation.regional_language import (
    RegionalLanguageService,
    TranslatedSegment,
    CaseGlossary,
    normalize_language_code,
)
from dfap.investigation.event_sourcing import EventStore, EventType
from dfap.investigation.ollama_client import OllamaUnavailableError
from dfap.investigation.evidence_provenance import CanonicalEvidenceRecord, EvidenceType


@pytest.fixture
def lang_setup(tmp_path):
    store_file = tmp_path / "lang_events.jsonl"
    event_store = EventStore(str(store_file))
    service = RegionalLanguageService(event_store=event_store, consistency_threshold=0.70, min_consistency_length=3)
    return service, event_store


# TEST 1 — Hindi -> English translation schema
def test_1_hindi_to_english_schema(lang_setup):
    service, _ = lang_setup
    hindi_text = "खाता संख्या ACC-99420 में संदिग्ध नकद जमा पाया गया है।"
    seg = service.translate_and_validate(hindi_text, source_lang="hi", target_lang="en")

    assert isinstance(seg, TranslatedSegment)
    assert seg.original_text == hindi_text
    assert seg.original_lang == "hi"
    assert seg.target_lang == "en"
    assert len(seg.translated_text) > 0
    assert 0.0 <= seg.consistency_score <= 1.0


# TEST 2 — Punjabi -> English translation schema
def test_2_punjabi_to_english_schema(lang_setup):
    service, _ = lang_setup
    punjabi_text = "ਖਾਤਾ ਨੰਬਰ ACC-99420 ਵਿੱਚ ਸ਼ੱਕੀ ਲੈਣ-ਦੇਣ ਦਰਜ ਕੀਤਾ ਗਿਆ ਹੈ।"
    seg = service.translate_and_validate(punjabi_text, source_lang="pa", target_lang="en")

    assert isinstance(seg, TranslatedSegment)
    assert seg.original_text == punjabi_text
    assert seg.original_lang == "pa"
    assert seg.target_lang == "en"
    assert len(seg.translated_text) > 0
    assert 0.0 <= seg.consistency_score <= 1.0


class FastOllamaClient:
    def generate(self, prompt: str, **kwargs):
        if "to Hindi" in prompt:
            return {"response": "खाता संख्या ACC-99420 में संदिग्ध नकद जमा पाया गया है।"}
        elif "to Punjabi" in prompt:
            return {"response": "ਖਾਤਾ ਨੰਬਰ ACC-99420 ਵਿੱਚ ਸ਼ੱਕੀ ਲੈਣ-ਦੇਣ ਦਰਜ ਕੀਤਾ ਗਿਆ ਹੈ।"}
        return {"response": "Suspicious cash deposited in account ACC-99420."}

@pytest.fixture
def fast_lang_setup(tmp_path):
    store_file = tmp_path / "lang_fast_events.jsonl"
    event_store = EventStore(str(store_file))
    service = RegionalLanguageService(
        ollama_client=FastOllamaClient(),
        event_store=event_store,
        consistency_threshold=0.70,
        min_consistency_length=3
    )
    return service, event_store

# TEST 3 — Original text remains unchanged (Immutability)
def test_3_original_text_immutability(fast_lang_setup):
    service, _ = fast_lang_setup
    original = "ਇਹ ਅਸਲ ਸਬੂਤ ਪਾਠ ਹੈ ਜੋ ਬਦਲਿਆ ਨਹੀਂ ਜਾ ਸਕਦਾ।"
    seg = service.translate_and_validate(original, source_lang="pa", target_lang="en")

    assert seg.original_text == original
    assert seg.original_text != seg.translated_text


# TEST 4 — Back-translation runs
def test_4_back_translation_runs(fast_lang_setup):
    service, _ = fast_lang_setup
    text = "संदिग्ध व्यक्ति ने दिल्ली से मुंबई की यात्रा की।"
    seg = service.translate_and_validate(text, source_lang="hi", target_lang="en")

    assert seg.backtranslation_text is not None
    assert len(seg.backtranslation_text) > 0


# TEST 5 — Cosine consistency score is bounded 0–1
def test_5_cosine_consistency_bounded(lang_setup):
    service, _ = lang_setup
    s1 = "खाता संख्या 12345 में अवैध धनराशि स्थानांतरित की गई।"
    s2 = "ਖਾਤੇ ਵਿੱਚ ਪੈਸੇ ਟਰਾਂਸਫਰ ਕੀਤੇ ਗਏ।"

    score_identical = service.calculate_consistency(s1, s1)
    score_diff = service.calculate_consistency(s1, s2)
    score_empty = service.calculate_consistency(s1, "")

    assert score_identical == 1.0
    assert 0.0 <= score_diff <= 1.0
    assert score_empty == 0.0


# TEST 6 — Low consistency flags review
def test_6_low_consistency_flags_review(fast_lang_setup):
    service, _ = fast_lang_setup
    # Force high threshold to trigger low-consistency review flag
    service.consistency_threshold = 0.99
    text = "अज्ञात सर्वर से डेटा पैकेट भेजे गए और कनेक्शन तुरंत बंद कर दिया गया।"
    seg = service.translate_and_validate(text, source_lang="hi", target_lang="en")

    if seg.consistency_score < 0.99:
        assert seg.flagged_for_review is True


# TEST 7 — Short segment always flags review
def test_7_short_segment_always_flags(fast_lang_setup):
    service, _ = fast_lang_setup
    # Token count < 3
    short_hi = "नकद जमा"
    seg = service.translate_and_validate(short_hi, source_lang="hi", target_lang="en")

    assert seg.flagged_for_review is True


# TEST 8 — Glossary is case-scoped
def test_8_glossary_case_scoped(fast_lang_setup):
    service, _ = fast_lang_setup
    service.add_glossary_term("CASE_ALPHA", "हवाला", "hawala_transfer_alpha")

    gloss_a = service.get_case_glossary("CASE_ALPHA")
    gloss_b = service.get_case_glossary("CASE_BETA")

    assert "हवाला" in gloss_a.terms
    assert "हवाला" not in gloss_b.terms


# TEST 9 — Glossary correction creates EventStore event
def test_9_glossary_correction_event(fast_lang_setup):
    service, event_store = fast_lang_setup
    ev_id = service.add_glossary_term(
        case_context_id="CASE_ALPHA",
        term="ਦਰਬਾਰ",
        corrected_translation="court",
        officer_id="OFFICER_07"
    )
    assert ev_id is not None

    events = event_store.get_events()
    gloss_events = [e for e in events if e.event_type == EventType.GLOSSARY_CORRECTION]
    assert len(gloss_events) >= 1
    assert gloss_events[-1].officer_id == "OFFICER_07"
    assert gloss_events[-1].metadata["source_term"] == "ਦਰਬਾਰ"
    assert gloss_events[-1].metadata["corrected_translation"] == "court"


# TEST 10 — Glossary correction propagates only within the same case
def test_10_glossary_propagation_same_case_only(fast_lang_setup):
    service, _ = fast_lang_setup
    # Translate segment in CASE_A
    seg_a = service.translate_and_validate(
        "संदिग्ध हवाला नेटवर्क की पहचान की गई।",
        source_lang="hi",
        target_lang="en",
        case_context_id="CASE_A"
    )
    # Translate same segment in CASE_B
    seg_b = service.translate_and_validate(
        "संदिग्ध हवाला नेटवर्क की पहचान की गई।",
        source_lang="hi",
        target_lang="en",
        case_context_id="CASE_B"
    )

    # Correct term in CASE_A only
    service.add_glossary_term("CASE_A", "हवाला", "illicit remittance network")

    # Segment in CASE_A updated with applied glossary term
    updated_a = service.get_segment(seg_a.segment_id)
    updated_b = service.get_segment(seg_b.segment_id)

    assert "हवाला" in updated_a.glossary_terms_applied
    assert "हवाला" not in updated_b.glossary_terms_applied


# TEST 11 — M12 / Feature 2 still cites original evidence
def test_11_m12_feature2_cites_original_evidence(fast_lang_setup):
    service, _ = fast_lang_setup
    # Create canonical M12 evidence record
    raw_punjabi = "ਟ੍ਰਾਂਜੈਕਸ਼ਨ ਨੰਬਰ 99420 ਸਫਲਤਾਪੂਰਵਕ ਪੂਰੀ ਹੋਈ।"
    seg = service.translate_and_validate(raw_punjabi, source_lang="pa", target_lang="en")

    evidence = CanonicalEvidenceRecord(
        evidence_type=EvidenceType.SOURCE_RECORD,
        source_domain="FINANCIAL",
        source_id="TX_PUNJABI_001",
        source_file="punjabi_ledger.json",
        source_row_index=0,
        canonical_entity_ids=["ENT_PUNJABI_001"],
        event_ids=["EVT_PA_001"],
        observation_timestamp="2026-09-08T00:00:00Z",
        ingestion_timestamp="2026-09-08T00:00:00Z",
        derivation_method="DIRECT",
        evidence_id="EVD-PUNJABI-001",
        metadata={
            "original_text": raw_punjabi,
            "translation": seg.model_dump()
        }
    )

    # Authoritative evidence ID remains untouched
    assert evidence.evidence_id == "EVD-PUNJABI-001"
    # Metadata contains translated segment as a rendering layer
    assert evidence.metadata["translation"]["translated_text"] == seg.translated_text
    assert evidence.metadata["original_text"] == raw_punjabi


# TEST 12 — Ollama unavailable does not fabricate translation
def test_12_ollama_unavailable_no_fabrication():
    class BrokenOllamaClient:
        def generate(self, *args, **kwargs):
            raise OllamaUnavailableError("Local Ollama runtime unreachable")

    service = RegionalLanguageService(ollama_client=BrokenOllamaClient())

    with pytest.raises(OllamaUnavailableError):
        service.translate_segment("नमस्ते", "hi", "en")
