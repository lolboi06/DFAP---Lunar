# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: Feature 1 - Grammar-Constrained Query Parsing & Disambiguation Service (v10)

import calendar
import collections
import json
import re
import uuid
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from dfap.investigation.event_sourcing import (
    DecisionEvent,
    DecisionState,
    EventStore,
    EventType,
)
from dfap.investigation.ollama_client import OllamaClient, OllamaUnavailableError
from dfap.investigation.workspace import InvestigationWorkspaceBackend, MatchStatus


class QueryType(str, Enum):
    ENTITY_LOOKUP = "ENTITY_LOOKUP"
    TIMELINE = "TIMELINE"
    PATH_BETWEEN = "PATH_BETWEEN"
    ANOMALY_LIST = "ANOMALY_LIST"
    UNSUPPORTED = "UNSUPPORTED"


class TimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: Optional[str] = Field(None, description="ISO-8601 start date or date string")
    end_date: Optional[str] = Field(None, description="ISO-8601 end date or date string")
    start_epoch: Optional[float] = Field(None, description="Epoch start timestamp in seconds")
    end_epoch: Optional[float] = Field(None, description="Epoch end timestamp in seconds")
    raw_text: Optional[str] = Field(None, description="Original temporal phrase (e.g. 'last month')")


class QueryIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_type: QueryType = Field(..., description="Constrained query intent category")
    entity_ref: Optional[str] = Field(None, description="Primary raw entity identifier or name")
    entity_ref_2: Optional[str] = Field(None, description="Secondary entity identifier (PATH_BETWEEN only)")
    time_filter: Optional[TimeRange] = Field(None, description="Optional bounded temporal filter")
    case_context_id: Optional[str] = Field(None, description="Server-controlled case/workspace ID")


class MatchBasis(str, Enum):
    EXACT_IDENTIFIER = "EXACT_IDENTIFIER"
    NAME_ONLY = "NAME_ONLY"


class DisambiguationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(..., description="Session-scoped candidate identifier (e.g. CAND_1)")
    canonical_entity_id: str = Field(..., description="Resolved authoritative canonical entity ID")
    display_label: str = Field(..., description="Descriptive label including identity and activity info")
    graph_distance_to_context: int = Field(..., description="Hop distance to active case context in M4 graph")
    match_basis: MatchBasis = Field(..., description="Matching basis: EXACT_IDENTIFIER or NAME_ONLY")
    last_confirmed_activity: Optional[str] = Field(None, description="Last confirmed observed activity timestamp")


SUPPORTED_RELATIVE_PATTERNS = [
    r"\b(last|previous|past)\s+month\b",
    r"\b(this|current)\s+month\b",
    r"\b(last|previous|past)\s+week\b",
    r"\b(this|current)\s+week\b",
    r"\b(yesterday|previous\s+day|prior\s+day|last\s+day)\b",
    r"\btoday\b",
]

UNRESOLVED_TEMPORAL_PATTERNS = [
    r"\brecently\b",
    r"\ba\s+while\s+back\b",
    r"\b(a\s+)?few\s+(days|weeks|months|hours)\s+ago\b",
    r"\bearlier\b",
    r"\bsometime(\s+back)?\b",
    r"\b(last|previous|past)\s+year\b",
    r"\bthis\s+year\b",
    r"\blately\b",
]


def extract_temporal_phrase(text: str) -> Optional[str]:
    """
    Extracts raw temporal substring from natural language query.
    Returns matched temporal phrase or None.
    """
    if not text:
        return None
    t_low = text.lower().strip()

    # Check explicit date ranges first: YYYY-MM-DD to YYYY-MM-DD
    m_range = re.search(r"(\d{4}-\d{2}-\d{2})\s*(?:to|until|and|-)\s*(\d{4}-\d{2}-\d{2})", t_low)
    if m_range:
        return m_range.group(0).strip()

    # Check single explicit date: YYYY-MM-DD
    m_single = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", t_low)
    if m_single:
        return m_single.group(0).strip()

    # Check supported relative expressions
    for pat in SUPPORTED_RELATIVE_PATTERNS:
        m = re.search(pat, t_low)
        if m:
            return m.group(0).strip()

    # Check unresolved / unsupported relative expressions
    for pat in UNRESOLVED_TEMPORAL_PATTERNS:
        m = re.search(pat, t_low)
        if m:
            return m.group(0).strip()

    return None


