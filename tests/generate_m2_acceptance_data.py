# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
import os
import pandas as pd
import duckdb

def generate_fixtures(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    
    events = [
        # CDR
        {"event_id": "EVT1", "timestamp": "2026-09-01T10:00:00+00:00", "actor_id": "PHONE1", "target_id": "PHONE2", "event_type": "CALL", "source_domain": "CDR", "sha256_hash": "hash1", "attributes": '{"duration": 120}'},
        {"event_id": "EVT2", "timestamp": "2026-09-01T10:05:00+00:00", "actor_id": "PHONE2", "target_id": "PHONE1", "event_type": "CALL", "source_domain": "CDR", "sha256_hash": "hash2", "attributes": '{"duration": 300}'},
        {"event_id": "EVT_NIGHT", "timestamp": "2026-09-01T23:00:00+00:00", "actor_id": "PHONE1", "target_id": "PHONE3", "event_type": "CALL", "source_domain": "CDR", "sha256_hash": "hash3", "attributes": '{"duration": 60}'},
        
        # IPDR
        {"event_id": "EVT3", "timestamp": "2026-09-01T10:10:00+00:00", "actor_id": "IP1", "target_id": "IP2", "event_type": "IP_SESSION", "source_domain": "IPDR", "sha256_hash": "hash4", "attributes": '{"bytes_in": 100, "bytes_out": 200, "dest_ip": "10.0.0.1", "protocol": "TCP", "dest_port": 443}'},
        {"event_id": "EVT4", "timestamp": "2026-09-01T10:15:00+00:00", "actor_id": "IP3", "target_id": "IP1", "event_type": "IP_SESSION", "source_domain": "IPDR", "sha256_hash": "hash5", "attributes": '{"bytes_in": 500, "bytes_out": 50, "dest_ip": "192.168.1.1", "protocol": "UDP", "dest_port": 53}'},
        
        # BANK
        {"event_id": "EVT5", "timestamp": "2026-09-01T10:20:00+00:00", "actor_id": "ACC1", "target_id": "ACC2", "event_type": "TRANSACTION", "source_domain": "BANK", "sha256_hash": "hash6", "attributes": '{"amount": 1000.0}'},
        {"event_id": "EVT6", "timestamp": "2026-09-01T10:25:00+00:00", "actor_id": "ACC2", "target_id": "ACC3", "event_type": "TRANSACTION", "source_domain": "BANK", "sha256_hash": "hash7", "attributes": '{"amount": 500.0}'},
        {"event_id": "EVT7", "timestamp": "2026-09-01T10:30:00+00:00", "actor_id": "ACC1", "target_id": "ACC2", "event_type": "TRANSACTION", "source_domain": "BANK", "sha256_hash": "hash8", "attributes": '{"amount": 2000.0}'},
        
        # SOCIAL
        {"event_id": "EVT8", "timestamp": "2026-09-01T10:35:00+00:00", "actor_id": "SOC1", "target_id": "SOC2", "event_type": "SOCIAL", "source_domain": "SOCIAL", "sha256_hash": "hash9", "attributes": '{"action": "reply"}'},
        
        # FINANCIAL GRAPH DATASET (A, B, C, D)
        {"event_id": "EVT_AB", "timestamp": "2026-09-01T11:00:00+00:00", "actor_id": "A", "target_id": "B", "event_type": "TRANSACTION", "source_domain": "BANK", "sha256_hash": "h_ab", "attributes": '{"amount": 100.0}'},
        {"event_id": "EVT_AC", "timestamp": "2026-09-01T11:05:00+00:00", "actor_id": "A", "target_id": "C", "event_type": "TRANSACTION", "source_domain": "BANK", "sha256_hash": "h_ac", "attributes": '{"amount": 50.0}'},
        {"event_id": "EVT_BC", "timestamp": "2026-09-01T11:10:00+00:00", "actor_id": "B", "target_id": "C", "event_type": "TRANSACTION", "source_domain": "BANK", "sha256_hash": "h_bc", "attributes": '{"amount": 25.0}'},
        {"event_id": "EVT_CD", "timestamp": "2026-09-01T11:15:00+00:00", "actor_id": "C", "target_id": "D", "event_type": "TRANSACTION", "source_domain": "BANK", "sha256_hash": "h_cd", "attributes": '{"amount": 10.0}'}
    ]
    
    entities = [
        {"canonical_entity_id": "ENT1", "raw_identifier": "PHONE1", "identifier_type": "PHONE", "match_confidence": 1.0, "match_method": "EXACT", "match_status": "CONFIRMED", "evidence": "{}"},
        {"canonical_entity_id": "ENT2", "raw_identifier": "PHONE2", "identifier_type": "PHONE", "match_confidence": 1.0, "match_method": "EXACT", "match_status": "CONFIRMED", "evidence": "{}"},
        {"canonical_entity_id": "ENT3", "raw_identifier": "PHONE3", "identifier_type": "PHONE", "match_confidence": 1.0, "match_method": "EXACT", "match_status": "CONFIRMED", "evidence": "{}"},
        {"canonical_entity_id": "ENT4", "raw_identifier": "IP1", "identifier_type": "IP", "match_confidence": 1.0, "match_method": "EXACT", "match_status": "CONFIRMED", "evidence": "{}"},
        {"canonical_entity_id": "ENT5", "raw_identifier": "IP2", "identifier_type": "IP", "match_confidence": 1.0, "match_method": "EXACT", "match_status": "CONFIRMED", "evidence": "{}"},
        {"canonical_entity_id": "ENT6", "raw_identifier": "IP3", "identifier_type": "IP", "match_confidence": 1.0, "match_method": "EXACT", "match_status": "CONFIRMED", "evidence": "{}"},
        {"canonical_entity_id": "ENT7", "raw_identifier": "ACC1", "identifier_type": "ACCOUNT", "match_confidence": 1.0, "match_method": "EXACT", "match_status": "CONFIRMED", "evidence": "{}"},
        {"canonical_entity_id": "ENT8", "raw_identifier": "ACC2", "identifier_type": "ACCOUNT", "match_confidence": 1.0, "match_method": "EXACT", "match_status": "CONFIRMED", "evidence": "{}"},
        {"canonical_entity_id": "ENT9", "raw_identifier": "ACC3", "identifier_type": "ACCOUNT", "match_confidence": 1.0, "match_method": "EXACT", "match_status": "CONFIRMED", "evidence": "{}"},
        {"canonical_entity_id": "ENT10", "raw_identifier": "SOC1", "identifier_type": "HANDLE", "match_confidence": 1.0, "match_method": "EXACT", "match_status": "CONFIRMED", "evidence": "{}"},
        {"canonical_entity_id": "ENT11", "raw_identifier": "SOC2", "identifier_type": "HANDLE", "match_confidence": 1.0, "match_method": "EXACT", "match_status": "CONFIRMED", "evidence": "{}"},
        {"canonical_entity_id": "ENT_A", "raw_identifier": "A", "identifier_type": "ACCOUNT", "match_confidence": 1.0, "match_method": "EXACT", "match_status": "CONFIRMED", "evidence": "{}"},
        {"canonical_entity_id": "ENT_B", "raw_identifier": "B", "identifier_type": "ACCOUNT", "match_confidence": 1.0, "match_method": "EXACT", "match_status": "CONFIRMED", "evidence": "{}"},
        {"canonical_entity_id": "ENT_C", "raw_identifier": "C", "identifier_type": "ACCOUNT", "match_confidence": 1.0, "match_method": "EXACT", "match_status": "CONFIRMED", "evidence": "{}"},
        {"canonical_entity_id": "ENT_D", "raw_identifier": "D", "identifier_type": "ACCOUNT", "match_confidence": 1.0, "match_method": "EXACT", "match_status": "CONFIRMED", "evidence": "{}"},
    ]
    
    events_df = pd.DataFrame(events)
    entities_df = pd.DataFrame(entities)
    
    events_df.to_parquet(os.path.join(output_dir, "canonical_events.parquet"))
    entities_df.to_parquet(os.path.join(output_dir, "resolved_entities.parquet"))
    
if __name__ == "__main__":
    generate_fixtures("/home/samrogerx/Documents/DFAP/tests/fixtures")
