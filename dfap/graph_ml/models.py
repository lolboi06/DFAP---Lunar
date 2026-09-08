# Author: Sam Roger X
# Component: DFAP Graph ML Research & Ablation Layer
# Scope: GraphSAGE static baseline and Temporal Graph Network (TGN) architectures

import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="torch.jit")

from typing import Optional, Tuple, Dict, Any, List
import numpy as np

try:
    import torch
    import torch.nn as nn
    from torch_geometric.nn import SAGEConv
    from torch_geometric.nn.models.tgn import (
        TGNMemory,
        IdentityMessage,
        LastAggregator
    )
    PYG_AVAILABLE = True
except ImportError:
    PYG_AVAILABLE = False


class GraphSAGEModel(nn.Module if PYG_AVAILABLE else object):
    """
    Static GraphSAGE baseline model.
    Operates on static snapshots of graph connectivity. Aggregates neighbor features
    via inductive SAGEConv layers without temporal memory or interaction ordering awareness.
    """

    def __init__(
        self,
        in_channels: int,
        hidden_channels: int = 32,
        out_channels: int = 16,
        dropout: float = 0.1,
    ):
        if not PYG_AVAILABLE:
            raise ImportError("PyTorch and PyTorch Geometric are required for GraphSAGEModel.")
        super().__init__()
        self.conv1 = SAGEConv(in_channels, hidden_channels)
        self.conv2 = SAGEConv(hidden_channels, out_channels)
        self.dropout = nn.Dropout(dropout)
        self.link_pred = nn.Sequential(
            nn.Linear(2 * out_channels, hidden_channels),
            nn.ReLU(),
            nn.Linear(hidden_channels, 1),
            nn.Sigmoid(),
        )

    def encode(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        """Encodes node features into static embeddings."""
        if edge_index.numel() == 0:
            # Handle empty edge index gracefully
            return torch.zeros((x.size(0), self.conv2.out_channels), device=x.device)
        h = torch.relu(self.conv1(x, edge_index))
        h = self.dropout(h)
        z = self.conv2(h, edge_index)
        return z

    def forward(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        src: torch.Tensor,
        dst: torch.Tensor
    ) -> torch.Tensor:
        """Predicts probability of edge between src and dst from static graph representation."""
        z = self.encode(x, edge_index)
        edge_features = torch.cat([z[src], z[dst]], dim=-1)
        return self.link_pred(edge_features).squeeze(-1)


class TGNModel(nn.Module if PYG_AVAILABLE else object):
    """
    Continuous-Time Temporal Graph Network (TGN) architecture.
    Maintains a continuous-time dynamic memory state for every node updated upon sequential
    event arrival via TGNMemory. Retains historical interaction sequence, time intervals,
    and temporal dynamics that static GraphSAGE cannot represent.
    """

    def __init__(
        self,
        num_nodes: int,
        in_channels: int,
        raw_msg_dim: int = 8,
        memory_dim: int = 32,
        time_dim: int = 16,
        out_channels: int = 16,
    ):
        if not PYG_AVAILABLE:
            raise ImportError("PyTorch and PyTorch Geometric are required for TGNModel.")
        super().__init__()
        self.num_nodes = num_nodes
        self.memory_dim = memory_dim
        self.in_channels = in_channels

        self.memory = TGNMemory(
            num_nodes=num_nodes,
            raw_msg_dim=raw_msg_dim,
            memory_dim=memory_dim,
            time_dim=time_dim,
            message_module=IdentityMessage(
                raw_msg_dim=raw_msg_dim,
                memory_dim=memory_dim,
                time_dim=time_dim
            ),
            aggregator_module=LastAggregator(),
        )

        self.node_proj = nn.Linear(in_channels + memory_dim, out_channels)
        self.link_pred = nn.Sequential(
            nn.Linear(2 * out_channels + 1, memory_dim),
            nn.ReLU(),
            nn.Linear(memory_dim, 1),
            nn.Sigmoid(),
        )

    def reset_state(self):
        """Resets dynamic memory to initial zero states."""
        self.memory.reset_state()

    def detach(self):
        """Detaches dynamic memory from autograd graph for truncated BPTT."""
        self.memory.detach()

    def update_memory(
        self,
        src: torch.Tensor,
        dst: torch.Tensor,
        t: torch.Tensor,
        raw_msg: torch.Tensor
    ):
        """Sequentially updates node memory states with an observed interaction event."""
        if t.dtype != torch.long:
            t = t.to(torch.long)
        self.memory.update_state(src, dst, t, raw_msg)

    def get_embeddings(self, x: torch.Tensor) -> torch.Tensor:
        """Retrieves node embeddings combining static features and current temporal memory state."""
        all_nodes = torch.arange(self.num_nodes, device=x.device)
        mem, _ = self.memory(all_nodes)
        combined = torch.cat([x, mem], dim=-1)
        return torch.relu(self.node_proj(combined))

    def forward(
        self,
        x: torch.Tensor,
        src: torch.Tensor,
        dst: torch.Tensor,
        t_delta: Optional[torch.Tensor] = None
    ) -> torch.Tensor:
        """
        Predicts future interaction probability between src and dst based on current memory state.
        Does NOT update memory state (prediction step only).
        """
        z = self.get_embeddings(x)
        if t_delta is None:
            t_delta = torch.zeros((src.size(0), 1), device=x.device)
        elif t_delta.dim() == 1:
            t_delta = t_delta.unsqueeze(-1)

        edge_features = torch.cat([z[src], z[dst], t_delta], dim=-1)
        return self.link_pred(edge_features).squeeze(-1)
