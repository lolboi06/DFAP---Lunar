#!/usr/bin/env bash
# ============================================================================
# DFAP Feature 6 — Safety-Critical Prompt Invariant Manual Test
# SYNTHETIC TEST DATA ONLY. No production records are modified.
# ============================================================================
set -euo pipefail

CASE_ID="CASE-RED-POSSIBLE-001"
OFFICER="OFFICER_INVESTIGATOR_01"
TMP_DIR=$(mktemp -d -t dfap_feature6_test_XXXXXX)
EVENT_STORE_PATH="$TMP_DIR/data/features5_6_events.jsonl"

echo "========================================================================"
echo " DFAP FEATURE 6: SAFETY-CRITICAL PROMPT INVARIANT MANUAL VERIFICATION"
echo " Synthetic case ID : $CASE_ID"
echo " Officer           : $OFFICER"
echo " Temp dir          : $TMP_DIR"
echo "========================================================================"

# ── Step 0: Bootstrap synthetic case ────────────────────────────────────────
echo ""
echo "[Step 0] Bootstrapping synthetic RED+POSSIBLE case..."
PYTHONPATH="$(pwd)" ./venv/bin/python - <<PYEOF
import sys
sys.path.insert(0, ".")
from tests.helpers.synthetic_red_possible import setup_synthetic_red_possible, CASE_ID
import os, json

tmp_dir = "$TMP_DIR"
backend, event_store = setup_synthetic_red_possible(tmp_dir)
print(f"  Synthetic case '{CASE_ID}' registered.")
print(f"  Finding FND_SYN_RED_01 anomaly_score=0.95 → HIGH tier.")
possible = backend.entities_df[backend.entities_df["match_status"].str.upper() == "POSSIBLE"]
print(f"  POSSIBLE rows in entities_df: {len(possible)}")
print(f"  EventStore path: {event_store.file_path}")
PYEOF

echo ""
echo "[Step 1] Generating prompt candidates..."
echo "  Command: ./dfap-cli prompts candidates --case-id $CASE_ID"
echo "  NOTE: dfap-cli uses the production data path."
echo "        The in-process candidate generation is verified via the test suite."
echo ""
echo "--- BEGIN CANDIDATES OUTPUT (in-process via PYTHONPATH) ---"
PYTHONPATH="$(pwd)" ./venv/bin/python - <<PYEOF
import sys, json
sys.path.insert(0, ".")
from tests.helpers.synthetic_red_possible import setup_synthetic_red_possible, CASE_ID
from dfap.investigation.guided_prompts import GuidedPromptService
from dfap.investigation.event_sourcing import EventStore

backend, event_store = setup_synthetic_red_possible("$TMP_DIR")
svc = GuidedPromptService(backend=backend, event_store=event_store)
candidates = svc.generate_candidates(CASE_ID)
print(json.dumps([c.model_dump() for c in candidates], indent=2))
PYEOF
echo "--- END CANDIDATES OUTPUT ---"

echo ""
echo "[Step 2] Deciding prompts (officer: $OFFICER)..."
echo "--- BEGIN DECIDE OUTPUT ---"
PYTHONPATH="$(pwd)" ./venv/bin/python - <<PYEOF
import sys, json
sys.path.insert(0, ".")
from tests.helpers.synthetic_red_possible import setup_synthetic_red_possible, CASE_ID
from dfap.investigation.guided_prompts import GuidedPromptService
from dfap.investigation.event_sourcing import EventStore

backend, event_store = setup_synthetic_red_possible("$TMP_DIR")
svc = GuidedPromptService(backend=backend, event_store=event_store)
decisions = svc.decide_prompts(CASE_ID, "$OFFICER")

print(json.dumps([d.model_dump() for d in decisions], indent=2))

# Safety-critical assertion
sc = next((d for d in decisions if d.prompt_type == "RESOLVE_POSSIBLE_MATCH"), None)
if sc:
    print("")
    print("=== SAFETY-CRITICAL INVARIANT CHECK ===")
    print(f"  prompt_type      : {sc.prompt_type}")
    print(f"  decision_id      : {sc.decision_id}")
    print(f"  shown            : {sc.shown}")
    print(f"  is_safety_critical: {sc.context_snapshot.get('is_safety_critical', True)}")
    print(f"  bandit_evaluated : {sc.context_snapshot.get('bandit_evaluated')}")
    print(f"  bypass_reason    : {sc.context_snapshot.get('bypass_reason')}")
    assert sc.shown is True,                                        "FAIL: shown must be True"
    assert sc.context_snapshot.get("bandit_evaluated") is False,   "FAIL: bandit_evaluated must be False"
    assert sc.context_snapshot.get("bypass_reason") == "SAFETY_CRITICAL_RED_TIER_BYPASS", "FAIL: wrong bypass_reason"
    print("  RESULT: ALL SAFETY-CRITICAL ASSERTIONS PASSED ✓")
else:
    print("FAIL: No RESOLVE_POSSIBLE_MATCH decision found")
    sys.exit(1)
PYEOF
echo "--- END DECIDE OUTPUT ---"

echo ""
echo "[Step 3] Verifying persistence (fresh GuidedPromptService from EventStore)..."
echo "--- BEGIN HISTORY OUTPUT ---"
PYTHONPATH="$(pwd)" ./venv/bin/python - <<PYEOF
import sys, json
sys.path.insert(0, ".")
from tests.helpers.synthetic_red_possible import setup_synthetic_red_possible, CASE_ID
from dfap.investigation.guided_prompts import GuidedPromptService
from dfap.investigation.event_sourcing import EventStore, EventType

# First process: decide
backend, event_store = setup_synthetic_red_possible("$TMP_DIR")
svc_1 = GuidedPromptService(backend=backend, event_store=event_store)
decisions = svc_1.decide_prompts(CASE_ID, "$OFFICER")
sc = next(d for d in decisions if d.prompt_type == "RESOLVE_POSSIBLE_MATCH")
decision_id = sc.decision_id

# Second process: reload from EventStore (cross-process simulation)
svc_2 = GuidedPromptService(backend=backend, event_store=EventStore(event_store.path))
events = svc_2.event_store.get_events_for_case(CASE_ID)
shown_events = [
    e for e in events
    if e.event_type == EventType.PROMPT_SHOWN and e.metadata.get("decision_id") == decision_id
]
prompt_history = [e.to_dict() for e in shown_events]
print(json.dumps(prompt_history, indent=2, default=str))
print("")
print("=== PERSISTENCE CHECK ===")
print(f"  decision_id       : {decision_id}")
print(f"  PROMPT_SHOWN events found: {len(shown_events)}")
assert shown_events, "FAIL: No PROMPT_SHOWN event persisted"
assert shown_events[0].metadata.get("shown") is True
assert shown_events[0].metadata.get("is_safety_critical") is True
print("  RESULT: CROSS-PROCESS PERSISTENCE VERIFIED ✓")
PYEOF
echo "--- END HISTORY OUTPUT ---"

echo ""
echo "========================================================================"
echo " MANUAL TEST COMPLETE — ALL INVARIANTS SATISFIED"
echo "========================================================================"
echo " Expected results summary:"
echo "   shown            = true"
echo "   is_safety_critical = true"
echo "   bandit_evaluated = false"
echo "   bypass_reason    = SAFETY_CRITICAL_RED_TIER_BYPASS"
echo "   PROMPT_SHOWN event persisted across simulated process boundary ✓"
echo "========================================================================"

# Cleanup
rm -rf "$TMP_DIR"
