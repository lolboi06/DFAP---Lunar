# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research

import pandas as pd
import numpy as np
import json
from dfap.graph import DFAPGraphService
from datetime import datetime, timezone
from dateutil.parser import isoparse
from typing import List, Dict

class DomainAnalyticsService:
    def __init__(self, graph_service: DFAPGraphService):
        self.gs = graph_service
        self.g = self.gs.g
        
    def _create_feature_row(self, entity_id: str, name: str, val: float, window: str, src: str, refs: List[str]) -> Dict:
        return {
            'entity_id': entity_id,
            'feature_name': name,
            'feature_value': float(val) if val is not None else 0.0,
            'window': window,
            'source': src,
            'evidence_refs': list(set(refs))
        }

    def _get_entity_events(self, v_idx: int, domain: str, event_types: List[str] = None):
        events = []
        for e in self.g.incident(v_idx, mode="all"):
            edge = self.g.es[e]
            n_idx = edge.target if edge.source == v_idx else edge.source
            node = self.g.vs[n_idx]
            if node['node_type'] == 'Event' and node['source_domain'] == domain:
                if event_types is None or node['event_type'] in event_types:
                    events.append((node, edge))
        return events

    def m5_telecom_analytics(self, window: str = "ALL") -> pd.DataFrame:
        features = []
        for v in self.g.vs:
            if v['node_type'] not in ['Person', 'Phone', 'IP']: continue
            
            # CDR Features
            cdr_events = self._get_entity_events(v.index, 'CDR', ['CALL'])
            if cdr_events:
                refs = [ev['name'] for ev, _ in cdr_events]
                durations = []
                night_calls = 0
                contacts = set()
                inter_event = []
                last_time = None
                
                # Directed contacts for reciprocity
                directed_out = set()
                directed_in = set()
                
                for ev, edge in sorted(cdr_events, key=lambda x: x[0]['epoch_time']):
                    attrs = json.loads(ev['attributes']) if ev['attributes'] else {}
                    dur = float(attrs.get('duration', 0.0))
                    durations.append(dur)
                    
                    try:
                        dt = isoparse(ev['timestamp'])
                        if dt.hour >= 22 or dt.hour < 6:
                            night_calls += 1
                    except:
                        pass
                        
                    if last_time is not None:
                        inter_event.append(ev['epoch_time'] - last_time)
                    last_time = ev['epoch_time']
                    
                    # Find counterparty
                    for ev_edge_idx in self.g.incident(ev.index, mode="all"):
                        ev_edge = self.g.es[ev_edge_idx]
                        cp_idx = ev_edge.target if ev_edge.source == ev.index else ev_edge.source
                        if cp_idx != v.index:
                            cp_name = self.g.vs[cp_idx]['name']
                            contacts.add(cp_name)
                            if ev_edge['relationship_type'] == 'RECEIVES':
                                directed_out.add(cp_name)
                            elif ev_edge['relationship_type'] == 'CALLS':
                                directed_in.add(cp_name)
                                
                features.append(self._create_feature_row(v['name'], 'call_count', len(cdr_events), window, 'CDR', refs))
                features.append(self._create_feature_row(v['name'], 'unique_contacts', len(contacts), window, 'CDR', refs))
                features.append(self._create_feature_row(v['name'], 'mean_duration', np.mean(durations) if durations else 0.0, window, 'CDR', refs))
                features.append(self._create_feature_row(v['name'], 'max_duration', np.max(durations) if durations else 0.0, window, 'CDR', refs))
                features.append(self._create_feature_row(v['name'], 'night_call_ratio', night_calls/len(cdr_events), window, 'CDR', refs))
                
                mutual = len(directed_out.intersection(directed_in))
                total_directed = len(directed_out.union(directed_in))
                features.append(self._create_feature_row(v['name'], 'reciprocity', mutual/total_directed if total_directed > 0 else 0.0, window, 'CDR', refs))
                
                burstiness = 0.0
                if len(inter_event) > 1:
                    mu = np.mean(inter_event)
                    if mu > 0: burstiness = np.std(inter_event) / mu
                features.append(self._create_feature_row(v['name'], 'burstiness', burstiness, window, 'CDR', refs))
                
            # IPDR Features
            ipdr_events = self._get_entity_events(v.index, 'IPDR', ['IP_SESSION'])
            if ipdr_events:
                refs = [ev['name'] for ev, _ in ipdr_events]
                bytes_in = 0
                bytes_out = 0
                target_ips = set()
                protocols = set()
                ports = set()
                
                for ev, edge in ipdr_events:
                    attrs = json.loads(ev['attributes']) if ev['attributes'] else {}
                    bytes_in += int(attrs.get('bytes_in', 0))
                    bytes_out += int(attrs.get('bytes_out', 0))
                    if 'dest_ip' in attrs: target_ips.add(attrs['dest_ip'])
                    if 'protocol' in attrs: protocols.add(attrs['protocol'])
                    if 'dest_port' in attrs: ports.add(attrs['dest_port'])
                    
                features.append(self._create_feature_row(v['name'], 'session_count', len(ipdr_events), window, 'IPDR', refs))
                features.append(self._create_feature_row(v['name'], 'bytes_in', bytes_in, window, 'IPDR', refs))
                features.append(self._create_feature_row(v['name'], 'bytes_out', bytes_out, window, 'IPDR', refs))
                features.append(self._create_feature_row(v['name'], 'destination_diversity', len(target_ips), window, 'IPDR', refs))
                features.append(self._create_feature_row(v['name'], 'protocol_diversity', len(protocols), window, 'IPDR', refs))
                features.append(self._create_feature_row(v['name'], 'port_diversity', len(ports), window, 'IPDR', refs))

        return pd.DataFrame(features)

    def m6_financial_analytics(self, window: str = "ALL") -> pd.DataFrame:
        features = []
        for v in self.g.vs:
            if v['node_type'] not in ['Person', 'Account', 'Merchant']: continue
            bank_events = self._get_entity_events(v.index, 'BANK', ['TRANSACTION'])
            if not bank_events: continue
            
            refs = [ev['name'] for ev, _ in bank_events]
            amounts = []
            sent = 0.0
            received = 0.0
            counterparties = set()
            merchants = set()
            
            for ev, edge in bank_events:
                attrs = json.loads(ev['attributes']) if ev['attributes'] else {}
                if 'raw_source_attributes' in attrs:
                    attrs = attrs['raw_source_attributes']
                amt = float(attrs.get('amount', 0.0))
                amounts.append(amt)
                
                if edge['relationship_type'] == 'SENDS':
                    sent += amt
                elif edge['relationship_type'] == 'RECEIVES':
                    received += amt
                    
                for ev_edge_idx in self.g.incident(ev.index, mode="all"):
                    ev_edge = self.g.es[ev_edge_idx]
                    cp_idx = ev_edge.target if ev_edge.source == ev.index else ev_edge.source
                    if cp_idx != v.index:
                        cp_name = self.g.vs[cp_idx]['name']
                        counterparties.add(cp_name)
                        if self.g.vs[cp_idx]['node_type'] == 'Merchant':
                            merchants.add(cp_name)
                            
            features.append(self._create_feature_row(v['name'], 'transaction_count', len(bank_events), window, 'BANK', refs))
            features.append(self._create_feature_row(v['name'], 'transaction_velocity', sum(amounts), window, 'BANK', refs))
            features.append(self._create_feature_row(v['name'], 'mean_amount', np.mean(amounts), window, 'BANK', refs))
            features.append(self._create_feature_row(v['name'], 'median_amount', np.median(amounts), window, 'BANK', refs))
            
            # Median Absolute Deviation
            med = np.median(amounts)
            mad = np.median(np.abs(amounts - med))
            features.append(self._create_feature_row(v['name'], 'amount_deviation', mad, window, 'BANK', refs))
            
            features.append(self._create_feature_row(v['name'], 'unique_counterparties', len(counterparties), window, 'BANK', refs))
            features.append(self._create_feature_row(v['name'], 'merchant_diversity', len(merchants), window, 'BANK', refs))
            
            ratio = (received / sent) if sent > 0 else 999999.0
            features.append(self._create_feature_row(v['name'], 'inflow_outflow_ratio', ratio, window, 'BANK', refs))
            
        return pd.DataFrame(features)

    def m7_social_analytics(self, window: str = "ALL") -> pd.DataFrame:
        features = []
        for v in self.g.vs:
            if v['node_type'] not in ['Person', 'SocialAccount']: continue
            soc_events = self._get_entity_events(v.index, 'SOCIAL', ['SOCIAL'])
            if not soc_events: continue
            
            refs = [ev['name'] for ev, _ in soc_events]
            interactions = 0
            
            for ev, edge in soc_events:
                if edge['relationship_type'] == 'INTERACTED_WITH':
                    interactions += 1
                    
            features.append(self._create_feature_row(v['name'], 'activity_frequency', len(soc_events), window, 'SOCIAL', refs))
            features.append(self._create_feature_row(v['name'], 'interaction_count', interactions, window, 'SOCIAL', refs))
            # Topic shift / community membership default to missing (0.0) as text isn't provided
        return pd.DataFrame(features)

    def extract_graph_features(self, window: str = "ALL") -> pd.DataFrame:
        features = []
        
        # Precompute neighbors for shared counterparties
        neighbors = {}
        tx_neighbors = {}
        for v in self.g.vs:
            if v['node_type'] not in ['Person', 'Account', 'Phone', 'IP', 'Merchant', 'SocialAccount', 'HANDLE']: continue
            n_set = set()
            t_set = set()
            for e in self.g.incident(v.index, mode="all"):
                edge = self.g.es[e]
                ev_idx = edge.target if edge.source == v.index else edge.source
                ev_node = self.g.vs[ev_idx]
                if ev_node['node_type'] == 'Event':
                    # Get the other entity on this event
                    for e2 in self.g.incident(ev_idx, mode="all"):
                        edge2 = self.g.es[e2]
                        cp_idx = edge2.target if edge2.source == ev_idx else edge2.source
                        if cp_idx != v.index and self.g.vs[cp_idx]['node_type'] != 'Event':
                            cp_name = self.g.vs[cp_idx]['name']
                            n_set.add(cp_name)
                            if ev_node['event_type'] == 'TRANSACTION':
                                t_set.add(cp_name)
                else:
                    n_set.add(ev_node['name']) # For inferred edges directly between entities
            neighbors[v['name']] = n_set
            tx_neighbors[v['name']] = t_set

        for v in self.g.vs:
            if v['node_type'] not in ['Person', 'Account', 'Phone', 'IP', 'Merchant', 'SocialAccount', 'HANDLE']: continue
            
            name = v['name']
            
            # Evidence collection: collect event refs for all incidents
            refs = []
            for e in self.g.incident(v.index, mode="all"):
                ev_idx = self.g.es[e].target if self.g.es[e].source == v.index else self.g.es[e].source
                if self.g.vs[ev_idx]['node_type'] == 'Event':
                    refs.append(self.g.vs[ev_idx]['name'])
            refs = list(set(refs))
            
            # 1. degree
            deg = len(neighbors[name])
            features.append(self._create_feature_row(name, 'degree', deg, window, 'GRAPH', refs))
            
            # 2. max_shared_counterparties
            max_shared = 0
            n_v = neighbors[name]
            if len(n_v) > 0:
                for other_name, n_u in neighbors.items():
                    if other_name != name:
                        overlap = len(n_v.intersection(n_u))
                        if overlap > max_shared:
                            max_shared = overlap
            features.append(self._create_feature_row(name, 'shared_counterparties', max_shared, window, 'GRAPH', refs))
            
            # Financial specific features
            if v['node_type'] in ['Person', 'Account', 'Merchant']:
                tx_events = self._get_entity_events(v.index, 'BANK', ['TRANSACTION'])
                tx_refs = [ev['name'] for ev, _ in tx_events]
                
                # 3. weighted_degree
                w_deg = 0.0
                for ev, edge in tx_events:
                    attrs = json.loads(ev['attributes']) if ev['attributes'] else {}
                    if 'raw_source_attributes' in attrs:
                        attrs = attrs['raw_source_attributes']
                    amt = float(attrs.get('amount', 0.0))
                    w_deg += amt
                features.append(self._create_feature_row(name, 'weighted_degree', w_deg, window, 'GRAPH', tx_refs))
                
                # 4. reachable_counterparties_2hop (transaction_path_features)
                reachable = set()
                t_n_v = tx_neighbors[name]
                for n1 in t_n_v:
                    reachable.add(n1)
                    for n2 in tx_neighbors.get(n1, set()):
                        if n2 != name:
                            reachable.add(n2)
                features.append(self._create_feature_row(name, 'transaction_path_features', len(reachable), window, 'GRAPH', tx_refs))
                
        return pd.DataFrame(features)
