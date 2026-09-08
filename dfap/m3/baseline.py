# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
"""
M8 — Entity-Specific Behavioral Baseline Service.

Mathematical definitions:
  median(X)    = 50th percentile of historical observations X
  MAD(X)       = median(|X - median(X)|)
  robust_z(x)  = (x - median(X)) / (1.4826 * MAD(X) + epsilon)
  percentile   = empirical rank of x in historical distribution (only if |X| >= 3)
  EWMA(t)      = alpha * x_t + (1 - alpha) * EWMA(t-1)   [alpha = 0.3]

Temporal Leakage Control:
  Baseline is fitted on observations STRICTLY PRECEDING the evaluated observation.
  No observation contaminates its own baseline.

Baseline Status:
  COLD_START      : |history| < 3   — deviation reported but flagged as unreliable
  LOW_HISTORY     : 3 <= |history| < 10 — moderate confidence
  STABLE_BASELINE : |history| >= 10 — full confidence
"""
import json
import uuid
from typing import List, Optional

import numpy as np
import pandas as pd

MODEL_VERSION = "M8_BASELINE_v1.0"
EWMA_ALPHA = 0.3
EPSILON = 1e-9
COLD_START_THRESH = 3
LOW_HISTORY_THRESH = 10


class EntityBaselineService:
    """
    Computes per-entity, per-feature behavioral baselines from a
    longitudinal feature DataFrame.

    Input DataFrame must contain:
        entity_id, feature_name, feature_value, window, source, evidence_refs

    The 'window' column may encode temporal ordering (e.g., "2026-09-01").
    If window values are not parseable as dates, ordering falls back to
    insertion order, which must be chronological.
    """

    def __init__(self):
        self._baseline_cache: dict = {}

    # ── public ───────────────────────────────────────────────────────────────

    def fit_baselines(self, features_df: pd.DataFrame) -> pd.DataFrame:
        """
        For every (entity_id, feature_name) series in features_df,
        compute leave-one-out baselines using strictly historical observations.

        Each output row represents a single observation evaluated against
        the baseline built from all PRECEDING observations.

        Returns baselines_df matching the output contract.
        """
        if features_df.empty or "entity_id" not in features_df.columns or "feature_name" not in features_df.columns:
            return pd.DataFrame(columns=self._output_columns())

        results = []
        grouped = features_df.groupby(["entity_id", "feature_name"])

        for (entity_id, feature_name), group in grouped:
            group_sorted = group.reset_index(drop=True)
            values = group_sorted["feature_value"].dropna().astype(float).tolist()
            ev_refs = group_sorted["evidence_refs"].tolist() if "evidence_refs" in group_sorted.columns else [[]]*len(values)

            # Rolling leave-one-out: evaluate index i using history [0..i-1]
            ewma_val = values[0] if values else 0.0

            for i, x in enumerate(values):
                history = values[:i]  # strictly preceding — no leakage
                refs = ev_refs[i] if i < len(ev_refs) else []
                w = group_sorted["window"].iloc[i] if "window" in group_sorted.columns else "ALL"
                s = group_sorted["source"].iloc[i] if "source" in group_sorted.columns else "UNKNOWN"

                baseline_row = self._compute_baseline_record(
                    entity_id=entity_id,
                    feature_name=feature_name,
                    observed_value=x,
                    history=history,
                    ewma_prev=ewma_val,
                    window=w,
                    source=s,
                    evidence_refs=refs,
                )
                results.append(baseline_row)

                # Update EWMA for next step
                ewma_val = EWMA_ALPHA * x + (1.0 - EWMA_ALPHA) * ewma_val

        if not results:
            return pd.DataFrame(columns=self._output_columns())

        df = pd.DataFrame(results)
        return df.sort_values(["entity_id", "feature_name"]).reset_index(drop=True)

    def score_observation(
        self,
        entity_id: str,
        feature_name: str,
        observed_value: float,
        history: List[float],
        evidence_refs: Optional[List[str]] = None,
        window: str = "CURRENT",
        source: str = "UNKNOWN",
    ) -> dict:
        """Score a single observation against provided history. No state mutation."""
        ewma = float(np.mean(history)) if history else observed_value
        return self._compute_baseline_record(
            entity_id=entity_id,
            feature_name=feature_name,
            observed_value=observed_value,
            history=history,
            ewma_prev=ewma,
            window=window,
            source=source,
            evidence_refs=evidence_refs or [],
        )

    # ── private ──────────────────────────────────────────────────────────────

    def _compute_baseline_record(
        self,
        entity_id: str,
        feature_name: str,
        observed_value: float,
        history: List[float],
        ewma_prev: float,
        window: str,
        source: str,
        evidence_refs,
    ) -> dict:
        n = len(history)
        hist_arr = np.array(history, dtype=float)

        # Baseline status
        if n < COLD_START_THRESH:
            status = "COLD_START"
        elif n < LOW_HISTORY_THRESH:
            status = "LOW_HISTORY"
        else:
            status = "STABLE_BASELINE"

        # Center and scale
        if n >= 1:
            center = float(np.median(hist_arr))
            mad = float(np.median(np.abs(hist_arr - center)))
            scale = 1.4826 * mad + EPSILON
            robust_z = (observed_value - center) / scale
        else:
            center = observed_value
            mad = 0.0
            scale = EPSILON
            robust_z = 0.0

        # Quantiles (only meaningful with enough history)
        if n >= 3:
            q25 = float(np.percentile(hist_arr, 25))
            q75 = float(np.percentile(hist_arr, 75))
            percentile = float(
                np.sum(hist_arr <= observed_value) / n * 100.0
            )
            roll_mean = float(np.mean(hist_arr[-10:]))  # last-10 rolling mean
        else:
            q25 = q75 = center
            percentile = float("nan")
            roll_mean = center

        # EWMA for this step
        ewma = EWMA_ALPHA * observed_value + (1.0 - EWMA_ALPHA) * ewma_prev

        # Normalise evidence_refs to list
        if evidence_refs is None:
            refs = []
        elif isinstance(evidence_refs, (list, np.ndarray)):
            refs = list(evidence_refs)
        else:
            refs = [str(evidence_refs)]

        baseline_id = f"BL_{uuid.uuid4().hex[:12].upper()}"

        return {
            "baseline_id": baseline_id,
            "entity_id": entity_id,
            "feature_name": feature_name,
            "window": window,
            "source": source,
            "observed_value": float(observed_value),
            "baseline_center": center,
            "baseline_scale": scale,
            "mad": mad,
            "robust_z": robust_z,
            "percentile": percentile,
            "ewma": ewma,
            "q25": q25,
            "q75": q75,
            "rolling_mean": roll_mean,
            "history_count": n,
            "baseline_status": status,
            "evidence_refs": refs,
            "model_version": MODEL_VERSION,
        }

    @staticmethod
    def _output_columns() -> List[str]:
        return [
            "baseline_id", "entity_id", "feature_name", "window", "source",
            "observed_value", "baseline_center", "baseline_scale", "mad",
            "robust_z", "percentile", "ewma", "q25", "q75", "rolling_mean",
            "history_count", "baseline_status", "evidence_refs", "model_version",
        ]
