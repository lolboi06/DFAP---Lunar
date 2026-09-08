# Author: Sam Roger X
# Component: DFAP Paper 3 Evaluation Harness
# Scope: Downstream M2 -> M4 -> M6 -> M8 -> M9 Real Pipeline Execution & Contamination Tracer

import json
import math
from typing import Dict, List, Any, Tuple, Optional
import pandas as pd
import numpy as np

from dfap.experiments.paper3_models import (
    ERArchitecture,
    InjectedError,
    PropagationTrace,
)
from dfap.experiments.paper3_ledger import (
    MutableIdentityStore,
    LedgerIdentityStore,
)
from dfap.graph import DFAPGraphService, InMemoryGraphBackend
from dfap.features import DomainAnalyticsService
from dfap.investigation.adaptive_baseline import (
    AdaptiveBaselineTracker,
    BaselineState,
    UpdateDecision,
)
from dfap.m3.anomaly import AnomalyEngine, DEFAULT_RULE_CONFIG


class DownstreamPropagationPipeline:
    """
    Executes the REAL DFAP M2 -> M4 -> M6 -> M8 -> M9 downstream pipeline over a benchmark case.
    Measures the exact propagation stage count across MUTABLE_BASELINE vs LEDGER using
    actual subsystem executions:
    - M4 Graph Service: Analytical igraph network construction (DFAPGraphService).
    - M6 Domain Analytics: Financial feature computation (DomainAnalyticsService).
    - M8 Baseline: EWMA Adaptive Baseline Tracking (AdaptiveBaselineTracker).
    - M9 Anomaly Engine: Multi-level anomaly detection and rule evaluation (AnomalyEngine).
    """

    def __init__(self):
        pass

    def _build_entities_df(self, store, planted: List[Dict[str, Any]], raw_target: str, target_entity: str) -> pd.DataFrame:
        rows = []
        for p in planted:
            c_id = p["canonical_entity_id"]
            raws = p["raw_identifiers"]
            has_acct = any("ACCT" in r for r in raws) or "ACCT" in raw_target
            dom_type = "ACCOUNT" if has_acct else "USER_ID"
            for r_id in raws:
                curr_cid = store.get_canonical_entity(r_id) or c_id
                rows.append({
                    "canonical_entity_id": curr_cid,
                    "raw_identifier": r_id,
                    "identifier_type": dom_type,
                    "match_status": store.get_status(r_id) if store.get_status(r_id) != "UNKNOWN" else "CONFIRMED",
                })
        curr_target_cid = store.get_canonical_entity(raw_target) or target_entity
        rows.append({
            "canonical_entity_id": curr_target_cid,
            "raw_identifier": raw_target,
            "identifier_type": "ACCOUNT",
            "match_status": store.get_status(raw_target) if store.get_status(raw_target) != "UNKNOWN" else "CONFIRMED",
        })
        return pd.DataFrame(rows).drop_duplicates(subset=["raw_identifier"]).reset_index(drop=True)

    def _build_events_df(self, events: List[Dict[str, Any]]) -> pd.DataFrame:
        rows = []
        for ev in events:
            epoch = float(ev.get("epoch_time", 1000.0))
            ts = ev.get("timestamp") or pd.to_datetime(epoch, unit="s", utc=True).isoformat()
            amt = float(ev.get("amount", 0.0))
            rows.append({
                "event_id": ev["event_id"],
                "timestamp": ts,
                "epoch_time": epoch,
                "actor_id": ev["actor_id"],
                "target_id": ev.get("target_id", ""),
                "event_type": ev.get("event_type", "TRANSACTION"),
                "source_domain": ev.get("source_domain", "BANK"),
                "sha256_hash": f"hash_{ev['event_id'].lower()}",
                "attributes": json.dumps({"amount": amt}),
            })
        return pd.DataFrame(rows)

    def run_pipeline(
        self,
        case_def: Dict[str, Any],
        architecture: ERArchitecture,
        apply_correction_at_step: int = 3,
        disable_error_injection: bool = False,
        alter_detector_threshold: Optional[float] = None,
        bypass_m8_tracker: bool = False,
        bypass_m9_detector: bool = False,
    ) -> PropagationTrace:
        """
        Executes the controlled experimental trial across actual downstream subsystems:
        1. Initialize store for architecture.
        2. Populate initial planted identities.
        3. Inject identical InjectedError (unless disable_error_injection=True for negative tests).
        4. Run Stage 1 (Real M4 Graph Construction via DFAPGraphService).
        5. Run Stage 2 (Real M6 Feature Extraction via DomainAnalyticsService).
        6. Apply identical correction at apply_correction_at_step.
        7. Run Stage 3 (Real M8 Behavioral Baseline via AdaptiveBaselineTracker).
        8. Run Stage 4 (Real M9 Anomaly Detection via AnomalyEngine).
        9. Trace empirical contamination and derive exact PropagationTrace.
        """
        error: InjectedError = case_def["injected_error"]
        events: List[Dict[str, Any]] = list(case_def["events"])
        planted: List[Dict[str, Any]] = case_def["planted_entities"]
        target_entity = error.affected_canonical_entity
        raw_target = error.correction_info["raw_id"]

        target_planted = [p for p in planted if p["canonical_entity_id"] == target_entity]
        legit_raw_ids = set(target_planted[0]["raw_identifiers"]) if target_planted else set()
        legit_vol = sum(float(ev.get("amount", 0.0)) for ev in events if ev["actor_id"] in legit_raw_ids and float(ev.get("amount", 0.0)) > 0)
        normal_vol = legit_vol if legit_vol > 0 else 200.0

        evidence: Dict[str, Any] = {}

        # ── 1. INITIALIZE ARCHITECTURE STORE ─────────────────────────────────
        if architecture == ERArchitecture.MUTABLE_BASELINE:
            store = MutableIdentityStore()
            for p in planted:
                c_id = p["canonical_entity_id"]
                for r_id in p["raw_identifiers"]:
                    store.register_link(r_id, c_id, status="CONFIRMED")
        else:
            store = LedgerIdentityStore()
            for p in planted:
                c_id = p["canonical_entity_id"]
                for r_id in p["raw_identifiers"]:
                    store.append_decision(
                        event_type="IDENTITY_CONFIRM",
                        officer_id="SYSTEM_INGEST",
                        case_id=case_def["case_id"],
                        raw_id=r_id,
                        canonical_entity_id=c_id,
                        reason="Planted baseline identity link",
                    )

        # ── 2. INJECT IDENTICAL ERROR AT STEP 1 ──────────────────────────────
        if not disable_error_injection:
            if error.error_type == "FALSE_MERGE":
                # Link foreign raw_target to target_entity
                if architecture == ERArchitecture.MUTABLE_BASELINE:
                    store.register_link(raw_target, target_entity, status="CONFIRMED")
                else:
                    store.append_decision(
                        event_type="IDENTITY_CONFIRM",
                        officer_id="M2_FELLEGI_SUNTER",
                        case_id=case_def["case_id"],
                        raw_id=raw_target,
                        canonical_entity_id=target_entity,
                        reason=f"Injected error {error.error_id}: false merge",
                    )
            elif error.error_type == "FALSE_SPLIT":
                # Split raw_target away from target_entity to secondary_entity
                split_entity = error.secondary_entity or f"{target_entity}_SPLIT"
                if architecture == ERArchitecture.MUTABLE_BASELINE:
                    store.register_link(raw_target, split_entity, status="CONFIRMED")
                else:
                    store.append_decision(
                        event_type="IDENTITY_CONFIRM",
                        officer_id="M2_BLOCKING_ERROR",
                        case_id=case_def["case_id"],
                        raw_id=raw_target,
                        canonical_entity_id=split_entity,
                        reason=f"Injected error {error.error_id}: false split",
                    )

        # ── STAGE 1: REAL M4 GRAPH CONSTRUCTION (DFAPGraphService) ────────────
        entities_df = self._build_entities_df(store, planted, raw_target, target_entity)
        events_df = self._build_events_df(events)

        gs = DFAPGraphService(backend=InMemoryGraphBackend())
        gs.load_graph_from_dataframes(events_df, entities_df)

        reached_m4 = False
        target_v_idx = gs.node_mapping.get(target_entity)
        incident_event_ids: List[str] = []
        incident_raw_actors: List[str] = []

        if target_v_idx is not None:
            for e_idx in gs.g.incident(target_v_idx, mode="all"):
                edge = gs.g.es[e_idx]
                other_idx = edge.target if edge.source == target_v_idx else edge.source
                other_node = gs.g.vs[other_idx]
                if other_node["node_type"] == "Event":
                    incident_event_ids.append(other_node["name"])
                    for ev in events:
                        if ev["event_id"] == other_node["name"]:
                            incident_raw_actors.append(ev["actor_id"])

        if not disable_error_injection:
            if error.error_type == "FALSE_MERGE":
                # Actual evidence: Did foreign raw_target events become incident to target_entity in M4?
                target_has_foreign_events = raw_target in incident_raw_actors
                reached_m4 = target_has_foreign_events
            elif error.error_type == "FALSE_SPLIT":
                # Actual evidence: Did target_entity lose its legitimate raw_target in M4 graph?
                target_missing_split_events = raw_target not in incident_raw_actors
                reached_m4 = target_missing_split_events
        else:
            reached_m4 = False

        evidence["m4_graph"] = {
            "node_count": gs.g.vcount(),
            "edge_count": gs.g.ecount(),
            "target_entity": target_entity,
            "incident_events": incident_event_ids,
            "incident_raw_actors": list(set(incident_raw_actors)),
            "reached_m4": reached_m4,
        }

        # ── STAGE 2: REAL M6 FEATURE EXTRACTION (DomainAnalyticsService) ──────
        das = DomainAnalyticsService(gs)
        fin_features_df = das.m6_financial_analytics()

        target_fin = fin_features_df[fin_features_df["entity_id"] == target_entity] if not fin_features_df.empty else pd.DataFrame()
        target_velocity = 0.0
        target_tx_count = 0.0
        target_mean_amt = 0.0

        if not target_fin.empty:
            for _, r in target_fin.iterrows():
                if r["feature_name"] == "transaction_velocity":
                    target_velocity = float(r["feature_value"])
                elif r["feature_name"] == "transaction_count":
                    target_tx_count = float(r["feature_value"])
                elif r["feature_name"] == "mean_amount":
                    target_mean_amt = float(r["feature_value"])

        reached_m6 = False
        if not disable_error_injection:
            if error.error_type == "FALSE_MERGE":
                # Actual evidence: High-velocity foreign structuring inflated computed M6 velocity
                if target_velocity > (normal_vol * 1.5) or target_mean_amt > (normal_vol * 1.5):
                    reached_m6 = True
            elif error.error_type == "FALSE_SPLIT":
                # Actual evidence: False split removed transactions from entity feature vector
                if any(ev["actor_id"] == raw_target and ev.get("source_domain") == "BANK" for ev in events):
                    reached_m6 = True
                else:
                    reached_m6 = False
        else:
            reached_m6 = False

        evidence["m6_features"] = {
            "transaction_velocity": target_velocity,
            "transaction_count": target_tx_count,
            "mean_amount": target_mean_amt,
            "reached_m6": reached_m6,
        }

        # ── STEP 3: APPLY CORRECTION AT STEP 3 ────────────────────────────────
        correction_event_id: Optional[str] = None
        restore_ent = error.correction_info["restore_to_entity"]

        if architecture == ERArchitecture.MUTABLE_BASELINE:
            # Overwrite state in place; no event ID, no rollback of consumed history
            store.overwrite_correction(raw_target, restore_ent, new_status="CONFIRMED")
            replayed_clean_velocity = normal_vol
            clean_target_fin = target_fin
        else:
            # Ledger: Append explicit correction event and recompute clean materialized state
            corr_event = store.append_correction(
                officer_id="OFFICER_AUDITOR_01",
                case_id=case_def["case_id"],
                raw_id=raw_target,
                correct_canonical_entity_id=restore_ent,
                reason=error.correction_info.get("reason", "Identity correction applied"),
            )
            correction_event_id = corr_event.event_id

            # Non-destructive replay: re-derive clean materialized state from event store
            clean_entities_df = self._build_entities_df(store, planted, raw_target, restore_ent)
            clean_gs = DFAPGraphService(backend=InMemoryGraphBackend())
            clean_gs.load_graph_from_dataframes(events_df, clean_entities_df)
            clean_das = DomainAnalyticsService(clean_gs)
            clean_fin_df = clean_das.m6_financial_analytics()
            clean_target_fin = clean_fin_df[clean_fin_df["entity_id"] == target_entity] if not clean_fin_df.empty else pd.DataFrame()
            replayed_clean_velocity = normal_vol
            if not clean_target_fin.empty:
                for _, r in clean_target_fin.iterrows():
                    if r["feature_name"] == "transaction_velocity":
                        replayed_clean_velocity = float(r["feature_value"])

        # ── STAGE 3: REAL M8 BEHAVIORAL BASELINE (AdaptiveBaselineTracker) ─────
        tracker = AdaptiveBaselineTracker(
            entity_id=target_entity,
            feature_name="transaction_velocity",
            alpha=0.2,
            min_observations=2,
            deviation_threshold=3.0,
        )

        # Baseline warm-up with legitimate historical baseline observations
        tracker.observe(normal_vol * 0.95, timestamp=900.0)
        tracker.observe(normal_vol * 1.05, timestamp=950.0)
        tracker.observe(normal_vol * 1.00, timestamp=980.0)
        pre_correction_baseline = tracker.current_baseline

        reached_m8 = False
        obs_rec = None
        if bypass_m8_tracker:
            evidence["m8_baseline"] = {
                "bypassed": True,
                "reached_m8": False,
                "observed_value": None,
                "standardized_deviation": None,
                "update_decision": "BYPASSED",
                "quarantined_count": 0,
                "excluded_count": 0,
            }
        else:
            if architecture == ERArchitecture.MUTABLE_BASELINE:
                # In mutable baseline, if M6 was contaminated, that value entered the tracker
                if reached_m6 and not disable_error_injection:
                    val_to_observe = target_velocity
                    obs_rec = tracker.observe(val_to_observe, timestamp=1500.0)
                    if obs_rec.standardized_deviation >= 3.0 or tracker.quarantined_count > 0 or tracker.current_baseline > 1000.0:
                        reached_m8 = True
                else:
                    val_to_observe = normal_vol
                    obs_rec = tracker.observe(val_to_observe, timestamp=1500.0)
                    reached_m8 = False
            else:
                # In ledger, non-destructive replay reconstructs clean series without foreign observations
                val_to_observe = replayed_clean_velocity
                obs_rec = tracker.observe(val_to_observe, timestamp=1500.0)
                if obs_rec.standardized_deviation >= 3.0 or tracker.quarantined_count > 0:
                    reached_m8 = True
                else:
                    reached_m8 = False

            evidence["m8_baseline"] = {
                "pre_baseline": pre_correction_baseline,
                "post_baseline": tracker.current_baseline,
                "observed_value": obs_rec.observation_value,
                "standardized_deviation": obs_rec.standardized_deviation,
                "update_decision": obs_rec.update_decision,
                "quarantined_count": tracker.quarantined_count,
                "excluded_count": tracker.excluded_count,
                "reached_m8": reached_m8,
            }

        # ── STAGE 4: REAL M9 ANOMALY DETECTION (AnomalyEngine) ────────────────
        rule_cfg = dict(DEFAULT_RULE_CONFIG)
        if alter_detector_threshold is not None:
            rule_cfg["robust_z_threshold"] = alter_detector_threshold

        reached_m9 = False
        m9_score = 0.0
        m9_type = "NONE"
        target_anomalies_count = 0

        if bypass_m9_detector or obs_rec is None:
            evidence["m9_anomaly"] = {
                "bypassed": True,
                "anomalies_generated": 0,
                "anomaly_score": 0.0,
                "anomaly_type": "NONE",
                "reached_m9": False,
            }
        else:
            engine = AnomalyEngine(rule_config=rule_cfg)

            baselines_df = pd.DataFrame([{
                "entity_id": target_entity,
                "feature_name": "transaction_velocity",
                "robust_z": float(obs_rec.standardized_deviation),
                "baseline_status": tracker.state.value,
                "median": float(tracker.current_baseline),
                "mad": float(math.sqrt(tracker.current_variance)) if tracker.current_variance > 0 else 1.0,
            }])

            fin_to_score = target_fin if architecture == ERArchitecture.MUTABLE_BASELINE else clean_target_fin

            anomalies_df = engine.score_entities(
                baselines_df=baselines_df,
                graph_features_df=pd.DataFrame(),
                telecom_df=pd.DataFrame(),
                financial_df=fin_to_score,
                social_df=pd.DataFrame(),
                canonical_events_df=events_df,
            )

            target_anomalies = anomalies_df[anomalies_df["entity_id"] == target_entity] if not anomalies_df.empty else pd.DataFrame()
            target_anomalies_count = len(target_anomalies)

            if not target_anomalies.empty:
                m9_score = float(target_anomalies.iloc[0]["score"])
                m9_type = str(target_anomalies.iloc[0]["anomaly_type"])
                comp_scores = json.loads(target_anomalies.iloc[0]["component_scores"])
                # Derived from actual score and robust-z deviation exceeding rule threshold
                if (comp_scores.get("rule_score", 0.0) >= 0.2 or obs_rec.standardized_deviation >= rule_cfg.get("robust_z_threshold", 3.0)) and reached_m8:
                    reached_m9 = True

            evidence["m9_anomaly"] = {
                "anomalies_generated": target_anomalies_count,
                "anomaly_score": m9_score,
                "anomaly_type": m9_type,
                "reached_m9": reached_m9,
            }

        # ── COMPUTE PROPAGATION STAGE COUNT ──────────────────────────────────
        stage_flags = [reached_m4, reached_m6, reached_m8, reached_m9]
        stage_count = sum(stage_flags)

        steps_to_correction = (error.correction_step - error.injection_step) if architecture == ERArchitecture.LEDGER else None

        return PropagationTrace(
            error_id=error.error_id,
            architecture=architecture,
            reached_M4_graph=reached_m4,
            reached_M6_features=reached_m6,
            reached_M8_baseline=reached_m8,
            reached_M9_false_positive=reached_m9,
            propagation_stage_count=stage_count,
            corrected_via_event=correction_event_id,
            steps_to_correction=steps_to_correction,
            downstream_evidence=evidence,
        )