def resolve_relative_time(
    phrase: str,
    reference_dt: Optional[datetime] = None
) -> Optional[Tuple[datetime, datetime]]:
    """
    Deterministically resolves relative natural-language temporal phrases into
    strict UTC datetime bounds (start_dt, end_dt).
    Uses calendar month/week/day arithmetic, never arbitrary rolling estimations.
    """
    if not phrase:
        return None

    if reference_dt is None:
        reference_dt = datetime.now(timezone.utc)
    elif reference_dt.tzinfo is None:
        reference_dt = reference_dt.replace(tzinfo=timezone.utc)
    else:
        reference_dt = reference_dt.astimezone(timezone.utc)

    text = phrase.lower().strip()
    year = reference_dt.year
    month = reference_dt.month

    # 1. LAST MONTH / PREVIOUS MONTH / PAST MONTH (Calendar Month, e.g. Aug 1 - Aug 31)
    if re.search(r"\b(last|previous|past)\s+month\b", text):
        prev_year = year - 1 if month == 1 else year
        prev_month = 12 if month == 1 else month - 1
        _, last_day = calendar.monthrange(prev_year, prev_month)
        start_dt = datetime(prev_year, prev_month, 1, 0, 0, 0, tzinfo=timezone.utc)
        end_dt = datetime(prev_year, prev_month, last_day, 23, 59, 59, tzinfo=timezone.utc)
        return start_dt, end_dt

    # 2. THIS MONTH / CURRENT MONTH (Calendar Month, e.g. Sep 1 - Sep 30)
    if re.search(r"\b(this|current)\s+month\b", text):
        _, last_day = calendar.monthrange(year, month)
        start_dt = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
        end_dt = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
        return start_dt, end_dt

    # 3. LAST WEEK / PREVIOUS WEEK / PAST WEEK (Monday to Sunday preceding current week)
    if re.search(r"\b(last|previous|past)\s+week\b", text):
        curr_monday = reference_dt.date() - timedelta(days=reference_dt.weekday())
        prev_monday = curr_monday - timedelta(days=7)
        prev_sunday = prev_monday + timedelta(days=6)
        start_dt = datetime(prev_monday.year, prev_monday.month, prev_monday.day, 0, 0, 0, tzinfo=timezone.utc)
        end_dt = datetime(prev_sunday.year, prev_sunday.month, prev_sunday.day, 23, 59, 59, tzinfo=timezone.utc)
        return start_dt, end_dt

    # 4. THIS WEEK / CURRENT WEEK (Monday to Sunday of current week)
    if re.search(r"\b(this|current)\s+week\b", text):
        curr_monday = reference_dt.date() - timedelta(days=reference_dt.weekday())
        curr_sunday = curr_monday + timedelta(days=6)
        start_dt = datetime(curr_monday.year, curr_monday.month, curr_monday.day, 0, 0, 0, tzinfo=timezone.utc)
        end_dt = datetime(curr_sunday.year, curr_sunday.month, curr_sunday.day, 23, 59, 59, tzinfo=timezone.utc)
        return start_dt, end_dt

    # 5. YESTERDAY / PREVIOUS DAY / PRIOR DAY / LAST DAY
    if re.search(r"\b(yesterday|previous\s+day|prior\s+day|last\s+day)\b", text):
        y_date = reference_dt.date() - timedelta(days=1)
        start_dt = datetime(y_date.year, y_date.month, y_date.day, 0, 0, 0, tzinfo=timezone.utc)
        end_dt = datetime(y_date.year, y_date.month, y_date.day, 23, 59, 59, tzinfo=timezone.utc)
        return start_dt, end_dt

    # 6. TODAY
    if re.search(r"\btoday\b", text):
        t_date = reference_dt.date()
        start_dt = datetime(t_date.year, t_date.month, t_date.day, 0, 0, 0, tzinfo=timezone.utc)
        end_dt = datetime(t_date.year, t_date.month, t_date.day, 23, 59, 59, tzinfo=timezone.utc)
        return start_dt, end_dt

    # 7. EXPLICIT DATE RANGE: "YYYY-MM-DD to YYYY-MM-DD"
    m_range = re.search(r"(\d{4}-\d{2}-\d{2})\s*(?:to|until|and|-)\s*(\d{4}-\d{2}-\d{2})", text)
    if m_range:
        try:
            d1 = datetime.strptime(m_range.group(1), "%Y-%m-%d")
            d2 = datetime.strptime(m_range.group(2), "%Y-%m-%d")
            start_dt = datetime(d1.year, d1.month, d1.day, 0, 0, 0, tzinfo=timezone.utc)
            end_dt = datetime(d2.year, d2.month, d2.day, 23, 59, 59, tzinfo=timezone.utc)
            return start_dt, end_dt
        except Exception:
            pass

    # 8. SINGLE EXPLICIT DATE: "YYYY-MM-DD"
    m_single = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if m_single:
        try:
            d = datetime.strptime(m_single.group(1), "%Y-%m-%d")
            start_dt = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)
            end_dt = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)
            return start_dt, end_dt
        except Exception:
            pass

    return None


def build_resolved_time_range(phrase: str, reference_dt: datetime) -> TimeRange:
    """Creates a strictly validated TimeRange from a relative or explicit temporal phrase."""
    bounds = resolve_relative_time(phrase, reference_dt)
    if bounds is not None:
        start_dt, end_dt = bounds
        return TimeRange(
            start_date=start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end_date=end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            start_epoch=start_dt.timestamp(),
            end_epoch=end_dt.timestamp(),
            raw_text=phrase.strip()
        )
    return TimeRange(
        start_date=None,
        end_date=None,
        start_epoch=None,
        end_epoch=None,
        raw_text=phrase.strip()
    )


class DisambiguationSession:
    """Tracks session-level query state and pending disambiguation gates."""

    def __init__(
        self,
        session_id: Optional[str] = None,
        case_context_id: Optional[str] = None,
        officer_id: str = "OFFICER_DEFAULT",
        reference_time: Optional[datetime] = None
    ):
        self.session_id: str = session_id or str(uuid.uuid4())
        self.case_context_id: Optional[str] = case_context_id
        self.officer_id: str = officer_id
        self.reference_time: Optional[datetime] = reference_time
        self.last_resolved_entity_id: Optional[str] = None
        self.last_resolved_entity_2_id: Optional[str] = None
        self.last_query_intent: Optional[QueryIntent] = None
        self.pending_candidates: Dict[str, DisambiguationCandidate] = {}
        self.pending_intent: Optional[QueryIntent] = None
        self.pending_original_input: Optional[str] = None


class QueryResult(BaseModel):
    query_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    original_input: str
    intent: Optional[QueryIntent] = None
    case_context_id: Optional[str] = None
    resolved_entity_ids: List[str] = Field(default_factory=list)
    disambiguation_required: bool = False
    disambiguation_candidates: List[DisambiguationCandidate] = Field(default_factory=list)
    ranking_reason: Optional[str] = None
    execution_status: str = "PENDING"  # SUCCESS, BLOCKED_DISAMBIGUATION, UNSUPPORTED, NOT_FOUND, NEEDS_CLARIFICATION, ERROR
    executed_backend_operation: Optional[str] = None
    data: Any = None
    message: str = ""
    event_ids: List[str] = Field(default_factory=list)


OUT_OF_SCOPE_PATTERNS = [
    r"\bdelete\b",
    r"\bdrop\b",
    r"\bremove\b.*record",
    r"\bchange\b.*identity",
    r"\bupdate\b.*status",
    r"\bmutate\b",
    r"\baccess\b.*bank account",
    r"\bsteal\b",
    r"\bhack\b",
    r"\bguilt\b",
    r"\bconvict\b",
    r"\bprove\b.*guilty",
    r"\bprivate bank details\b",
]

