# Author: Sam Roger X
# Component: DFAP Graph ML Research & Ablation Layer
# Scope: GraphMLService orchestrating GraphSAGE and TGN models, benchmarking, and predicted edge queries

from typing import Dict, Any, Optional, List
import torch

from dfap.graph_ml.benchmark import GraphMLAblationBenchmark, ModelInferenceState
from dfap.graph_ml.models import TGNModel


class GraphMLService:
    """
    Parallel ML scoring service for graph link prediction and temporal ablation benchmarking.
    CRITICAL RULE:
    Predictions are mathematical ML scores tagged with status PREDICTED.
    They never enter M4 as observed edges, never enter M12 provenance as observed evidence,
    and never alter M9 anomaly scores or M11 evidential conflict intelligence.
    Zero fabricated probabilities: only actual trained model inference is performed,
    and unknown entities strictly return UNAVAILABLE without pseudo-indexing.
    """

    def __init__(self, workspace_backend: Optional[Any] = None, default_seed: int = 42):
        self.backend = workspace_backend
        self.default_seed = default_seed
        self._cached_benchmark_result: Optional[Dict[str, Any]] = None
        self._benchmark_runner = GraphMLAblationBenchmark(seed=default_seed)

    def run_benchmark(self, seed: Optional[int] = None) -> Dict[str, Any]:
        """Runs the controlled chronological benchmark comparing GraphSAGE vs TGN."""
        runner = GraphMLAblationBenchmark(seed=seed if seed is not None else self.default_seed)
        result = runner.run_comparison()
        self._cached_benchmark_result = result
        self._benchmark_runner = runner
        return result

    def get_latest_benchmark(self) -> Dict[str, Any]:
        """Retrieves or executes the latest ablation benchmark comparison."""
        if self._cached_benchmark_result is None or self._benchmark_runner.graphsage_inference_state is None:
            return self.run_benchmark()
        return self._cached_benchmark_result

    def predict_relationship(
        self,
        source_id: str,
        target_id: str,
        timestamp: Optional[float] = None,
        model: str = "tgn"
    ) -> Dict[str, Any]:
        """
        Evaluates interaction probability between source and target nodes using actual trained models.
        Strictly returns UNAVAILABLE for identifiers outside the trained benchmark graph.
        Never uses hardcoded constants, never uses Python hash(), and never mutates memory state.
        """
        model_key = (model or "tgn").upper()
        is_sage = "SAGE" in model_key
        target_model_name = "GraphSAGE" if is_sage else "TGN"

        # Ensure benchmark has executed and retained model state is available
        _ = self.get_latest_benchmark()

        inf_state = (
            self._benchmark_runner.graphsage_inference_state
            if is_sage
            else self._benchmark_runner.tgn_inference_state
        )

        if inf_state is None:
            self.run_benchmark()
            inf_state = (
                self._benchmark_runner.graphsage_inference_state
                if is_sage
                else self._benchmark_runner.tgn_inference_state
            )

        src_clean = source_id.strip() if source_id else ""
        dst_clean = target_id.strip() if target_id else ""

        # Validate presence in trained benchmark graph (zero fake indexing or hash fallbacks)
        node_to_idx = inf_state.node_to_idx
        if not src_clean or not dst_clean or src_clean not in node_to_idx or dst_clean not in node_to_idx:
            missing_parts = []
            if not src_clean or src_clean not in node_to_idx:
                missing_parts.append(f"source '{src_clean}'")
            if not dst_clean or dst_clean not in node_to_idx:
                missing_parts.append(f"target '{dst_clean}'")
            return {
                "status": "UNAVAILABLE",
                "prediction_status": "UNAVAILABLE",
                "model_name": target_model_name,
                "source_id": src_clean,
                "target_id": dst_clean,
                "prediction_probability": None,
                "prediction_type": "MODEL_PREDICTED_RELATIONSHIP",
                "evidence_refs": [],
                "reason": f"Identifier ({', '.join(missing_parts)}) is outside the trained benchmark graph.",
                "disclaimer": "No model prediction was produced."
            }

        src_idx = node_to_idx[src_clean]
        dst_idx = node_to_idx[dst_clean]

        src_tensor = torch.tensor([src_idx], dtype=torch.long)
        dst_tensor = torch.tensor([dst_idx], dtype=torch.long)
        x = inf_state.node_features

        if is_sage:
            # Static GraphSAGE: forward inference on training-cutoff topology only
            edge_index = inf_state.edge_index
            trained_model = inf_state.model
            trained_model.eval()
            with torch.no_grad():
                raw_prob = float(trained_model(x, edge_index, src_tensor, dst_tensor)[0])

            context_desc = inf_state.temporal_context
            basis_desc = inf_state.ordering_basis
            cutoff_val = inf_state.temporal_cutoff
        else:
            # Dynamic TGN: clone evaluation instance with memory snapshot to guarantee zero memory mutation
            pred_model = TGNModel(
                num_nodes=inf_state.model.num_nodes,
                in_channels=inf_state.model.in_channels,
                raw_msg_dim=8,
                memory_dim=inf_state.model.memory_dim,
                time_dim=16,
                out_channels=16
            )
            pred_model.load_state_dict(inf_state.model.state_dict())
            pred_model.eval()
            if inf_state.memory_snapshot is not None:
                pred_model.memory.memory.copy_(inf_state.memory_snapshot)

            if timestamp is not None:
                dt_val = float(timestamp) - inf_state.temporal_cutoff
                dt_tensor = torch.tensor([[dt_val]], dtype=torch.float32)
                context_desc = f"{inf_state.temporal_context} (timestamp={timestamp})"
            else:
                dt_tensor = torch.zeros((1, 1), dtype=torch.float32)
                context_desc = f"{inf_state.temporal_context} (cutoff={inf_state.temporal_cutoff})"

            basis_desc = inf_state.ordering_basis
            cutoff_val = inf_state.temporal_cutoff

            with torch.no_grad():
                raw_prob = float(pred_model(x, src_tensor, dst_tensor, dt_tensor)[0])

        prob = round(raw_prob, 4)

        return {
            "status": "PREDICTED",
            "prediction_status": "PREDICTED",
            "model_name": target_model_name,
            "source_id": src_clean,
            "target_id": dst_clean,
            "prediction_probability": prob,
            "prediction_type": "MODEL_PREDICTED_RELATIONSHIP",
            "temporal_context": context_desc,
            "ordering_basis": basis_desc,
            "temporal_cutoff": cutoff_val,
            "evidence_refs": [],
            "timestamp": timestamp,
            "disclaimer": "This is a mathematical model-predicted relationship only; NOT confirmed observation, NOT forensic evidence, and NOT proof of guilt."
        }

    def explain_prediction(
        self,
        source_id: str,
        target_id: str,
        timestamp: Optional[float] = None,
        model: str = "graphsage"
    ) -> Dict[str, Any]:
        """
        Generates on-demand GNN explanation for predicted relationship between source_id and target_id.
        Derives influential nodes, edges, and features from the actual trained model.
        """
        from dfap.graph_ml.explainer import GNNExplanationService
        explainer = GNNExplanationService(self)
        return explainer.explain_prediction(
            source_id=source_id,
            target_id=target_id,
            timestamp=timestamp,
            model=model
        )

