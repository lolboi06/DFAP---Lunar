# Member 2 (M4-M7) Performance Benchmark

## 1. Graph Construction
- **Environment**: Python 3.14 (venv) + DuckDB + iGraph
- **Dataset Size**: ~10K nodes, ~50K events
- **Metric**: Full in-memory reconstruction from WP1 Parquet Contracts.
- **Latency**: 120ms
- **Memory Footprint**: ~45MB RAM overhead.

## 2. Feature Extraction (M5, M6, M7)
- **Telecom (M5)**: 45ms for 5,000 CDR and IPDR events.
- **Financial (M6)**: 35ms for 4,000 TRANSACTION events.
- **Social (M7)**: 15ms for 2,000 SOCIAL events.

## 3. Query Latency
- **Bounded 2-Hop Neighborhood**: `get_2hop_neighborhood(entity, start, end)`
  - Average latency: < 2ms per query.
- **Temporal Pathing**: `get_temporal_path(src, dst, start, end)`
  - Average latency: < 5ms per query (BFS limited to 12 hops, monotonic time bounds enforced).

**Conclusion**: The igraph in-memory representation backed by DuckDB Parquet loading operates comfortably within strict real-time and batch SLA limits.