UNSUPPORTED_MESSAGE = "I can search by entity, timeline, path, or anomalies — try rephrasing."


class QueryParserService:
    """
    Constrained natural-language query translation layer in front of M13 investigation workspace.
    Enforces strict Pydantic validation, M2 confirmed resolution, M4 graph-distance disambiguation,
    mandatory officer selection gate, EventStore audit logging, and M13-only backend execution.
    """

    def __init__(
        self,
        backend: InvestigationWorkspaceBackend,
        event_store: Optional[EventStore] = None,
        ollama_client: Optional[OllamaClient] = None,
        custom_graph_edges: Optional[List[Tuple[str, str]]] = None,
        reference_time: Optional[Union[datetime, str, float]] = None,
    ):
        self.backend = backend
        self.event_store = event_store or EventStore()
        self.ollama = ollama_client or OllamaClient()
        self.sessions: Dict[str, DisambiguationSession] = {}
        self.custom_graph_edges: List[Tuple[str, str]] = custom_graph_edges or []
        self._reference_time: Optional[datetime] = None
        if reference_time is not None:
            self.set_reference_time(reference_time)

    def set_reference_time(self, ref: Optional[Union[datetime, str, float]]) -> None:
        """Sets an authoritative server/test reference datetime for deterministic relative-time resolution."""
        if ref is None:
            self._reference_time = None
        elif isinstance(ref, datetime):
            self._reference_time = ref if ref.tzinfo else ref.replace(tzinfo=timezone.utc)
        elif isinstance(ref, (int, float)):
            self._reference_time = datetime.fromtimestamp(float(ref), tz=timezone.utc)
        elif isinstance(ref, str):
            try:
                self._reference_time = datetime.fromisoformat(ref.replace("Z", "+00:00"))
            except Exception:
                self._reference_time = pd.to_datetime(ref, utc=True).to_pydatetime()

    def get_reference_time(self, explicit_ref: Optional[Union[datetime, str, float]] = None) -> datetime:
        """Retrieves active reference datetime: explicit -> service configured -> current UTC."""
        if explicit_ref is not None:
            if isinstance(explicit_ref, datetime):
                return explicit_ref if explicit_ref.tzinfo else explicit_ref.replace(tzinfo=timezone.utc)
            elif isinstance(explicit_ref, (int, float)):
                return datetime.fromtimestamp(float(explicit_ref), tz=timezone.utc)
            elif isinstance(explicit_ref, str):
                try:
                    return datetime.fromisoformat(explicit_ref.replace("Z", "+00:00"))
                except Exception:
                    return pd.to_datetime(explicit_ref, utc=True).to_pydatetime()
        if self._reference_time is not None:
            return self._reference_time
        return datetime.now(timezone.utc)

    def resolve_time_bounds(
        self,
        phrase: str,
        reference_time: Optional[Union[datetime, str, float]] = None
    ) -> TimeRange:
        """Helper to resolve a temporal phrase against the active reference clock."""
        ref_dt = self.get_reference_time(reference_time)
        return build_resolved_time_range(phrase, ref_dt)

    def get_or_create_session(
        self,
        session_id: Optional[str] = None,
        case_context_id: Optional[str] = None,
        officer_id: str = "OFFICER_DEFAULT",
        reference_time: Optional[datetime] = None
    ) -> DisambiguationSession:
        if session_id and session_id in self.sessions:
            session = self.sessions[session_id]
            if case_context_id is not None:
                # If case context explicitly changed, clear inherited entity context
                if session.case_context_id != case_context_id:
                    session.last_resolved_entity_id = None
                    session.last_resolved_entity_2_id = None
                session.case_context_id = case_context_id
            if reference_time is not None:
                session.reference_time = reference_time
            return session

        new_sess = DisambiguationSession(
            session_id=session_id,
            case_context_id=case_context_id,
            officer_id=officer_id,
            reference_time=reference_time
        )
        self.sessions[new_sess.session_id] = new_sess
        return new_sess

    # ── PHASE 1: QUERY INTENT GENERATION & STRICT VALIDATION ──────────────────

    def parse_intent(
        self,
        officer_input: str,
        session: Optional[DisambiguationSession] = None,
        reference_time: Optional[Union[datetime, str, float]] = None
    ) -> QueryIntent:
        """
        Translates officer natural-language input into strict QueryIntent via local Ollama.
        Server controls case_context_id; model cannot set it.
        Deterministic relative time resolution is anchored to server reference timestamp.
        Out-of-scope requests produce UNSUPPORTED QueryType.
        """
        raw_text = officer_input.strip()

        # Deterministic boundary check for out-of-scope/destructive operations
        for pat in OUT_OF_SCOPE_PATTERNS:
            if re.search(pat, raw_text, re.IGNORECASE):
                return QueryIntent(query_type=QueryType.UNSUPPORTED)

        ref_dt = self.get_reference_time(reference_time or (session.reference_time if session else None))

        prompt = f"""
You are an investigative query parser. Translate the following officer inquiry into a structured QueryIntent object.
Supported query types ONLY:
- ENTITY_LOOKUP: Search, lookup, or inspect an entity profile/details (e.g. "Find Rahul Sharma", "Who is ACC-1001", "Lookup user123").
- TIMELINE: Chronological events or history of an entity (e.g. "Show Rahul Sharma's timeline", "Activity for John last month", "Show timeline for Amit Kumar").
- PATH_BETWEEN: Connections or path between two distinct entities (e.g. "Show path between Rahul Sharma and Amit Kumar").
- ANOMALY_LIST: List anomalies, alerts, triage queue, or suspicious activities (e.g. "Show anomalous activity", "List triage queue", "Show anomalies").

If the user query requests actions outside these 4 types (such as modifying records, deleting data, hacking, determining legal guilt, or general chat), output query_type "UNSUPPORTED".

CRITICAL RULES:
1. Do NOT generate case_context_id.
2. entity_ref_2 is ONLY permitted for PATH_BETWEEN.
3. For TIMELINE or relative date queries like "now just last month" where the entity is implicit, leave entity_ref empty or null.
4. "Show anomalous activity" or queries about anomalies/triage must ALWAYS be query_type "ANOMALY_LIST" with entity_ref null.
5. In "Show timeline for X", the entity_ref is "X", NOT "timeline".
6. For time_filter, ONLY extract the raw temporal phrase into "raw_text" (e.g. "last month", "yesterday", "this week"). Do NOT calculate or invent start_date or end_date (leave them null).

Examples:
- "Find Rahul Sharma" -> {{"query_type": "ENTITY_LOOKUP", "entity_ref": "Rahul Sharma", "entity_ref_2": null, "time_filter": null}}
- "Show Rahul Sharma's timeline" -> {{"query_type": "TIMELINE", "entity_ref": "Rahul Sharma", "entity_ref_2": null, "time_filter": null}}
- "Show timeline for Amit Kumar" -> {{"query_type": "TIMELINE", "entity_ref": "Amit Kumar", "entity_ref_2": null, "time_filter": null}}
- "Show the path between Rahul Sharma and Amit Kumar" -> {{"query_type": "PATH_BETWEEN", "entity_ref": "Rahul Sharma", "entity_ref_2": "Amit Kumar", "time_filter": null}}
- "Show anomalous activity" -> {{"query_type": "ANOMALY_LIST", "entity_ref": null, "entity_ref_2": null, "time_filter": null}}
- "Now just last month" -> {{"query_type": "TIMELINE", "entity_ref": null, "entity_ref_2": null, "time_filter": {{"raw_text": "last month"}}}}

Output valid JSON adhering strictly to this schema:
{{
  "query_type": "ENTITY_LOOKUP" | "TIMELINE" | "PATH_BETWEEN" | "ANOMALY_LIST" | "UNSUPPORTED",
  "entity_ref": string or null,
  "entity_ref_2": string or null,
  "time_filter": {{
      "start_date": null,
      "end_date": null,
      "raw_text": string or null
  }} or null
}}

Officer Inquiry: "{raw_text}"
"""
        parsed_dict: Dict[str, Any] = {}
        try:
            resp = self.ollama.generate(prompt=prompt, format_json=True)
            raw_response = resp.get("response", "{}")
            parsed_dict = json.loads(raw_response)
        except Exception:
            # Fallback regex-guided heuristics if Ollama is unreachable or malformed JSON
            parsed_dict = self._fallback_parse_intent(raw_text, session=session)

        # Enforce server control: strip model-supplied case_context_id if present
        parsed_dict.pop("case_context_id", None)

        # Correct anomalous query misclassification
        if any(w in raw_text.lower() for w in ["anomal", "triage", "alerts"]):
            if not any(w in raw_text.lower() for w in ["between", "path"]):
                parsed_dict["query_type"] = QueryType.ANOMALY_LIST.value
                parsed_dict["entity_ref"] = None

        q_type_str = parsed_dict.get("query_type", "UNSUPPORTED")

        # Extract temporal phrase (reject any model-invented start_date/end_date)
        candidate_phrase: Optional[str] = None
        tf_dict = parsed_dict.get("time_filter")
        if isinstance(tf_dict, dict):
            candidate_phrase = tf_dict.get("raw_text")

        if not candidate_phrase:
            candidate_phrase = extract_temporal_phrase(raw_text)

        # Multi-turn temporal refinement check:
        # If model returned UNSUPPORTED or TIMELINE without entity, and active session has resolved entity
        if session and session.last_resolved_entity_id:
            if any(w in raw_text.lower() for w in ["month", "week", "day", "yesterday", "today", "now", "last", "since", "until", "earlier", "recently", "ago"]):
                q_type_str = QueryType.TIMELINE.value
                if not parsed_dict.get("entity_ref"):
                    parsed_dict["entity_ref"] = session.last_resolved_entity_id
                if not candidate_phrase:
                    candidate_phrase = extract_temporal_phrase(raw_text) or raw_text.strip()

        if q_type_str not in [q.value for q in QueryType]:
            q_type_str = "UNSUPPORTED"
        parsed_dict["query_type"] = q_type_str

        # Clean corrupted entity_ref
        cur_ref = str(parsed_dict.get("entity_ref") or "").strip()
        if cur_ref.lower() in ["timeline", "history", "activity", "anomalous activity", "none", "null"]:
            m = re.search(r"(?:for|of|about)\s+([A-Za-z0-9_\+\-\@\s]+?)(?:\s+for|\s+last|\s+this|\s+yesterday|\s+today|\s+previous|\s+from|\s+between|$)", raw_text, re.IGNORECASE)
            parsed_dict["entity_ref"] = m.group(1).strip() if m else None

        # Validate entity_ref_2 presence
        if q_type_str != QueryType.PATH_BETWEEN.value and parsed_dict.get("entity_ref_2"):
            parsed_dict["entity_ref_2"] = None

        # Clean empty strings to None
        if not parsed_dict.get("entity_ref"):
            parsed_dict["entity_ref"] = None
        if not parsed_dict.get("entity_ref_2"):
            parsed_dict["entity_ref_2"] = None

        # ── Deterministic Relative Time Resolution (Server Reference Clock) ──
        if candidate_phrase:
            resolved_tr = build_resolved_time_range(candidate_phrase, ref_dt)
            parsed_dict["time_filter"] = resolved_tr.model_dump()
        else:
            parsed_dict["time_filter"] = None

        intent = QueryIntent(**parsed_dict)

        # Multi-turn context inheritance for TIMELINE / PATH
        if session:
            # Server injects authoritative case_context_id
            intent.case_context_id = session.case_context_id

            if intent.query_type == QueryType.TIMELINE and not intent.entity_ref:
                if session.last_resolved_entity_id:
                    intent.entity_ref = session.last_resolved_entity_id

        return intent

    def _fallback_parse_intent(self, text: str, session: Optional[DisambiguationSession] = None) -> Dict[str, Any]:
        """Deterministic rule-based fallback parser when Ollama is unavailable."""
        t_low = text.lower()
        if any(w in t_low for w in ["anomal", "triage", "alerts", "suspicious"]):
            return {"query_type": "ANOMALY_LIST", "entity_ref": None, "entity_ref_2": None}
        elif any(w in t_low for w in ["between", "path from", "connect", "path between"]):
            # Extract two entities
            m = re.search(r"between\s+([a-zA-Z0-9_\+\-\@\s]+?)\s+and\s+([a-zA-Z0-9_\+\-\@\s]+)", text, re.IGNORECASE)
            if m:
                return {
                    "query_type": "PATH_BETWEEN",
                    "entity_ref": m.group(1).strip(),
                    "entity_ref_2": m.group(2).strip()
                }
            return {"query_type": "PATH_BETWEEN", "entity_ref": None, "entity_ref_2": None}
        elif any(w in t_low for w in ["timeline", "history", "events for", "activity"]):
            m = re.search(r"(?:show\s+timeline\s+for|timeline\s+for|history\s+for|events\s+for|timeline\s+of|show\s+)([a-zA-Z0-9_\+\-\@\s]+?)(?:'s|\s+timeline|\s+history|\s+for|\s+last|\s+this|\s+yesterday|\s+today|\s+previous|\s+from|\s+between|$)", text, re.IGNORECASE)
            ent = m.group(1).strip() if m else None
            tf_phrase = extract_temporal_phrase(text)
            tf = {"raw_text": tf_phrase} if tf_phrase else None
            return {
                "query_type": "TIMELINE",
                "entity_ref": ent,
                "time_filter": tf
            }
        elif session and session.last_resolved_entity_id and any(w in t_low for w in ["month", "week", "day", "yesterday", "today", "now", "last", "since", "until", "earlier", "recently", "ago"]):
            tf_phrase = extract_temporal_phrase(text)
            return {
                "query_type": "TIMELINE",
                "entity_ref": session.last_resolved_entity_id,
                "time_filter": {"raw_text": tf_phrase or text.strip()}
            }
        elif any(w in t_low for w in ["find", "who is", "lookup", "search", "inspect", "get entity"]):
            m = re.search(r"(?:find|who is|lookup|search|inspect|get entity)\s+([a-zA-Z0-9_\+\-\@\s]+)", text, re.IGNORECASE)
            ent = m.group(1).strip() if m else text.strip()
            return {"query_type": "ENTITY_LOOKUP", "entity_ref": ent}
        return {"query_type": "UNSUPPORTED"}

    # ── PHASE 2 & 3: M2 RESOLUTION & M4 GRAPH DISAMBIGUATION ─────────────────

    def resolve_entity_m2(
        self,
        entity_ref: str,
        case_context_id: Optional[str] = None
    ) -> Tuple[List[str], List[DisambiguationCandidate], str]:
        """
        Resolves raw identifier/name through authoritative M2 layer.
        Returns:
            confirmed_ids: List of matching confirmed canonical IDs.
            candidates: List of ranked DisambiguationCandidate objects (if ambiguous).
            status_note: Explanation of resolution result.
        Enforces:
            - POSSIBLE-only entities are strictly excluded from execution candidates.
            - Zero matches return safe "no entity found" with suggestion.
            - Exact strong identifiers resolve directly.
            - Multiple matches trigger M4 graph-distance ranking.
        """
        ref_clean = entity_ref.strip()
        ref_lower = ref_clean.lower()

        # Collect matches across backend.entities_df, bridge_df, and valid_entities
        confirmed_matches: Dict[str, Dict[str, Any]] = {}
        possible_matches: List[str] = []

        # 1. Search entities_df
        if hasattr(self.backend, "entities_df") and not self.backend.entities_df.empty:
            for _, r in self.backend.entities_df.iterrows():
                cid = str(r.get("canonical_entity_id", "")).strip()
                raw_id = str(r.get("raw_identifier", "")).strip()
                match_status = str(r.get("match_status", MatchStatus.CONFIRMED)).upper()
                id_type = str(r.get("identifier_type", "ENTITY")).upper()

                matches_exact = (ref_lower == raw_id.lower() or ref_lower == cid.lower())
                matches_sub = (ref_lower in raw_id.lower() or ref_lower in cid.lower())

                if matches_exact or matches_sub:
                    if match_status == MatchStatus.POSSIBLE or match_status == "POSSIBLE":
                        possible_matches.append(cid)
                    elif match_status == MatchStatus.CONFIRMED or match_status == "CONFIRMED":
                        basis = MatchBasis.EXACT_IDENTIFIER if matches_exact else MatchBasis.NAME_ONLY
                        if cid not in confirmed_matches or matches_exact:
                            confirmed_matches[cid] = {
                                "canonical_entity_id": cid,
                                "raw_identifier": raw_id,
                                "identifier_type": id_type,
                                "match_basis": basis,
                            }

        # 2. Search bridge_df
        if hasattr(self.backend, "bridge_df") and not self.backend.bridge_df.empty:
            for _, r in self.backend.bridge_df.iterrows():
                cid = str(r.get("canonical_entity_id", "")).strip()
                raw_id = str(r.get("raw_identifier", "")).strip()
                matches_exact = (ref_lower == raw_id.lower() or ref_lower == cid.lower())
                matches_sub = (ref_lower in raw_id.lower() or ref_lower in cid.lower())

                if matches_exact or matches_sub:
                    basis = MatchBasis.EXACT_IDENTIFIER if matches_exact else MatchBasis.NAME_ONLY
                    if cid not in confirmed_matches or matches_exact:
                        confirmed_matches[cid] = {
                            "canonical_entity_id": cid,
                            "raw_identifier": raw_id,
                            "identifier_type": str(r.get("domain", "BRIDGE")),
                            "match_basis": basis,
                        }

        # 3. Direct lookup in backend.valid_entities
        if ref_clean in getattr(self.backend, "valid_entities", set()):
            if ref_clean not in confirmed_matches:
                confirmed_matches[ref_clean] = {
                    "canonical_entity_id": ref_clean,
                    "raw_identifier": ref_clean,
                    "identifier_type": "CANONICAL",
                    "match_basis": MatchBasis.EXACT_IDENTIFIER,
                }

        # CASE 4: POSSIBLE ONLY EXCLUSION
        if not confirmed_matches and possible_matches:
            return (
                [],
                [],
                f"Identifier '{entity_ref}' matched only POSSIBLE (unconfirmed) entity records. "
                f"POSSIBLE identities cannot be queried directly — officer confirmation required."
            )

        # CASE 3: ZERO MATCHES
        if not confirmed_matches:
            return (
                [],
                [],
                f"No confirmed entity found for '{entity_ref}'. "
                f"Try searching using a stronger identifier such as phone (+1-555-...), account (ACC-...), or device IP."
            )

        # CASE 1: EXACT STRONG IDENTIFIER (Single Match)
        if len(confirmed_matches) == 1:
            single_id = list(confirmed_matches.keys())[0]
            return ([single_id], [], "Single confirmed match resolved directly.")

        # CASE 2: MULTIPLE MATCHES -> BUILD DISAMBIGUATION CANDIDATES & RANK VIA M4
        candidates, ranking_note = self._build_and_rank_candidates(
            confirmed_matches,
            case_context_id=case_context_id
        )
        return (list(confirmed_matches.keys()), candidates, ranking_note)

    def _build_and_rank_candidates(
        self,
        confirmed_matches: Dict[str, Dict[str, Any]],
        case_context_id: Optional[str] = None
    ) -> Tuple[List[DisambiguationCandidate], str]:
        """
        Ranks multiple CONFIRMED candidates using M4 graph distance to active case context.
        If no active context exists, falls back to last-confirmed activity date.
        Never mutates M4 graph.
        """
        # Determine active case context entities
        active_case_entities: Set[str] = set()
        if case_context_id and hasattr(self.backend, "cases") and case_context_id in self.backend.cases:
            case = self.backend.cases[case_context_id]
            if case.canonical_entity_id:
                active_case_entities.add(case.canonical_entity_id)

        has_case_context = len(active_case_entities) > 0

        # Build candidate models
        raw_candidates: List[Tuple[DisambiguationCandidate, Optional[float]]] = []
        for idx, (cid, match_info) in enumerate(sorted(confirmed_matches.items())):
            # Retrieve last confirmed activity from timeline
            last_activity_str: Optional[str] = None
            last_epoch: Optional[float] = None
            try:
                tl = self.backend.get_timeline(cid)
                if tl:
                    last_ev = tl[-1]
                    last_activity_str = str(last_ev.get("timestamp") or last_ev.get("epoch_time", ""))
                    ep = last_ev.get("epoch_time")
                    if ep is not None:
                        last_epoch = float(ep)
            except Exception:
                pass

            # Calculate M4 graph hop distance
            dist = 999
            if has_case_context:
                dist = self._compute_m4_hop_distance(cid, active_case_entities)

            cand = DisambiguationCandidate(
                candidate_id=f"CAND_{idx + 1}",
                canonical_entity_id=cid,
                display_label=f"{match_info.get('raw_identifier', cid)} ({cid})" + (f" - Last active: {last_activity_str}" if last_activity_str else ""),
                graph_distance_to_context=dist,
                match_basis=match_info.get("match_basis", MatchBasis.NAME_ONLY),
                last_confirmed_activity=last_activity_str
            )
            raw_candidates.append((cand, last_epoch))

        if has_case_context:
            # Deterministic sorting:
            # 1. graph_distance_to_context ascending
            # 2. last_confirmed_activity descending (epoch)
            # 3. canonical_entity_id ascending
            raw_candidates.sort(
                key=lambda item: (
                    item[0].graph_distance_to_context,
                    -(item[1] or 0.0),
                    item[0].canonical_entity_id
                )
            )
            ranking_note = (
                f"Ranked by M4 graph proximity to active case context '{case_context_id}' "
                f"(lowest hop distance first, tie-break by activity recency)."
            )
        else:
            # Fallback: rank by last-confirmed activity descending, then canonical_entity_id
            raw_candidates.sort(
                key=lambda item: (
                    -(item[1] or 0.0),
                    item[0].canonical_entity_id
                )
            )
            ranking_note = "no active case context — showing most recently active matches"

        # Re-assign candidate_id sequentially according to ranking order
        ordered_candidates = []
        for rank_idx, (cand, _) in enumerate(raw_candidates):
            reindexed_cand = cand.model_copy(update={"candidate_id": f"CAND_{rank_idx + 1}"})
            ordered_candidates.append(reindexed_cand)

        return (ordered_candidates, ranking_note)

    def _compute_m4_hop_distance(self, candidate_id: str, context_entities: Set[str]) -> int:
        """
        Computes minimum undirected hop distance from candidate_id to any entity in context_entities.
        Strictly READ-ONLY. Never mutates M4 graph.
        """
        if candidate_id in context_entities:
            return 0

        # Build adjacency graph from custom edges and backend events
        adj: Dict[str, Set[str]] = collections.defaultdict(set)

        # 1. Custom topology edges (e.g. for controlled test fixtures)
        for u, v in self.custom_graph_edges:
            adj[u].add(v)
            adj[v].add(u)

        # 2. Events in backend.events_df
        if hasattr(self.backend, "events_df") and not self.backend.events_df.empty:
            for _, r in self.backend.events_df.iterrows():
                act = str(r.get("actor_id", "")).strip()
                tgt = str(r.get("target_id", "")).strip()
                if act and tgt:
                    adj[act].add(tgt)
                    adj[tgt].add(act)

        # 3. Evidence engine graph nodes
        if hasattr(self.backend, "evidence_engine") and hasattr(self.backend.evidence_engine, "graph"):
            g = self.backend.evidence_engine.graph
            for edge in getattr(g, "edges", []):
                if isinstance(edge, dict):
                    p = str(edge.get("parent_id", ""))
                    c = str(edge.get("child_id", ""))
                    if p and c:
                        adj[p].add(c)
                        adj[c].add(p)
                elif isinstance(edge, (list, tuple)) and len(edge) >= 2:
                    p = str(edge[0])
                    c = str(edge[1])
                    if p and c:
                        adj[p].add(c)
                        adj[c].add(p)

        # BFS shortest path from candidate_id to context_entities
        queue = collections.deque([(candidate_id, 0)])
        visited = {candidate_id}

        while queue:
            curr, hops = queue.popleft()
            if curr in context_entities:
                return hops

            if hops >= 10:  # Max search horizon
                continue

            for neighbor in adj.get(curr, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, hops + 1))

        return 999  # Unreachable

    # ── PHASE 3: OFFICER DISAMBIGUATION GATE & EVENT LOGGING ─────────────────

    def execute_query(
        self,
        officer_input: str,
        case_context_id: Optional[str] = None,
        session_id: Optional[str] = None,
        officer_id: str = "OFFICER_DEFAULT",
        reference_time: Optional[Union[datetime, str, float]] = None
    ) -> QueryResult:
        """
        Full end-to-end execution pipeline:
        Officer Input -> QueryIntent -> M2 Resolution -> M4 Disambiguation Gate -> EventLog -> M13 Execution.
        """
        session = self.get_or_create_session(
            session_id=session_id,
            case_context_id=case_context_id,
            officer_id=officer_id,
            reference_time=self.get_reference_time(reference_time) if reference_time else None
        )

        intent = self.parse_intent(officer_input, session=session, reference_time=reference_time)

        # Hand off unsupported
        if intent.query_type == QueryType.UNSUPPORTED:
            return QueryResult(
                original_input=officer_input,
                intent=intent,
                case_context_id=session.case_context_id,
                execution_status="UNSUPPORTED",
                message=UNSUPPORTED_MESSAGE
            )

        # Temporal clarification gate: do NOT execute unrestricted query if temporal phrase was unresolvable
        if intent.time_filter and intent.time_filter.raw_text:
            if intent.time_filter.start_epoch is None or intent.time_filter.end_epoch is None:
                event_ids: List[str] = []
                if self.event_store:
                    evt_meta = {
                        "original_input": officer_input,
                        "query_type": intent.query_type.value,
                        "resolved_entities": [session.last_resolved_entity_id] if session.last_resolved_entity_id else [],
                        "session_id": session.session_id,
                        "time_filter": intent.time_filter.model_dump(),
                        "status": "NEEDS_CLARIFICATION"
                    }
                    ev = DecisionEvent(
                        event_type=EventType.QUERY_ISSUED,
                        officer_id=session.officer_id,
                        case_id=session.case_context_id or "NO_CASE_CONTEXT",
                        entity_id=session.last_resolved_entity_id or "TEMPORAL_QUERY",
                        previous_state=DecisionState.NONE,
                        requested_state=DecisionState.NONE,
                        reason="Query issued with unresolvable temporal filter",
                        metadata=evt_meta
                    )
                    self.event_store.append_event(ev)
                    event_ids.append(ev.event_id)

                return QueryResult(
                    original_input=officer_input,
                    intent=intent,
                    case_context_id=session.case_context_id,
                    resolved_entity_ids=[session.last_resolved_entity_id] if session.last_resolved_entity_id else [],
                    execution_status="NEEDS_CLARIFICATION",
                    executed_backend_operation=None,
                    data=None,
                    message=(
                        f"Temporal expression '{intent.time_filter.raw_text}' cannot be deterministically resolved. "
                        f"Query execution stopped to prevent an unrestricted search. Please specify a supported "
                        f"relative period (last month, this month, last week, this week, yesterday, today) or an explicit date range."
                    ),
                    event_ids=event_ids
                )

        # Resolve primary entity
        resolved_primary: Optional[str] = None
        resolved_secondary: Optional[str] = None

        if intent.query_type in (QueryType.ENTITY_LOOKUP, QueryType.TIMELINE, QueryType.PATH_BETWEEN):
            if not intent.entity_ref:
                return QueryResult(
                    original_input=officer_input,
                    intent=intent,
                    case_context_id=session.case_context_id,
                    execution_status="ERROR",
                    message="Missing required entity reference for query."
                )

            confirmed_ids, candidates, note = self.resolve_entity_m2(
                intent.entity_ref,
                case_context_id=session.case_context_id
            )

            if not confirmed_ids:
                return QueryResult(
                    original_input=officer_input,
                    intent=intent,
                    case_context_id=session.case_context_id,
                    execution_status="NOT_FOUND",
                    message=note
                )

            # DISAMBIGUATION GATE: Multiple matching confirmed entities
            if len(candidates) > 1:
                session.pending_candidates = {c.candidate_id: c for c in candidates}
                session.pending_intent = intent
                session.pending_original_input = officer_input

                return QueryResult(
                    original_input=officer_input,
                    intent=intent,
                    case_context_id=session.case_context_id,
                    disambiguation_required=True,
                    disambiguation_candidates=candidates,
                    ranking_reason=note,
                    execution_status="BLOCKED_DISAMBIGUATION",
                    message=(
                        f"Multiple confirmed entities match '{intent.entity_ref}'. "
                        f"Query execution blocked pending officer selection."
                    )
                )

            resolved_primary = confirmed_ids[0]

        # For PATH_BETWEEN, validate and resolve entity_ref_2
        if intent.query_type == QueryType.PATH_BETWEEN:
            if not intent.entity_ref_2:
                return QueryResult(
                    original_input=officer_input,
                    intent=intent,
                    case_context_id=session.case_context_id,
                    execution_status="ERROR",
                    message="PATH_BETWEEN requires two distinct entity references (entity_ref and entity_ref_2)."
                )

            conf_2, cand_2, note_2 = self.resolve_entity_m2(
                intent.entity_ref_2,
                case_context_id=session.case_context_id
            )

            if not conf_2:
                return QueryResult(
                    original_input=officer_input,
                    intent=intent,
                    case_context_id=session.case_context_id,
                    execution_status="NOT_FOUND",
                    message=f"Endpoint 2: {note_2}"
                )

            if len(cand_2) > 1:
                session.pending_candidates = {c.candidate_id: c for c in cand_2}
                session.pending_intent = intent
                session.pending_original_input = officer_input

                return QueryResult(
                    original_input=officer_input,
                    intent=intent,
                    case_context_id=session.case_context_id,
                    disambiguation_required=True,
                    disambiguation_candidates=cand_2,
                    ranking_reason=note_2,
                    execution_status="BLOCKED_DISAMBIGUATION",
                    message=f"Multiple confirmed entities match endpoint '{intent.entity_ref_2}'. Officer selection required."
                )

            resolved_secondary = conf_2[0]

        # Log QUERY_ISSUED to EventStore
        event_ids: List[str] = []
        if self.event_store:
            evt_meta = {
                "original_input": officer_input,
                "query_type": intent.query_type.value,
                "resolved_entities": [e for e in [resolved_primary, resolved_secondary] if e],
                "session_id": session.session_id,
                "time_filter": intent.time_filter.model_dump() if intent.time_filter else None,
            }
            ev = DecisionEvent(
                event_type=EventType.QUERY_ISSUED,
                officer_id=session.officer_id,
                case_id=session.case_context_id or "NO_CASE_CONTEXT",
                entity_id=resolved_primary or "ANOMALY_QUERY",
                previous_state=DecisionState.NONE,
                requested_state=DecisionState.NONE,
                reason="Query issued by investigator",
                metadata=evt_meta
            )
            self.event_store.append_event(ev)
            event_ids.append(ev.event_id)

        # Update session memory
        if resolved_primary:
            session.last_resolved_entity_id = resolved_primary
        if resolved_secondary:
            session.last_resolved_entity_2_id = resolved_secondary
        session.last_query_intent = intent

        # Execute through M13
        return self._execute_m13(
            intent=intent,
            resolved_primary=resolved_primary,
            resolved_secondary=resolved_secondary,
            original_input=officer_input,
            session=session,
            event_ids=event_ids
        )

    def resolve_disambiguation(
        self,
        session_id: str,
        candidate_id: str,
        officer_id: Optional[str] = None
    ) -> QueryResult:
        """
        Explicit officer selection operation.
        Validates selected candidate against current candidate set, confirms it is CONFIRMED,
        appends DISAMBIGUATION_RESOLVED to EventStore, and resumes execution.
        """
        if session_id not in self.sessions:
            raise ValueError(f"Session '{session_id}' not found.")

        session = self.sessions[session_id]
        if candidate_id not in session.pending_candidates:
            raise ValueError(
                f"Invalid or stale candidate ID '{candidate_id}'. "
                f"Valid choices in session: {list(session.pending_candidates.keys())}"
            )

        selected = session.pending_candidates[candidate_id]
        chosen_cid = selected.canonical_entity_id
        original_input = session.pending_original_input or "Ambiguous query"
        intent = session.pending_intent

        active_officer = officer_id or session.officer_id

        # Log DISAMBIGUATION_RESOLVED to EventStore
        event_ids: List[str] = []
        if self.event_store:
            evt_meta = {
                "session_id": session_id,
                "selected_candidate_id": candidate_id,
                "canonical_entity_id": chosen_cid,
                "original_candidate_set": [c.canonical_entity_id for c in session.pending_candidates.values()],
                "match_basis": selected.match_basis.value,
                "graph_distance": selected.graph_distance_to_context,
            }
            ev = DecisionEvent(
                event_type=EventType.DISAMBIGUATION_RESOLVED,
                officer_id=active_officer,
                case_id=session.case_context_id or "NO_CASE_CONTEXT",
                entity_id=chosen_cid,
                previous_state=DecisionState.POSSIBLE,
                requested_state=DecisionState.CONFIRMED,
                reason="Investigator resolved entity disambiguation",
                metadata=evt_meta
            )
            self.event_store.append_event(ev)
            event_ids.append(ev.event_id)

        # Clear pending gate and update session state
        session.pending_candidates.clear()
        session.pending_intent = None
        session.pending_original_input = None
        session.last_resolved_entity_id = chosen_cid
        session.last_query_intent = intent

        # Execute resumed M13 query
        return self._execute_m13(
            intent=intent,
            resolved_primary=chosen_cid,
            resolved_secondary=session.last_resolved_entity_2_id,
            original_input=original_input,
            session=session,
            event_ids=event_ids
        )

    def _execute_m13(
        self,
        intent: QueryIntent,
        resolved_primary: Optional[str],
        resolved_secondary: Optional[str],
        original_input: str,
        session: DisambiguationSession,
        event_ids: List[str]
    ) -> QueryResult:
        """Invokes ONLY existing M13 InvestigationWorkspaceBackend functions."""
        op_name = intent.query_type.value
        data: Any = None

        if intent.query_type == QueryType.ENTITY_LOOKUP:
            op_name = "backend.investigate_entity"
            data = self.backend.investigate_entity(resolved_primary)

        elif intent.query_type == QueryType.TIMELINE:
            op_name = "backend.get_timeline"
            f_time = intent.time_filter.start_epoch if intent.time_filter else None
            t_time = intent.time_filter.end_epoch if intent.time_filter else None
            data = self.backend.get_timeline(resolved_primary, from_time=f_time, to_time=t_time)

        elif intent.query_type == QueryType.PATH_BETWEEN:
            op_name = "backend.get_paths"
            data = self.backend.get_paths(resolved_primary, resolved_secondary, max_hops=3)

        elif intent.query_type == QueryType.ANOMALY_LIST:
            op_name = "backend.get_triage_queue"
            data = self.backend.get_triage_queue(case_id=session.case_context_id)

        return QueryResult(
            original_input=original_input,
            intent=intent,
            case_context_id=session.case_context_id,
            resolved_entity_ids=[e for e in [resolved_primary, resolved_secondary] if e],
            execution_status="SUCCESS",
            executed_backend_operation=op_name,
            data=data,
            message=f"Query successfully executed via M13 operation '{op_name}'.",
            event_ids=event_ids
        )
