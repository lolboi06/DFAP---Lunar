# Author: Sam Roger X
# Component: DFAP Graph ML Research & Ablation Layer
# Scope: Controlled Chronological Benchmark comparing GraphSAGE vs Temporal GNN/TGN

import copy
import time
import random
from dataclasses import dataclass, field
from typing import Dict, Any, List, Tuple, Optional
import numpy as np
from sklearn.metrics import (
    roc_auc_score,
    average_precision_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
)

import torch
import torch.nn as nn

from dfap.graph_ml.models import GraphSAGEModel, TGNModel


@dataclass
class ModelInferenceState:
    """Retained model state for deterministic on-demand link prediction without fabrication."""
    model_name: str
    model: nn.Module
    seed: int
    node_names: List[str]
    node_to_idx: Dict[str, int]
    node_features: torch.Tensor
    edge_index: Optional[torch.Tensor] = None
    memory_snapshot: Optional[torch.Tensor] = None
    temporal_context: str = ""
    ordering_basis: str = ""
    temporal_cutoff: float = 0.0
    training_range: Tuple[float, float] = (0.0, 0.0)
    validation_range: Tuple[float, float] = (0.0, 0.0)
    model_config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PredictionRecord:
    model_name: str
    event_id: str
    source_id: str
    target_id: str
    prediction_probability: float
    true_label: int
    temporal_context: str
    ordering_basis: str
    prediction_status: str = "PREDICTED"
    evidence_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "event_id": self.event_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "prediction_probability": round(self.prediction_probability, 4),
            "true_label": self.true_label,
            "temporal_context": self.temporal_context,
            "ordering_basis": self.ordering_basis,
            "prediction_status": self.prediction_status,
            "evidence_refs": self.evidence_refs,
            "disclaimer": "Model-predicted relationship only; NOT observed evidence, identity proof, or guilt."
        }


@dataclass
class BenchmarkResult:
    model_name: str
    auroc: float
    pr_auc: float
    precision: float
    recall: float
    f1: float
    fpr: float
    latency_ms: float
    train_runtime_sec: float
    test_samples: int
    predictions: List[PredictionRecord] = field(default_factory=list)
    inference_state: Optional[ModelInferenceState] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "auroc": round(self.auroc, 4),
            "pr_auc": round(self.pr_auc, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "fpr": round(self.fpr, 4),
            "latency_ms": round(self.latency_ms, 3),
            "train_runtime_sec": round(self.train_runtime_sec, 3),
            "test_samples": self.test_samples,
            "sample_predictions": [p.to_dict() for p in self.predictions[:5]],
        }


