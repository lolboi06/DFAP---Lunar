with open("dfap/api_workspace.py", "r") as f:
    content = f.read()

sanitizer_def = """import math

def sanitize_json(obj):
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_json(x) for x in obj]
    return obj
"""

content = content.replace("logger = logging.getLogger(__name__)", "logger = logging.getLogger(__name__)\n\n" + sanitizer_def)

# Replace the return in get_unified_timeline
old_ret = """    return {
        "entity_id": entity_id,
        "case_id": case_id,
        "window": window,
        "total_events": len(enriched),
        "events": enriched,
        "chronology_guarantee": "Strictly Causal — zero future-event leakage."
    }"""

new_ret = """    return sanitize_json({
        "entity_id": entity_id,
        "case_id": case_id,
        "window": window,
        "total_events": len(enriched),
        "events": enriched,
        "chronology_guarantee": "Strictly Causal — zero future-event leakage."
    })"""

content = content.replace(old_ret, new_ret)

# Also in list_cross_domain_evidence
old_ev = """    return {
        "case_id": case_id,
        "count": len(filtered),
        "domains": list({e.get("source_domain") for e in all_evidence if e.get("source_domain")}),
        "evidence": filtered
    }"""

new_ev = """    return sanitize_json({
        "case_id": case_id,
        "count": len(filtered),
        "domains": list({e.get("source_domain") for e in all_evidence if e.get("source_domain")}),
        "evidence": filtered
    })"""

content = content.replace(old_ev, new_ev)

with open("dfap/api_workspace.py", "w") as f:
    f.write(content)
print("Sanitizer applied!")
