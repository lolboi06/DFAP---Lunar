# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M13 Unified Timeline Backend with strict half-open window semantics

import json
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
from dateutil.parser import isoparse
from datetime import timezone

from dfap.wp4.contracts import (
    ErrorCode,
    WorkspaceError,
    CanonicalEvidenceEvent,
)


class TimelineService:
    """
    M13 Unified Timeline Service.
    Queries and extracts canonical events for an entity within a strict [start, end) temporal window.
    Guarantees:
    - Half-open window semantics: timestamp >= start and timestamp < end.
    - Pure canonical event preservation (zero synthetic timestamp mutation).
    - Deterministic ordering by (timestamp_utc, event_id).
    - Timezone-normalized comparison.
    """

    def __init__(self, df_events: pd.DataFrame, df_entities: pd.DataFrame):
        self.df_events = df_events.copy()
        self.df_entities = df_entities.copy()
        self._build_actor_to_canonical_map()

    def _build_actor_to_canonical_map(self):
        """Maps raw identifiers and canonical entity IDs to entity membership."""
        self.actor_to_canonical: Dict[str, str] = {}
        if not self.df_entities.empty and "raw_identifier" in self.df_entities.columns:
            for _, row in self.df_entities.iterrows():
                raw = str(row["raw_identifier"]).strip()
                can = str(row["canonical_entity_id"]).strip()
                self.actor_to_canonical[raw] = can
                self.actor_to_canonical[can] = can

    def _parse_utc_iso(self, ts_str: Optional[str]) -> Optional[float]:
        if ts_str is None:
            return None
        s = str(ts_str).strip()
        if not s:
            return None
        try:
            dt = isoparse(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception as e:
            raise WorkspaceError(f"Invalid timestamp format: '{ts_str}' ({str(e)})", ErrorCode.INVALID_TIME_RANGE)

    def get_entity_timeline(
        self,
        entity_id: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Extracts all canonical events where entity_id participates as actor or target
        within the half-open temporal window [start, end).
        """
        ent_str = str(entity_id).strip()
        start_epoch = self._parse_utc_iso(start)
        end_epoch = self._parse_utc_iso(end)

        if start_epoch is not None and end_epoch is not None:
            if start_epoch > end_epoch:
                raise WorkspaceError(
                    f"Invalid temporal window: start ({start}) cannot be strictly after end ({end})",
                    ErrorCode.INVALID_TIME_RANGE
                )

        matching_rows = []

        for _, row in self.df_events.iterrows():
            actor = str(row.get("actor_id", "")).strip()
            target = str(row.get("target_id", "")).strip() if pd.notna(row.get("target_id")) else ""

            # Check if actor or target matches entity_id directly or via resolved canonical ID
            actor_can = self.actor_to_canonical.get(actor, actor)
            target_can = self.actor_to_canonical.get(target, target)

            if ent_str in (actor, target, actor_can, target_can):
                ts_str = str(row.get("timestamp", ""))
                ev_epoch = self._parse_utc_iso(ts_str)
                if ev_epoch is None:
                    raise WorkspaceError(
                        f"Malformed or missing canonical event timestamp '{ts_str}' in event '{row.get('event_id')}'",
                        ErrorCode.INVALID_TIME_RANGE
                    )

                # Strict [start, end) half-open window check
                if start_epoch is not None and ev_epoch < start_epoch:
                    continue
                if end_epoch is not None and ev_epoch >= end_epoch:
                    continue

                attr_val = row.get("attributes", {})
                if isinstance(attr_val, str):
                    try:
                        attr_dict = json.loads(attr_val)
                    except Exception:
                        attr_dict = {"raw": attr_val}
                elif isinstance(attr_val, dict):
                    attr_dict = attr_val
                else:
                    attr_dict = {}

                matching_rows.append({
                    "event_id": str(row.get("event_id", "")),
                    "timestamp": ts_str,
                    "event_type": str(row.get("event_type", "")),
                    "source_domain": str(row.get("source_domain", "")),
                    "actor_id": actor,
                    "target_id": target if target else None,
                    "sha256_hash": str(row.get("sha256_hash", "")),
                    "attributes": attr_dict,
                })

        # Deterministic sorting: primary = timestamp, secondary = event_id
        matching_rows.sort(key=lambda x: (x["timestamp"], x["event_id"]))
        return matching_rows
