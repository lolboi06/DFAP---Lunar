#!/bin/bash
set -e
echo "Running release gate tests..."
./dfap-cli finding explain FND_4DOM_FUSED_001
./dfap-cli case forensic CASE-DFAP-4DOMAIN-001
./dfap-cli case risk CASE-DFAP-4DOMAIN-001
./dfap-cli sequence ablation stumpy-dtw
./dfap-cli graph ml explain ENT_NODE_00 ENT_NODE_01 graphsage
./dfap-cli graphml compare
./dfap-cli agent investigate 'Why was ENT_DFAP_4DOM_001 flagged?' CASE-DFAP-4DOMAIN-001
echo "RELEASE GATE PASS"
