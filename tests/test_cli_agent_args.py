import pytest
import subprocess
import json

def test_agent_investigate_args():
    cmd1 = [
        "./dfap-cli",
        "agent",
        "investigate",
        "Why was ENT_DFAP_4DOM_001 flagged?",
        "CASE-DFAP-4DOMAIN-001"
    ]
    res1 = subprocess.run(cmd1, capture_output=True, text=True)
    assert "Question: Why was ENT_DFAP_4DOM_001 flagged?" in res1.stdout
    assert "Case 'was' not found" not in res1.stdout
    assert "CONFLICTED" in res1.stdout or "COMPLETED" in res1.stdout or "HUMAN_REVIEW_REQUIRED" in res1.stdout
    assert "finding_explainability" in res1.stdout or "cross_domain_conflict" in res1.stdout or "EVD-" in res1.stdout

def test_agent_investigate_args_2():
    cmd2 = [
        "./dfap-cli",
        "agent",
        "investigate",
        "Why is this finding high risk?",
        "CASE-DFAP-4DOMAIN-001"
    ]
    res2 = subprocess.run(cmd2, capture_output=True, text=True)
    assert "Question: Why is this finding high risk?" in res2.stdout
    assert "Case 'is' not found" not in res2.stdout
    assert "Case 'this' not found" not in res2.stdout
    assert "CONFLICTED" in res2.stdout or "COMPLETED" in res2.stdout or "HUMAN_REVIEW_REQUIRED" in res2.stdout