class GraphMLAblationBenchmark:
    """
    Controlled chronological benchmark comparing static GraphSAGE vs dynamic TGN.
    Evaluates strictly on chronological train/validation/test partitions with zero future leakage.
    """

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.graphsage_inference_state: Optional[ModelInferenceState] = None
        self.tgn_inference_state: Optional[ModelInferenceState] = None
        self._set_seed(seed)

    def _set_seed(self, seed: int):
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)

    def generate_synthetic_temporal_dataset(self) -> Dict[str, Any]:
        """
        Generates a synthetic dynamic graph dataset representing DFAP cross-domain entities
        with inherent sequential dependency and temporal order sensitivity.
        """
        self._set_seed(self.seed)
        num_nodes = 16
        node_names = [f"ENT_NODE_{i:02d}" for i in range(num_nodes)]
        node_to_idx = {name: i for i, name in enumerate(node_names)}

        # Node initial features (8-dim: domain one-hot + static baseline attributes)
        node_features = np.zeros((num_nodes, 8), dtype=np.float32)
        for i in range(num_nodes):
            domain_idx = i % 4
            node_features[i, domain_idx] = 1.0
            node_features[i, 4] = (i + 1) / float(num_nodes)
            node_features[i, 5] = ((i * 7) % 11) / 10.0
            node_features[i, 6] = np.sin(i * 0.5)
            node_features[i, 7] = np.cos(i * 0.5)

        # Generate temporal events across continuous timeline [100.0, 500.0]
        # Inherent sequential structure:
        # Pattern 1: Ordered relay 0 -> 1 -> 2 -> 3 (temporal sequence matters)
        # Pattern 2: Periodic burst between 4 and 5
        # Pattern 3: Hub interactions with nodes 6..15
        events: List[Dict[str, Any]] = []
        event_counter = 0

        # Timeline increments
        t = 100.0
        while t <= 500.0:
            # Pattern 1: Sequential cascade (0 -> 1, then 1 -> 2, then 2 -> 3)
            # Order is strictly chronological: 0->1 at t, 1->2 at t+4, 2->3 at t+8
            events.append({
                "event_id": f"EVT_BENCH_{event_counter:04d}",
                "src": "ENT_NODE_00",
                "dst": "ENT_NODE_01",
                "src_idx": 0,
                "dst_idx": 1,
                "t": t,
                "msg": np.array([0.9, 0.1, 0.5, 0.2, 0.0, 0.0, 0.1, 0.8], dtype=np.float32)
            })
            event_counter += 1

            events.append({
                "event_id": f"EVT_BENCH_{event_counter:04d}",
                "src": "ENT_NODE_01",
                "dst": "ENT_NODE_02",
                "src_idx": 1,
                "dst_idx": 2,
                "t": t + 4.0,
                "msg": np.array([0.8, 0.2, 0.4, 0.3, 0.1, 0.0, 0.2, 0.7], dtype=np.float32)
            })
            event_counter += 1

            events.append({
                "event_id": f"EVT_BENCH_{event_counter:04d}",
                "src": "ENT_NODE_02",
                "dst": "ENT_NODE_03",
                "src_idx": 2,
                "dst_idx": 3,
                "t": t + 8.0,
                "msg": np.array([0.7, 0.3, 0.6, 0.1, 0.0, 0.1, 0.3, 0.6], dtype=np.float32)
            })
            event_counter += 1

            # Pattern 2: Reciprocal burst between 4 and 5
            events.append({
                "event_id": f"EVT_BENCH_{event_counter:04d}",
                "src": "ENT_NODE_04",
                "dst": "ENT_NODE_05",
                "src_idx": 4,
                "dst_idx": 5,
                "t": t + 12.0,
                "msg": np.array([0.4, 0.6, 0.2, 0.7, 0.1, 0.2, 0.0, 0.4], dtype=np.float32)
            })
            event_counter += 1

            # Pattern 3: Sparse background communication with changing hubs
            hub_src = 6 + (int(t / 50.0) % 5)
            hub_dst = 11 + (int(t / 30.0) % 5)
            events.append({
                "event_id": f"EVT_BENCH_{event_counter:04d}",
                "src": node_names[hub_src],
                "dst": node_names[hub_dst],
                "src_idx": hub_src,
                "dst_idx": hub_dst,
                "t": t + 18.0,
                "msg": np.array([0.2, 0.2, 0.8, 0.1, 0.3, 0.1, 0.4, 0.2], dtype=np.float32)
            })
            event_counter += 1

            t += 25.0

        # Sort all events chronologically
        events.sort(key=lambda e: e["t"])

        # Strict chronological split:
        # TRAIN: t < 340.0 (~60%)
        # VAL:   340.0 <= t < 420.0 (~20%)
        # TEST:  t >= 420.0 (~20%)
        t_val_start = 340.0
        t_test_start = 420.0

        train_events = [e for e in events if e["t"] < t_val_start]
        val_events = [e for e in events if t_val_start <= e["t"] < t_test_start]
        test_events = [e for e in events if e["t"] >= t_test_start]

        # Generate negative samples for val and test
        # Negative sample is a non-occurring interaction at that specific timestamp
        def make_eval_pairs(pos_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            eval_items = []
            for pe in pos_events:
                # Positive item
                eval_items.append({
                    "event_id": pe["event_id"],
                    "src": pe["src"],
                    "dst": pe["dst"],
                    "src_idx": pe["src_idx"],
                    "dst_idx": pe["dst_idx"],
                    "t": pe["t"],
                    "msg": pe["msg"],
                    "label": 1
                })
                # Negative sample: randomly select dst_neg != pe["dst_idx"] that wasn't interacting
                neg_dst_idx = (pe["dst_idx"] + random.randint(1, num_nodes - 1)) % num_nodes
                if neg_dst_idx == pe["src_idx"]:
                    neg_dst_idx = (neg_dst_idx + 1) % num_nodes
                eval_items.append({
                    "event_id": f"NEG_{pe['event_id']}",
                    "src": pe["src"],
                    "dst": node_names[neg_dst_idx],
                    "src_idx": pe["src_idx"],
                    "dst_idx": neg_dst_idx,
                    "t": pe["t"],
                    "msg": np.zeros(8, dtype=np.float32),
                    "label": 0
                })
            return eval_items

        val_eval_items = make_eval_pairs(val_events)
        test_eval_items = make_eval_pairs(test_events)

        return {
            "num_nodes": num_nodes,
            "node_names": node_names,
            "node_to_idx": node_to_idx,
            "node_features": node_features,
            "train_events": train_events,
            "val_events": val_events,
            "test_events": test_events,
            "val_eval_items": val_eval_items,
            "test_eval_items": test_eval_items,
            "temporal_split": {
                "train_range": (float(min(e["t"] for e in train_events)), float(max(e["t"] for e in train_events))),
                "val_range": (float(min(e["t"] for e in val_events)), float(max(e["t"] for e in val_events))),
                "test_range": (float(min(e["t"] for e in test_events)), float(max(e["t"] for e in test_events))),
            }
        }

    def verify_chronological_integrity(self, dataset: Dict[str, Any]) -> bool:
        """Verifies strictly that train < validation < test and no timestamps overlap."""
        t_split = dataset["temporal_split"]
        train_max = t_split["train_range"][1]
        val_min = t_split["val_range"][0]
        val_max = t_split["val_range"][1]
        test_min = t_split["test_range"][0]
        assert train_max < val_min, f"Chronological leak: train_max ({train_max}) >= val_min ({val_min})"
        assert val_max < test_min, f"Chronological leak: val_max ({val_max}) >= test_min ({test_min})"
        return True

    def train_and_evaluate_graphsage(self, dataset: Dict[str, Any], epochs: int = 40) -> BenchmarkResult:
        """Trains and evaluates static GraphSAGE baseline strictly up to train/test time boundaries."""
        self._set_seed(self.seed)
        start_train_time = time.time()

        num_nodes = dataset["num_nodes"]
        x = torch.from_numpy(dataset["node_features"])
        train_events = dataset["train_events"]

        # Build static training graph edge index from training events only
        train_src = [e["src_idx"] for e in train_events]
        train_dst = [e["dst_idx"] for e in train_events]
        # Undirected static edges for message passing
        edge_index = torch.tensor([train_src + train_dst, train_dst + train_src], dtype=torch.long)

        model = GraphSAGEModel(in_channels=8, hidden_channels=32, out_channels=16)
        optimizer = torch.optim.Adam(model.parameters(), lr=0.01, weight_decay=1e-4)
        criterion = nn.BCELoss()

        # Training loop
        model.train()
        for epoch in range(epochs):
            optimizer.zero_grad()
            pos_src = torch.tensor([e["src_idx"] for e in train_events], dtype=torch.long)
            pos_dst = torch.tensor([e["dst_idx"] for e in train_events], dtype=torch.long)
            pos_prob = model(x, edge_index, pos_src, pos_dst)
            pos_loss = criterion(pos_prob, torch.ones_like(pos_prob))

            # Sample negative pairs
            neg_dst = torch.randint(0, num_nodes, (len(train_events),), dtype=torch.long)
            neg_prob = model(x, edge_index, pos_src, neg_dst)
            neg_loss = criterion(neg_prob, torch.zeros_like(neg_prob))

            loss = pos_loss + neg_loss
            loss.backward()
            optimizer.step()

        train_runtime = time.time() - start_train_time

        # Test evaluation
        model.eval()
        test_items = dataset["test_eval_items"]
        y_true = []
        y_prob = []
        predictions: List[PredictionRecord] = []

        start_eval_time = time.time()
        with torch.no_grad():
            for item in test_items:
                src_t = torch.tensor([item["src_idx"]], dtype=torch.long)
                dst_t = torch.tensor([item["dst_idx"]], dtype=torch.long)
                prob = float(model(x, edge_index, src_t, dst_t)[0])
                y_prob.append(prob)
                y_true.append(item["label"])

                rec = PredictionRecord(
                    model_name="GraphSAGE",
                    event_id=item["event_id"],
                    source_id=item["src"],
                    target_id=item["dst"],
                    prediction_probability=prob,
                    true_label=item["label"],
                    temporal_context="STATIC_TOPOLOGY_UP_TO_TRAIN_CUTOFF",
                    ordering_basis="INDUCTIVE_NEIGHBORHOOD_AGGREGATION",
                    prediction_status="PREDICTED",
                    evidence_refs=[]
                )
                predictions.append(rec)

        eval_elapsed = time.time() - start_eval_time
        latency_ms = (eval_elapsed / len(test_items)) * 1000.0 if test_items else 0.0

        y_true_arr = np.array(y_true)
        y_prob_arr = np.array(y_prob)
        y_pred_binary = (y_prob_arr >= 0.5).astype(int)

        auroc = float(roc_auc_score(y_true_arr, y_prob_arr))
        pr_auc = float(average_precision_score(y_true_arr, y_prob_arr))
        prec = float(precision_score(y_true_arr, y_pred_binary, zero_division=0))
        rec = float(recall_score(y_true_arr, y_pred_binary, zero_division=0))
        f1 = float(f1_score(y_true_arr, y_pred_binary, zero_division=0))
        tn, fp, fn, tp = confusion_matrix(y_true_arr, y_pred_binary).ravel()
        fpr = float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0

        inf_sage_model = GraphSAGEModel(in_channels=8, hidden_channels=32, out_channels=16)
        inf_sage_model.load_state_dict(model.state_dict())
        inf_sage_model.eval()
        self.graphsage_inference_state = ModelInferenceState(
            model_name="GraphSAGE",
            model=inf_sage_model,
            seed=self.seed,
            node_names=dataset["node_names"],
            node_to_idx=dataset["node_to_idx"],
            node_features=x.clone(),
            edge_index=edge_index.clone(),
            temporal_context="STATIC_TOPOLOGY_UP_TO_TRAIN_CUTOFF",
            ordering_basis="INDUCTIVE_NEIGHBORHOOD_AGGREGATION",
            temporal_cutoff=float(dataset["temporal_split"]["train_range"][1]),
            training_range=dataset["temporal_split"]["train_range"],
            validation_range=dataset["temporal_split"]["val_range"],
            model_config={"in_channels": 8, "hidden_channels": 32, "out_channels": 16, "dropout": 0.1}
        )

        return BenchmarkResult(
            model_name="GraphSAGE",
            auroc=auroc,
            pr_auc=pr_auc,
            precision=prec,
            recall=rec,
            f1=f1,
            fpr=fpr,
            latency_ms=latency_ms,
            train_runtime_sec=train_runtime,
            test_samples=len(test_items),
            predictions=predictions,
            inference_state=self.graphsage_inference_state
        )

    def train_and_evaluate_tgn(self, dataset: Dict[str, Any], epochs: int = 40) -> BenchmarkResult:
        """Trains and evaluates continuous-time TGN with dynamic memory state updates."""
        self._set_seed(self.seed)
        start_train_time = time.time()

        num_nodes = dataset["num_nodes"]
        x = torch.from_numpy(dataset["node_features"])
        train_events = dataset["train_events"]

        model = TGNModel(
            num_nodes=num_nodes,
            in_channels=8,
            raw_msg_dim=8,
            memory_dim=32,
            time_dim=16,
            out_channels=16
        )
        optimizer = torch.optim.Adam(model.parameters(), lr=0.01, weight_decay=1e-4)
        criterion = nn.BCELoss()

        # Sequential training loop over continuous time events
        for epoch in range(epochs):
            model.train()
            model.reset_state()
            optimizer.zero_grad()

            epoch_loss = 0.0
            last_t = 100.0

            # Step sequentially through chronological events
            for e in train_events:
                model.detach()
                src = torch.tensor([e["src_idx"]], dtype=torch.long)
                dst = torch.tensor([e["dst_idx"]], dtype=torch.long)
                t_val = torch.tensor([e["t"]], dtype=torch.float32)
                msg_val = torch.from_numpy(e["msg"]).unsqueeze(0)
                dt = torch.tensor([e["t"] - last_t], dtype=torch.float32)

                # Predict before updating memory to preserve causality
                pos_prob = model(x, src, dst, dt)
                pos_loss = criterion(pos_prob, torch.ones_like(pos_prob))

                # Negative sample
                neg_dst = torch.randint(0, num_nodes, (1,), dtype=torch.long)
                neg_prob = model(x, src, neg_dst, dt)
                neg_loss = criterion(neg_prob, torch.zeros_like(neg_prob))

                loss = pos_loss + neg_loss
                loss.backward()
                optimizer.step()
                optimizer.zero_grad()

                # Update memory with observed event
                model.update_memory(src, dst, t_val, msg_val)
                last_t = e["t"]

        train_runtime = time.time() - start_train_time

        # Test evaluation: Run forward from train history through validation, then evaluate on test
        model.eval()
        model.reset_state()

        # Step 1: Replay train events into memory
        with torch.no_grad():
            for e in train_events:
                src = torch.tensor([e["src_idx"]], dtype=torch.long)
                dst = torch.tensor([e["dst_idx"]], dtype=torch.long)
                t_val = torch.tensor([e["t"]], dtype=torch.float32)
                msg_val = torch.from_numpy(e["msg"]).unsqueeze(0)
                model.update_memory(src, dst, t_val, msg_val)

            # Step 2: Replay val events into memory
            for e in dataset["val_events"]:
                src = torch.tensor([e["src_idx"]], dtype=torch.long)
                dst = torch.tensor([e["dst_idx"]], dtype=torch.long)
                t_val = torch.tensor([e["t"]], dtype=torch.float32)
                msg_val = torch.from_numpy(e["msg"]).unsqueeze(0)
                model.update_memory(src, dst, t_val, msg_val)

        # Step 3: Evaluate on test events sequentially
        test_items = dataset["test_eval_items"]
        y_true = []
        y_prob = []
        predictions: List[PredictionRecord] = []

        start_eval_time = time.time()
        last_eval_t = dataset["val_events"][-1]["t"] if dataset["val_events"] else 340.0

        with torch.no_grad():
            for item in test_items:
                src_t = torch.tensor([item["src_idx"]], dtype=torch.long)
                dst_t = torch.tensor([item["dst_idx"]], dtype=torch.long)
                dt = torch.tensor([item["t"] - last_eval_t], dtype=torch.float32)

                # Query prediction strictly BEFORE updating memory
                prob = float(model(x, src_t, dst_t, dt)[0])
                y_prob.append(prob)
                y_true.append(item["label"])

                rec = PredictionRecord(
                    model_name="TGN",
                    event_id=item["event_id"],
                    source_id=item["src"],
                    target_id=item["dst"],
                    prediction_probability=prob,
                    true_label=item["label"],
                    temporal_context="DYNAMIC_CONTINUOUS_TIME_MEMORY_STATE",
                    ordering_basis="SEQUENTIAL_TEMPORAL_MEMORY_GRU",
                    prediction_status="PREDICTED",
                    evidence_refs=[]
                )
                predictions.append(rec)

                # If it's a positive ground-truth event, update memory sequentially for subsequent steps
                if item["label"] == 1:
                    t_val = torch.tensor([item["t"]], dtype=torch.float32)
                    msg_val = torch.from_numpy(item["msg"]).unsqueeze(0)
                    model.update_memory(src_t, dst_t, t_val, msg_val)
                    last_eval_t = item["t"]

        eval_elapsed = time.time() - start_eval_time
        latency_ms = (eval_elapsed / len(test_items)) * 1000.0 if test_items else 0.0

        y_true_arr = np.array(y_true)
        y_prob_arr = np.array(y_prob)
        y_pred_binary = (y_prob_arr >= 0.5).astype(int)

        auroc = float(roc_auc_score(y_true_arr, y_prob_arr))
        pr_auc = float(average_precision_score(y_true_arr, y_prob_arr))
        prec = float(precision_score(y_true_arr, y_pred_binary, zero_division=0))
        rec = float(recall_score(y_true_arr, y_pred_binary, zero_division=0))
        f1 = float(f1_score(y_true_arr, y_pred_binary, zero_division=0))
        tn, fp, fn, tp = confusion_matrix(y_true_arr, y_pred_binary).ravel()
        fpr = float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0

        # Prepare retained inference model with memory state up to training cutoff
        inf_tgn = TGNModel(
            num_nodes=num_nodes,
            in_channels=8,
            raw_msg_dim=8,
            memory_dim=32,
            time_dim=16,
            out_channels=16
        )
        inf_tgn.load_state_dict(model.state_dict())
        inf_tgn.eval()
        inf_tgn.reset_state()
        with torch.no_grad():
            for e in train_events:
                src = torch.tensor([e["src_idx"]], dtype=torch.long)
                dst = torch.tensor([e["dst_idx"]], dtype=torch.long)
                t_val = torch.tensor([e["t"]], dtype=torch.float32)
                msg_val = torch.from_numpy(e["msg"]).unsqueeze(0)
                inf_tgn.update_memory(src, dst, t_val, msg_val)
            # Flush unaggregated messages into the memory tensor so state is consolidated
            _ = inf_tgn.get_embeddings(x)

        mem_snapshot = inf_tgn.memory.memory.clone()
        self.tgn_inference_state = ModelInferenceState(
            model_name="TGN",
            model=inf_tgn,
            seed=self.seed,
            node_names=dataset["node_names"],
            node_to_idx=dataset["node_to_idx"],
            node_features=x.clone(),
            memory_snapshot=mem_snapshot,
            temporal_context="DYNAMIC_CONTINUOUS_TIME_MEMORY_AT_TRAIN_CUTOFF",
            ordering_basis="SEQUENTIAL_TEMPORAL_MEMORY_GRU",
            temporal_cutoff=float(dataset["temporal_split"]["train_range"][1]),
            training_range=dataset["temporal_split"]["train_range"],
            validation_range=dataset["temporal_split"]["val_range"],
            model_config={"num_nodes": num_nodes, "in_channels": 8, "raw_msg_dim": 8, "memory_dim": 32, "time_dim": 16, "out_channels": 16}
        )

        return BenchmarkResult(
            model_name="TGN",
            auroc=auroc,
            pr_auc=pr_auc,
            precision=prec,
            recall=rec,
            f1=f1,
            fpr=fpr,
            latency_ms=latency_ms,
            train_runtime_sec=train_runtime,
            test_samples=len(test_items),
            predictions=predictions,
            inference_state=self.tgn_inference_state
        )

    def run_comparison(self) -> Dict[str, Any]:
        """Executes the full ablation benchmark comparing GraphSAGE and TGN."""
        dataset = self.generate_synthetic_temporal_dataset()
        self.verify_chronological_integrity(dataset)

        res_sage = self.train_and_evaluate_graphsage(dataset)
        res_tgn = self.train_and_evaluate_tgn(dataset)

        # Build markdown ablation table
        header = f"{'Model':<12} {'AUROC':<8} {'PR-AUC':<8} {'Precision':<10} {'Recall':<8} {'F1':<8} {'FPR':<8} {'Latency (ms)':<14}"
        div = "-" * len(header)
        row_sage = f"{res_sage.model_name:<12} {res_sage.auroc:<8.4f} {res_sage.pr_auc:<8.4f} {res_sage.precision:<10.4f} {res_sage.recall:<8.4f} {res_sage.f1:<8.4f} {res_sage.fpr:<8.4f} {res_sage.latency_ms:<14.3f}"
        row_tgn = f"{res_tgn.model_name:<12} {res_tgn.auroc:<8.4f} {res_tgn.pr_auc:<8.4f} {res_tgn.precision:<10.4f} {res_tgn.recall:<8.4f} {res_tgn.f1:<8.4f} {res_tgn.fpr:<8.4f} {res_tgn.latency_ms:<14.3f}"
        table_str = f"{header}\n{div}\n{row_sage}\n{row_tgn}"

        return {
            "dataset_summary": {
                "num_nodes": dataset["num_nodes"],
                "total_train_events": len(dataset["train_events"]),
                "total_val_events": len(dataset["val_events"]),
                "total_test_events": len(dataset["test_events"]),
                "test_eval_samples": len(dataset["test_eval_items"]),
                "temporal_split": dataset["temporal_split"],
            },
            "models": {
                "GraphSAGE": res_sage.to_dict(),
                "TGN": res_tgn.to_dict(),
            },
            "table_markdown": table_str,
            "disclaimer": "CRITICAL RULE: Model predictions are marked PREDICTED and never enter M12 provenance as observed evidence."
        }
