# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Real Public Data Historical Replay Engine

import datetime
import json
import logging
import os
import time
from typing import Dict, Any, List, Optional
import pandas as pd

from dfap.wp4.stream import RealtimeM1M2M3Pipeline

logger = logging.getLogger(__name__)


class ReplayState:
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class HistoricalReplayEngine:
    """
    Historical Replay Engine for Authentic Public Research Datasets.
    Replays real historical events strictly in chronological sequence
    preserving original timestamps.
    Supports compressed replay speeds: 1x, 10x, 100x, 1000x.
    Transparently labeled as: REAL PUBLIC DATA REPLAY.
    """

    SUPPORTED_SPEEDS = {1, 10, 100, 1000}

    def __init__(
        self,
        canonical_dir: str = "data/canonical",
        pipeline: Optional[RealtimeM1M2M3Pipeline] = None
    ):
        self.canonical_dir = canonical_dir
        self.pipeline = pipeline
        self.active_dataset: Optional[str] = None
        self.events_df: pd.DataFrame = pd.DataFrame()
        self.cursor: int = 0
        self.state: str = ReplayState.IDLE
        self.speed: int = 100
        self.replayed_events: List[Dict[str, Any]] = []

    def load_dataset(self, dataset_name: str) -> Dict[str, Any]:
        """Loads canonical dataset records for historical replay."""
        key = dataset_name.lower().strip()
        can_path = os.path.join(self.canonical_dir, f"{key}_canonical.parquet")
        if not os.path.exists(can_path):
            raise FileNotFoundError(f"Canonical dataset '{key}' not found at {can_path}. Please run 'dfap ingest {key}' first.")

        self.events_df = pd.read_parquet(can_path).sort_values("epoch_time").reset_index(drop=True)
        self.active_dataset = key
        self.cursor = 0
        self.state = ReplayState.IDLE
        self.replayed_events = []

        return {
            "mode": "REAL PUBLIC DATA REPLAY",
            "dataset": key,
            "total_events": len(self.events_df),
            "start_time": str(self.events_df["timestamp"].min()),
            "end_time": str(self.events_df["timestamp"].max()),
            "actors_count": len(self.events_df["actor_id"].unique()),
            "state": self.state
        }

    def start(self, speed: int = 100) -> Dict[str, Any]:
        """Starts real public data replay at specified compression speed."""
        if self.events_df.empty:
            raise ValueError("No dataset loaded. Run 'source <dataset>' first.")
        if speed not in self.SUPPORTED_SPEEDS:
            raise ValueError(f"Unsupported speed {speed}x. Choose from {self.SUPPORTED_SPEEDS}")

        self.speed = speed
        self.state = ReplayState.RUNNING
        return {
            "status": "REPLAY_STARTED",
            "mode": "REAL PUBLIC DATA REPLAY",
            "dataset": self.active_dataset,
            "speed": f"{self.speed}x",
            "cursor": self.cursor,
            "total_events": len(self.events_df)
        }

    def pause(self) -> Dict[str, Any]:
        """Pauses historical replay."""
        if self.state != ReplayState.RUNNING:
            return {"status": "NOT_RUNNING", "current_state": self.state}
        self.state = ReplayState.PAUSED
        return {"status": "REPLAY_PAUSED", "cursor": self.cursor}

    def resume(self) -> Dict[str, Any]:
        """Resumes paused historical replay."""
        if self.state != ReplayState.PAUSED:
            return {"status": "NOT_PAUSED", "current_state": self.state}
        self.state = ReplayState.RUNNING
        return {"status": "REPLAY_RESUMED", "cursor": self.cursor}

    def stop(self) -> Dict[str, Any]:
        """Stops and resets historical replay."""
        self.state = ReplayState.IDLE
        self.cursor = 0
        self.replayed_events = []
        return {"status": "REPLAY_STOPPED"}

    def step(self, n_events: int = 1) -> List[Dict[str, Any]]:
        """
        Advances n_events chronologically through M1->M2->M3 pipeline.
        Original timestamps remain completely preserved.
        """
        if self.events_df.empty:
            raise ValueError("No dataset loaded. Run 'source <dataset>' first.")
        if self.cursor >= len(self.events_df):
            self.state = ReplayState.COMPLETED
            return []

        processed = []
        limit = min(self.cursor + n_events, len(self.events_df))

        for idx in range(self.cursor, limit):
            row = self.events_df.iloc[idx].to_dict()
            raw_attrs = json.loads(row.get("attributes", "{}")) if isinstance(row.get("attributes"), str) else row.get("attributes", {})

            # Prepare raw event payload for pipeline ingestion
            raw_event_payload = {
                "source_domain": row["source_domain"],
                "default_event_type": row["event_type"],
                "payload": {
                    "event_id": row["event_id"],
                    "timestamp": row["timestamp"],
                    "actor_id": row["actor_id"],
                    "target_id": row["target_id"],
                    "amount": float(row.get("amount", 0.0)),
                    "duration": float(row.get("duration", 0.0)),
                    **raw_attrs
                }
            }

            if self.pipeline is not None:
                step_res = self.pipeline.process_raw_event(raw_event_payload)
            else:
                step_res = {
                    "status": "ACCEPTED",
                    "event_id": row["event_id"],
                    "timestamp": row["timestamp"],
                    "actor_id": row["actor_id"],
                    "target_id": row["target_id"],
                    "domain": row["source_domain"]
                }

            processed.append(step_res)
            self.replayed_events.append(step_res)

        self.cursor = limit
        if self.cursor >= len(self.events_df):
            self.state = ReplayState.COMPLETED

        return processed

    def status(self) -> Dict[str, Any]:
        """Returns live replay status."""
        return {
            "mode": "REAL PUBLIC DATA REPLAY",
            "active_dataset": self.active_dataset,
            "state": self.state,
            "cursor": self.cursor,
            "total_events": len(self.events_df),
            "progress_percent": round(float(self.cursor / max(1, len(self.events_df))) * 100, 2),
            "speed": f"{self.speed}x"
        }
