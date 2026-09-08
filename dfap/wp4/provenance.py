# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research
# Scope: M12 W3C PROV-O compliant provenance builder with deterministic URIs

import json
from typing import Dict, List, Any, Optional, Set, Tuple


class W3CProvenanceBuilder:
    """
    Constructs deterministic W3C PROV-O compliant JSON-LD / JSON representation
    for DFAP entities, activities, agents, and relations.
    
    Guarantees:
    - Zero random UUIDs.
    - Deterministic URI schemas.
    - Pure functional mapping from static inputs.
    - Standard PROV-O predicates: wasDerivedFrom, wasGeneratedBy, used, wasAssociatedWith, wasAttributedTo.
    """

    PROV_NS = "http://www.w3.org/ns/prov#"
    DFAP_NS = "urn:dfap:"

    @staticmethod
    def entity_uri(entity_type: str, entity_id: str) -> str:
        return f"{W3CProvenanceBuilder.DFAP_NS}entity:{entity_type.lower()}:{str(entity_id).strip()}"

    @staticmethod
    def activity_uri(activity_type: str, activity_id: str) -> str:
        return f"{W3CProvenanceBuilder.DFAP_NS}activity:{activity_type.lower()}:{str(activity_id).strip()}"

    @staticmethod
    def agent_uri(agent_type: str, agent_id: str) -> str:
        return f"{W3CProvenanceBuilder.DFAP_NS}agent:{agent_type.lower()}:{str(agent_id).strip()}"

    @classmethod
    def build_finding_prov_document(
        cls,
        finding_id: str,
        entity_id: str,
        event_records: List[Dict[str, Any]],
        feature_names: List[str],
        anomaly_type: str,
        created_at: str,
        model_version: str = "M11_DS_FUSION_v1.0"
    ) -> Dict[str, Any]:
        """
        Builds a complete, deterministic PROV-O graph document for a given finding and its supporting evidence.
        """
        entities: Dict[str, Dict[str, Any]] = {}
        activities: Dict[str, Dict[str, Any]] = {}
        agents: Dict[str, Dict[str, Any]] = {}
        relations: List[Dict[str, Any]] = []

        # 1. System Agent
        software_agent_id = cls.agent_uri("software", "DFAP_Analytics_Engine_v1")
        agents[software_agent_id] = {
            "@type": "prov:SoftwareAgent",
            "prov:label": "DFAP Analytics Engine v1.0",
            "dfap:modelVersion": model_version
        }

        # 2. Finding Entity
        finding_uri = cls.entity_uri("finding", finding_id)
        entities[finding_uri] = {
            "@type": "prov:Entity",
            "prov:label": f"DFAP Finding {finding_id}",
            "dfap:findingType": anomaly_type,
            "dfap:targetEntity": entity_id,
            "prov:generatedAtTime": created_at
        }

        # 3. Fusion Activity
        fusion_act_id = cls.activity_uri("fusion", finding_id)
        activities[fusion_act_id] = {
            "@type": "prov:Activity",
            "prov:label": "Cross-Domain Evidential Fusion (M11)",
            "prov:startedAtTime": created_at,
            "prov:endedAtTime": created_at
        }
        relations.append({
            "@type": "prov:wasGeneratedBy",
            "prov:entity": finding_uri,
            "prov:activity": fusion_act_id
        })
        relations.append({
            "@type": "prov:wasAssociatedWith",
            "prov:activity": fusion_act_id,
            "prov:agent": software_agent_id
        })

        # 4. Feature Entities & Anomaly Engine Activity
        anomaly_act_id = cls.activity_uri("anomaly_engine", finding_id)
        activities[anomaly_act_id] = {
            "@type": "prov:Activity",
            "prov:label": "Behavioral Baseline & Anomaly Engine (M8-M10)",
            "prov:endedAtTime": created_at
        }
        relations.append({
            "@type": "prov:wasAssociatedWith",
            "prov:activity": anomaly_act_id,
            "prov:agent": software_agent_id
        })

        for feat in sorted(set(feature_names)):
            feat_uri = cls.entity_uri("feature", f"{feat}:{entity_id}")
            entities[feat_uri] = {
                "@type": "prov:Entity",
                "prov:label": f"Engine Feature: {feat}",
                "dfap:featureName": feat
            }
            # Fusion used feature
            relations.append({
                "@type": "prov:used",
                "prov:activity": fusion_act_id,
                "prov:entity": feat_uri
            })
            # Finding derived from feature
            relations.append({
                "@type": "prov:wasDerivedFrom",
                "prov:generatedEntity": finding_uri,
                "prov:usedEntity": feat_uri
            })
            # Anomaly engine generated feature
            relations.append({
                "@type": "prov:wasGeneratedBy",
                "prov:entity": feat_uri,
                "prov:activity": anomaly_act_id
            })

        # 5. Canonical Events & Raw Source Records
        for ev in sorted(event_records, key=lambda x: (x.get("timestamp", ""), x.get("event_id", ""))):
            ev_id = ev.get("event_id", "")
            if not ev_id:
                continue
            ev_uri = cls.entity_uri("canonical_event", ev_id)
            ev_hash = ev.get("sha256_hash", "")
            entities[ev_uri] = {
                "@type": "prov:Entity",
                "prov:label": f"Canonical Event {ev_id}",
                "dfap:eventType": ev.get("event_type", ""),
                "dfap:sourceDomain": ev.get("source_domain", ""),
                "dfap:timestamp": ev.get("timestamp", ""),
                "dfap:sha256Hash": ev_hash
            }

            # Anomaly Engine used Event
            relations.append({
                "@type": "prov:used",
                "prov:activity": anomaly_act_id,
                "prov:entity": ev_uri
            })

            # Ingestion Activity & Raw Record Entity
            src_file = ev.get("source_file", "unknown_source")
            src_idx = ev.get("source_row_index", 0)
            ingest_act_id = cls.activity_uri("ingestion", f"{src_file}:{src_idx}")
            activities[ingest_act_id] = {
                "@type": "prov:Activity",
                "prov:label": f"Ingestion & Validation of {src_file}",
                "dfap:sourceFile": src_file
            }
            relations.append({
                "@type": "prov:wasGeneratedBy",
                "prov:entity": ev_uri,
                "prov:activity": ingest_act_id
            })

            raw_rec_uri = cls.entity_uri("raw_source_record", f"{src_file}:{src_idx}")
            entities[raw_rec_uri] = {
                "@type": "prov:Entity",
                "prov:label": f"Raw Source Row {src_idx} from {src_file}",
                "dfap:sourceFile": src_file,
                "dfap:sourceRowIndex": src_idx
            }
            relations.append({
                "@type": "prov:used",
                "prov:activity": ingest_act_id,
                "prov:entity": raw_rec_uri
            })
            relations.append({
                "@type": "prov:wasDerivedFrom",
                "prov:generatedEntity": ev_uri,
                "prov:usedEntity": raw_rec_uri
            })

        # Return fully structured and sorted PROV-O document
        return {
            "@context": {
                "prov": cls.PROV_NS,
                "dfap": cls.DFAP_NS
            },
            "entities": {k: entities[k] for k in sorted(entities.keys())},
            "activities": {k: activities[k] for k in sorted(activities.keys())},
            "agents": {k: agents[k] for k in sorted(agents.keys())},
            "relations": sorted(relations, key=lambda x: (x.get("@type", ""), x.get("prov:entity", ""), x.get("prov:generatedEntity", ""), x.get("prov:activity", "")))
        }
