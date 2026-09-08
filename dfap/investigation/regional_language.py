# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Feature 5 - Regional Language Translation & Case-Specific Glossary Service (v10)

import json
import re
import uuid
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from dfap.investigation.event_sourcing import (
    DecisionEvent,
    DecisionState,
    EventStore,
    EventType,
)
from dfap.investigation.ollama_client import OllamaClient, OllamaUnavailableError


SUPPORTED_LANGUAGES = {
    "en": "English",
    "en-in": "English (India)",
    "hi": "Hindi",
    "hi-in": "Hindi (India)",
    "pa": "Punjabi",
    "pa-in": "Punjabi (India)",
}


def normalize_language_code(code: str) -> str:
    """
    Validates and normalizes regional language codes.
    hi-IN -> hi
    pa-IN -> pa
    en-IN -> en
    Rejects unsupported languages fail-closed.
    """
    clean = code.strip().lower().replace("_", "-")
    if clean not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"Unsupported language code '{code}'. DFAP Feature 5 strictly supports English ('en', 'en-IN'), "
            f"Hindi ('hi', 'hi-IN'), and Punjabi ('pa', 'pa-IN')."
        )
    if clean in ("hi", "hi-in"):
        return "hi"
    if clean in ("pa", "pa-in"):
        return "pa"
    if clean in ("en", "en-in"):
        return "en"
    return clean


class TranslatedSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    original_text: str = Field(..., description="Authoritative immutable source evidence text")
    original_lang: str = Field(..., description="Normalized source language code (en, hi, pa)")
    translated_text: str = Field(..., description="Derived translated text")
    target_lang: str = Field(..., description="Normalized target language code (en, hi, pa)")
    backtranslation_text: str = Field(..., description="Validation text back-translated to original_lang")
    consistency_score: float = Field(..., description="Deterministic cosine similarity score in [0.0, 1.0]")
    flagged_for_review: bool = Field(..., description="True if consistency is low or segment is below min length")
    glossary_terms_applied: List[str] = Field(default_factory=list, description="Case glossary terms injected")


class CaseGlossary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_context_id: str = Field(..., description="Authoritative case identifier scoping the glossary")
    terms: Dict[str, str] = Field(default_factory=dict, description="Case-specific term -> translated meaning")
    updated_via_event_ids: List[str] = Field(default_factory=list, description="Audit event IDs for corrections")


