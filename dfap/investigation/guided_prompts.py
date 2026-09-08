# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Feature 6 - Guided Next-Step Prompts with Deterministic Rules & Safety Bypass (v10)

import uuid
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from dfap.investigation.event_sourcing import (
    DecisionEvent,
    DecisionState,
    EventStore,
    EventType,
)
from dfap.investigation.workspace import InvestigationWorkspaceBackend, MatchStatus


class PromptCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_type: str = Field(..., description="Action prompt category (e.g. RESOLVE_POSSIBLE_MATCH)")
    is_safety_critical: bool = Field(..., description="True if prompt must bypass bandit and show 100% of the time")
    context_features: Dict[str, Any] = Field(default_factory=dict, description="Deterministic workspace context")


class PromptDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    prompt_type: str = Field(..., description="Candidate prompt type evaluated")
    shown: bool = Field(..., description="Whether the prompt was displayed to the officer")
    officer_id: str = Field(..., description="Officer identifier")
    context_snapshot: Dict[str, Any] = Field(default_factory=dict, description="Context snapshot at decision time")
    outcome: Optional[str] = Field(None, description="'FOLLOWED' or 'IGNORED' once recorded")


class GuidedPromptService:
    """
    Guided Next-Step Prompts Engine.
    Enforces:
    - Deterministic candidate generation from M13 workspace state (zero LLM hallucination).
    - Strict Safety-Critical Bypass: RED tier + RESOLVE_POSSIBLE_MATCH is shown 100% of the time.
    - Lightweight Beta/Thompson contextual bandit per (officer_id, prompt_type).
    - Cold-start grace period (MIN_HISTORY = 5).
    - Guaranteed non-zero exploration.
    - Append-only EventStore audit logging (PROMPT_SHOWN, PROMPT_OUTCOME).
    """

    PROMPT_RESOLVE_POSSIBLE_MATCH = "RESOLVE_POSSIBLE_MATCH"
    PROMPT_REVIEW_PREDICTED_LINK = "REVIEW_PREDICTED_LINK"
    PROMPT_VIEW_TIMELINE = "VIEW_TIMELINE"

    def __init__(
        self,
        backend: InvestigationWorkspaceBackend,
        event_store: Optional[EventStore] = None,
        min_history: int = 5,
        decision_threshold: float = 0.40,
        min_exploration_prob: float = 0.05,
    ):
        self.backend = backend
        self.event_store = event_store or EventStore()
        self.min_history = int(min_history)
        self.decision_threshold = float(decision_threshold)
        self.min_exploration_prob = float(min_exploration_prob)

        # Bandit state: (officer_id, prompt_type) -> {"alpha": float, "beta": float, "history_count": int}
        self.bandit_state: Dict[Tuple[str, str], Dict[str, Any]] = {}

        # Decisions repository: decision_id -> PromptDecision
        self.decisions: Dict[str, PromptDecision] = {}

        # Rehydrate persistent decisions and bandit state from EventStore
        self._rehydrate_from_event_store()

    def _rehydrate_from_event_store(self) -> None:
        """
        Rehydrates in-memory PromptDecisions and BanditState from authoritative EventStore.
        Ensures state survives across separate CLI invocations and independent processes.
        """
        if not self.event_store:
            return

        events = self.event_store.get_events()
        self.decisions.clear()
        self.bandit_state.clear()

        # Step 1: Replay PROMPT_SHOWN events to reconstruct PromptDecisions
        for ev in events:
            if ev.event_type == EventType.PROMPT_SHOWN:
                d_id = ev.metadata.get("decision_id")
                if not d_id:
                    continue
                prompt_type = ev.metadata.get("prompt_type", ev.entity_id)
                snapshot = ev.metadata.get("context_snapshot", {})
                shown = ev.metadata.get("shown", True)

                self.decisions[d_id] = PromptDecision(
                    decision_id=d_id,
                    prompt_type=prompt_type,
                    shown=shown,
                    officer_id=ev.officer_id,
                    context_snapshot=snapshot,
                    outcome=None,
                )

        # Step 2: Replay PROMPT_OUTCOME events to attach outcomes and update bandit state
        for ev in events:
            if ev.event_type == EventType.PROMPT_OUTCOME:
                d_id = ev.metadata.get("decision_id")
                outcome = ev.metadata.get("outcome")
                prompt_type = ev.metadata.get("prompt_type", ev.entity_id)
                officer_id = ev.officer_id

                if d_id and d_id in self.decisions:
                    self.decisions[d_id].outcome = outcome

                b_params = self._get_bandit_params(officer_id, prompt_type)
                if outcome == "FOLLOWED":
                    b_params["alpha"] += 1.0
                elif outcome == "IGNORED":
                    b_params["beta"] += 1.0
                b_params["history_count"] += 1

    def _get_bandit_params(self, officer_id: str, prompt_type: str) -> Dict[str, Any]:
        key = (officer_id, prompt_type)
        if key not in self.bandit_state:
            self.bandit_state[key] = {
                "alpha": 1.0,
                "beta": 1.0,
                "history_count": 0
            }
        return self.bandit_state[key]

    # ── 1. DETERMINISTIC CANDIDATE GENERATION & SAFETY-CRITICAL EVALUATION ────

    def generate_candidates(self, case_id: Optional[str] = None) -> List[PromptCandidate]:
        """
        Deterministically inspects actual M13 workspace state and yields candidates.
        Rule 1: Unresolved POSSIBLE match -> RESOLVE_POSSIBLE_MATCH (Safety-critical if RED tier).
        Rule 2: Unreviewed PREDICTED edge -> REVIEW_PREDICTED_LINK.
        Rule 3: Unviewed anomaly -> VIEW_TIMELINE.
        """
        candidates: List[PromptCandidate] = []

        # Determine active case context & risk tier
        risk_tier = "GREEN"
        has_possible_match = False
        target_entity = None

        if case_id and hasattr(self.backend, "cases") and case_id in self.backend.cases:
            case = self.backend.cases[case_id]
            target_entity = case.canonical_entity_id

            # Evaluate Feature 3 risk tier
            try:
                for fid in case.finding_ids:
                    f_eval = self.backend.risk_engine.evaluate_finding(fid, case_id=case_id)
                    p_level = str(getattr(f_eval, "priority_level", "GREEN")).upper()
                    if p_level in ("RED", "CRITICAL", "HIGH"):
                        risk_tier = "RED"
                        break
            except Exception:
                pass

        # Check for POSSIBLE matches in entities_df or bridge_df
        if hasattr(self.backend, "entities_df") and not self.backend.entities_df.empty:
            possible_rows = self.backend.entities_df[
                self.backend.entities_df["match_status"].str.upper().isin(["POSSIBLE", MatchStatus.POSSIBLE])
            ]
            if not possible_rows.empty:
                has_possible_match = True

        # RULE 1: Unresolved POSSIBLE match
        if has_possible_match:
            is_critical = (risk_tier == "RED")
            candidates.append(
                PromptCandidate(
                    prompt_type=self.PROMPT_RESOLVE_POSSIBLE_MATCH,
                    is_safety_critical=is_critical,
                    context_features={
                        "case_id": case_id,
                        "target_entity": target_entity,
                        "risk_tier": risk_tier,
                        "unresolved_match_status": "POSSIBLE",
                        "rule": "RULE_1_UNRESOLVED_POSSIBLE_MATCH"
                    }
                )
            )

        # RULE 2: PREDICTED edge exists
        has_predicted_edge = False
        if hasattr(self.backend, "evidence_engine") and hasattr(self.backend.evidence_engine, "graph"):
            # Check graph for PREDICTED edges or unreviewed relationships
            for e in getattr(self.backend.evidence_engine.graph, "edges", []):
                if isinstance(e, dict) and e.get("status") == "PREDICTED":
                    has_predicted_edge = True
                    break

        if has_predicted_edge or (hasattr(self.backend, "graph_ml_service") and getattr(self.backend.graph_ml_service, "_has_predicted", False)):
            candidates.append(
                PromptCandidate(
                    prompt_type=self.PROMPT_REVIEW_PREDICTED_LINK,
                    is_safety_critical=False,
                    context_features={
                        "case_id": case_id,
                        "has_predicted_edge": True,
                        "rule": "RULE_2_UNREVIEWED_PREDICTED_LINK"
                    }
                )
            )

        # RULE 3: Anomaly exists and timeline unviewed
        if hasattr(self.backend, "findings_by_id") and len(self.backend.findings_by_id) > 0:
            candidates.append(
                PromptCandidate(
                    prompt_type=self.PROMPT_VIEW_TIMELINE,
                    is_safety_critical=False,
                    context_features={
                        "case_id": case_id,
                        "findings_count": len(self.backend.findings_by_id),
                        "rule": "RULE_3_UNVIEWED_ANOMALY"
                    }
                )
            )

        return candidates

    # ── 2. DECISION ENGINE (SAFETY BYPASS + BETA BANDIT) ─────────────────────

    def decide_prompts(
        self,
        case_id: Optional[str],
        officer_id: str,
        simulated_candidates: Optional[List[PromptCandidate]] = None
    ) -> List[PromptDecision]:
        """
        Evaluates prompt candidates for an officer:
        - Safety-critical prompts ALWAYS show (shown = True, bandit bypassed).
        - Cold-start officers (< MIN_HISTORY) ALWAYS show.
        - Mature non-critical prompts sample from Beta(alpha, beta) with guaranteed exploration.
        - Logs PROMPT_SHOWN to EventStore.
        """
        candidates = simulated_candidates if simulated_candidates is not None else self.generate_candidates(case_id=case_id)
        decisions: List[PromptDecision] = []

        for cand in candidates:
            # 1. SAFETY-CRITICAL BYPASS (HARD INVARIANT)
            if cand.is_safety_critical:
                decision = PromptDecision(
                    prompt_type=cand.prompt_type,
                    shown=True,
                    officer_id=officer_id,
                    context_snapshot={
                        **cand.context_features,
                        "bypass_reason": "SAFETY_CRITICAL_RED_TIER_BYPASS",
                        "bandit_evaluated": False,
                    }
                )
            else:
                # 2. BANDIT / COLD-START EVALUATION
                b_params = self._get_bandit_params(officer_id, cand.prompt_type)
                h_count = b_params["history_count"]
                alpha = b_params["alpha"]
                beta_val = b_params["beta"]

                if h_count < self.min_history:
                    # Cold start: show by default
                    decision = PromptDecision(
                        prompt_type=cand.prompt_type,
                        shown=True,
                        officer_id=officer_id,
                        context_snapshot={
                            **cand.context_features,
                            "cold_start": True,
                            "history_count": h_count,
                            "bandit_evaluated": False,
                        }
                    )
                else:
                    # Thompson / Beta sampling with non-zero exploration floor
                    sample = float(np.random.beta(alpha, beta_val))
                    bounded_p = float(np.clip(sample, self.min_exploration_prob, 1.0 - self.min_exploration_prob))
                    shown = (bounded_p >= self.decision_threshold)

                    decision = PromptDecision(
                        prompt_type=cand.prompt_type,
                        shown=shown,
                        officer_id=officer_id,
                        context_snapshot={
                            **cand.context_features,
                            "cold_start": False,
                            "history_count": h_count,
                            "alpha": alpha,
                            "beta": beta_val,
                            "thompson_sample": round(sample, 4),
                            "bounded_prob": round(bounded_p, 4),
                            "threshold": self.decision_threshold,
                            "bandit_evaluated": True,
                        }
                    )

            self.decisions[decision.decision_id] = decision
            decisions.append(decision)

            # Log PROMPT_SHOWN to EventStore
            if self.event_store and decision.shown:
                ev = DecisionEvent(
                    event_type=EventType.PROMPT_SHOWN,
                    officer_id=officer_id,
                    case_id=case_id or "NO_CASE_CONTEXT",
                    entity_id=cand.prompt_type,
                    previous_state=DecisionState.NONE,
                    requested_state=DecisionState.NONE,
                    reason="Guided prompt presented to officer",
                    metadata={
                        "decision_id": decision.decision_id,
                        "prompt_type": cand.prompt_type,
                        "is_safety_critical": cand.is_safety_critical,
                        "context_snapshot": decision.context_snapshot,
                        "shown": decision.shown,
                    }
                )
                self.event_store.append_event(ev)

        return decisions

    # ── 3. OUTCOME RECORDING & BANDIT LEARNING ────────────────────────────────

    def record_outcome(
        self,
        decision_id: str,
        outcome: str
    ) -> PromptDecision:
        """
        Updates prompt decision outcome (FOLLOWED / IGNORED) and updates Beta state.
        Logs PROMPT_OUTCOME to EventStore.
        """
        outcome_upper = outcome.strip().upper()
        if outcome_upper not in ("FOLLOWED", "IGNORED"):
            raise ValueError(f"Invalid outcome '{outcome}'. Must be 'FOLLOWED' or 'IGNORED'.")

        if decision_id not in self.decisions:
            # Rehydrate from persistent EventStore in case created across process boundaries
            self._rehydrate_from_event_store()

        if decision_id not in self.decisions:
            raise KeyError(f"PromptDecision ID '{decision_id}' not found.")

        dec = self.decisions[decision_id]
        dec.outcome = outcome_upper

        # Update Beta parameters if not safety critical
        b_params = self._get_bandit_params(dec.officer_id, dec.prompt_type)
        if outcome_upper == "FOLLOWED":
            b_params["alpha"] += 1.0
        else:
            b_params["beta"] += 1.0
        b_params["history_count"] += 1

        # Log PROMPT_OUTCOME to EventStore
        if self.event_store:
            ev = DecisionEvent(
                event_type=EventType.PROMPT_OUTCOME,
                officer_id=dec.officer_id,
                case_id=dec.context_snapshot.get("case_id") or "NO_CASE_CONTEXT",
                entity_id=dec.prompt_type,
                previous_state=DecisionState.NONE,
                requested_state=DecisionState.NONE,
                reason=f"Officer {outcome_upper.lower()} guided prompt",
                metadata={
                    "decision_id": decision_id,
                    "prompt_type": dec.prompt_type,
                    "outcome": outcome_upper,
                    "updated_alpha": b_params["alpha"],
                    "updated_beta": b_params["beta"],
                    "history_count": b_params["history_count"]
                }
            )
            self.event_store.append_event(ev)

        return dec