class RegionalLanguageService:
    """
    Regional Language Translation Service supporting Hindi (hi) and Punjabi (pa).
    Enforces original text immutability, back-translation validation, TF-IDF cosine consistency,
    short-segment safety flagging, and case-scoped glossary propagation.
    """

    def __init__(
        self,
        ollama_client: Optional[OllamaClient] = None,
        event_store: Optional[EventStore] = None,
        consistency_threshold: float = 0.70,
        min_consistency_length: int = 3,
    ):
        self.ollama = ollama_client or OllamaClient(timeout=120.0)
        self.event_store = event_store or EventStore()
        self.consistency_threshold = float(consistency_threshold)
        self.min_consistency_length = int(min_consistency_length)

        # In-memory case glossaries and segment registry
        self.case_glossaries: Dict[str, CaseGlossary] = {}
        self.segments: Dict[str, TranslatedSegment] = {}
        self.segment_case_map: Dict[str, str] = {}  # segment_id -> case_context_id

    def get_case_glossary(self, case_context_id: str) -> CaseGlossary:
        if case_context_id not in self.case_glossaries:
            self.case_glossaries[case_context_id] = CaseGlossary(case_context_id=case_context_id)
        return self.case_glossaries[case_context_id]

    def get_segment(self, segment_id: str) -> Optional[TranslatedSegment]:
        return self.segments.get(segment_id)

    def calculate_consistency(self, original_text: str, backtranslation_text: str) -> float:
        """
        Calculates cosine similarity between original_text and backtranslation_text
        using character n-gram TF-IDF vectors (robust across Indic scripts and English).
        Guarantees 0.0 <= score <= 1.0. Zero random numbers.
        """
        orig = original_text.strip()
        back = backtranslation_text.strip()

        if not orig or not back:
            return 0.0

        if orig == back:
            return 1.0

        try:
            vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
            matrix = vectorizer.fit_transform([orig, back])
            cos_sim = float(cosine_similarity(matrix[0:1], matrix[1:2])[0][0])
            clamped = float(np.clip(cos_sim, 0.0, 1.0))
            return round(clamped, 4)
        except Exception:
            return 0.0

    def apply_glossary(self, text: str, glossary: Dict[str, str]) -> Tuple[str, List[str]]:
        """Applies case-specific glossary overrides before or during translation."""
        applied = []
        result = text
        for term, repl in glossary.items():
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            if pattern.search(result):
                applied.append(term)
        return result, applied

    def translate_segment(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        glossary: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Translates text from source_lang to target_lang using local Ollama.
        Enforces case glossary constraints when provided.
        """
        src_norm = normalize_language_code(source_lang)
        tgt_norm = normalize_language_code(target_lang)

        if src_norm == tgt_norm:
            return text

        gloss_instruction = ""
        if glossary:
            gloss_str = json.dumps(glossary, ensure_ascii=False)
            gloss_instruction = f"\nCase Glossary constraints (use these translations for specific terms):\n{gloss_str}\n"

        prompt = f"""
Translate the following investigative text from {SUPPORTED_LANGUAGES[src_norm]} ({src_norm}) to {SUPPORTED_LANGUAGES[tgt_norm]} ({tgt_norm}).
{gloss_instruction}
Rules:
1. Translate accurately and objectively.
2. Do not add commentary, disclaimers, or explanations.
3. Preserve numbers, dates, timestamps, account numbers, and identifiers exactly.
4. Output ONLY the translated text.

Source Text:
"{text}"
"""
        try:
            resp = self.ollama.generate(
                prompt=prompt,
                system="You are an official police forensic translator. Output only the direct translation text. Never output explanations or commentary.",
                temperature=0.0
            )
            translated = resp.get("response", "").strip()
            # Strip quotes if wrapped
            if translated.startswith('"') and translated.endswith('"') and len(translated) > 1:
                translated = translated[1:-1].strip()
            return translated
        except OllamaUnavailableError:
            raise
        except Exception as e:
            raise RuntimeError(f"Translation execution failed: {str(e)}")

    def back_translate(self, translated_text: str, target_lang: str, original_lang: str) -> str:
        """Back-translates translated_text back to original_lang for consistency validation."""
        return self.translate_segment(
            text=translated_text,
            source_lang=target_lang,
            target_lang=original_lang,
            glossary=None
        )

    def translate_and_validate(
        self,
        original_text: str,
        source_lang: str,
        target_lang: str = "en",
        case_context_id: Optional[str] = None,
        segment_id: Optional[str] = None,
    ) -> TranslatedSegment:
        """
        Full translation pipeline:
        1. Preserve immutable original text
        2. Apply case-scoped glossary
        3. Translate
        4. Back-translate
        5. Calculate TF-IDF cosine consistency
        6. Apply short-segment and consistency review flags
        """
        src_norm = normalize_language_code(source_lang)
        tgt_norm = normalize_language_code(target_lang)

        # 1. Fetch case glossary if applicable
        glossary_terms = {}
        if case_context_id:
            glossary_obj = self.get_case_glossary(case_context_id)
            glossary_terms = glossary_obj.terms

        _, applied_terms = self.apply_glossary(original_text, glossary_terms)

        # 2. Execute translation and back-translation
        translated_text = self.translate_segment(
            text=original_text,
            source_lang=src_norm,
            target_lang=tgt_norm,
            glossary=glossary_terms
        )

        back_text = self.back_translate(
            translated_text=translated_text,
            target_lang=tgt_norm,
            original_lang=src_norm
        )

        # 3. Calculate consistency score
        score = self.calculate_consistency(original_text, back_text)

        # 4. Short-segment and consistency threshold checks
        tokens = [t for t in re.split(r"\s+", original_text.strip()) if t]
        token_count = len(tokens)

        is_short = token_count < self.min_consistency_length
        is_low_consistency = score < self.consistency_threshold

        flagged = is_short or is_low_consistency

        seg = TranslatedSegment(
            segment_id=segment_id or str(uuid.uuid4()),
            original_text=original_text,  # NEVER MUTATED
            original_lang=src_norm,
            translated_text=translated_text,
            target_lang=tgt_norm,
            backtranslation_text=back_text,
            consistency_score=score,
            flagged_for_review=flagged,
            glossary_terms_applied=applied_terms
        )

        # Store in registry
        self.segments[seg.segment_id] = seg
        if case_context_id:
            self.segment_case_map[seg.segment_id] = case_context_id

        return seg

    def add_glossary_term(
        self,
        case_context_id: str,
        term: str,
        corrected_translation: str,
        officer_id: str = "OFFICER_DEFAULT",
    ) -> str:
        """
        Adds or corrects a translation term in a case-scoped glossary.
        Appends an immutable GLOSSARY_CORRECTION event to EventStore.
        Propagates the correction ONLY to existing segments in the SAME case context.
        """
        glossary = self.get_case_glossary(case_context_id)
        glossary.terms[term] = corrected_translation

        # Log to EventStore
        event_id = None
        if self.event_store:
            evt_meta = {
                "case_context_id": case_context_id,
                "source_term": term,
                "corrected_translation": corrected_translation,
                "scope": "CASE_LOCAL_GLOSSARY",
            }
            ev = DecisionEvent(
                event_type=EventType.GLOSSARY_CORRECTION,
                officer_id=officer_id,
                case_id=case_context_id,
                entity_id=term,
                previous_state=DecisionState.NONE,
                requested_state=DecisionState.CONFIRMED,
                reason="Investigator corrected regional glossary translation term",
                metadata=evt_meta
            )
            self.event_store.append_event(ev)
            event_id = ev.event_id
            glossary.updated_via_event_ids.append(event_id)

        # Propagate within SAME case context only
        for seg_id, seg_case in list(self.segment_case_map.items()):
            if seg_case == case_context_id:
                existing_seg = self.segments.get(seg_id)
                if existing_seg and re.search(re.escape(term), existing_seg.original_text, re.IGNORECASE):
                    # Re-translate with updated glossary while preserving original_text and segment_id
                    self.translate_and_validate(
                        original_text=existing_seg.original_text,
                        source_lang=existing_seg.original_lang,
                        target_lang=existing_seg.target_lang,
                        case_context_id=case_context_id,
                        segment_id=existing_seg.segment_id
                    )

        return event_id or str(uuid.uuid4())
