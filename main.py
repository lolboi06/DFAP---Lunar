# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research

import argparse
import sys
import uvicorn

from generate_sample_data import generate_sample_datasets
from dfap.pipeline import DFAPPipeline
from dfap.m3.pipeline import M3Pipeline


def main():
    parser = argparse.ArgumentParser(
        description="DFAP WP1 - Digital Footprint Fusion & Analysis Platform CLI"
    )
    parser.add_argument(
        "--mode",
        choices=["pipeline", "server", "generate", "build-graph", "extract-features", "run-m3"],
        default="pipeline",
        help="Operation mode: 'pipeline' (run batch ingestion & resolution), 'server' (start FastAPI server), 'generate' (create sample CSVs), 'build-graph' (build temporal graph), 'extract-features' (extract domain analytics)"
    )
    parser.add_argument(
        "--data-dir",
        default="./data/raw",
        help="Directory containing input raw CSV files (default: ./data/raw)"
    )
    parser.add_argument(
        "--out-dir",
        default="./output",
        help="Directory for exporting Parquet contract files (default: ./output)"
    )
    parser.add_argument(
        "--confirmed-threshold",
        type=float,
        default=0.85,
        help="Probability threshold for CONFIRMED match (default: 0.85)"
    )
    parser.add_argument(
        "--possible-threshold",
        type=float,
        default=0.60,
        help="Probability threshold for POSSIBLE match (default: 0.60)"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="FastAPI server host address (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="FastAPI server port (default: 8000)"
    )

    args = parser.parse_args()

    if args.mode == "generate":
        print(f"Generating synthetic adversarial CSV/JSON datasets in '{args.data_dir}'...")
        generate_sample_datasets(output_dir=args.data_dir)

    elif args.mode == "pipeline":
        print(f"Executing DFAP WP1 Pipeline (Confirmed > {args.confirmed_threshold}, Possible > {args.possible_threshold})...")
        generate_sample_datasets(output_dir=args.data_dir)

        pipeline = DFAPPipeline(
            confirmed_threshold=args.confirmed_threshold,
            possible_threshold=args.possible_threshold
        )
        results = pipeline.run(raw_data_dir=args.data_dir, output_dir=args.out_dir)

        print("\n================ DFAP WP1 Pipeline Execution Summary ================")
        print(f"Run ID              : {results['run_id']}")
        print(f"Status              : {results['status']}")
        print(f"Input Rows          : {results['input_rows']}")
        print(f"Accepted Rows       : {results['accepted_rows']}")
        print(f"Rejected Rows       : {results['rejected_rows']}")
        print(f"Canonical Events    : {results['canonical_events']}")
        print(f"Candidate Matches   : {results['candidate_matches']}")
        print(f"Confirmed Matches   : {results['confirmed_matches']}")
        print(f"Possible Matches    : {results['possible_matches']}")
        print(f"Rejected Matches    : {results['rejected_matches']}")
        print(f"Resolved Entities   : {results['resolved_entities']}")
        print(f"Provenance Records  : {results['provenance_records']}")
        print(f"Canonical Events    : {results['canonical_events_path']}")
        print(f"Resolved Entities   : {results['resolved_entities_path']}")
        print(f"Provenance Ledger   : {results['provenance_ledger_path']}")
        print(f"Entity Matches      : {results['entity_matches_path']}")
        print(f"Pipeline Manifest   : {results['manifest_path']}")
        print("====================================================================\n")

    elif args.mode == "server":
        print(f"Starting DFAP WP1 FastAPI server on http://{args.host}:{args.port}...")
        uvicorn.run("dfap.api:app", host=args.host, port=args.port, reload=True)

    elif args.mode == "build-graph":
        print(f"Building M4 Temporal Heterogeneous Graph from {args.out_dir}...")
        from dfap.graph import DFAPGraphService
        import os
        events_path = os.path.join(args.out_dir, "canonical_events.parquet")
        entities_path = os.path.join(args.out_dir, "resolved_entities.parquet")
        gs = DFAPGraphService()
        gs.load_graph_from_parquet(events_path, entities_path)
        print("Graph building completed.")

    elif args.mode == "extract-features":
        print(f"Extracting domain features (M5, M6, M7) using WP1 Parquet contracts in {args.out_dir}...")
        from dfap.graph import DFAPGraphService
        from dfap.features import DomainAnalyticsService
        import os
        events_path = os.path.join(args.out_dir, "canonical_events.parquet")
        entities_path = os.path.join(args.out_dir, "resolved_entities.parquet")
        gs = DFAPGraphService()
        gs.load_graph_from_parquet(events_path, entities_path)
        das = DomainAnalyticsService(gs)
        
        m5_df = das.m5_telecom_analytics()
        if not m5_df.empty:
            m5_df = m5_df.sort_values(by=['entity_id', 'feature_name']).reset_index(drop=True)
            m5_df.to_parquet(os.path.join(args.out_dir, "telecom_features.parquet"))
            print(f"Saved {len(m5_df)} telecom features.")
        
        m6_df = das.m6_financial_analytics()
        if not m6_df.empty:
            m6_df = m6_df.sort_values(by=['entity_id', 'feature_name']).reset_index(drop=True)
            m6_df.to_parquet(os.path.join(args.out_dir, "financial_features.parquet"))
            print(f"Saved {len(m6_df)} financial features.")
            
        m7_df = das.m7_social_analytics()
        if not m7_df.empty:
            m7_df = m7_df.sort_values(by=['entity_id', 'feature_name']).reset_index(drop=True)
            m7_df.to_parquet(os.path.join(args.out_dir, "social_features.parquet"))
            print(f"Saved {len(m7_df)} social features.")
            
        g_df = das.extract_graph_features()
        if not g_df.empty:
            g_df = g_df.sort_values(by=['entity_id', 'feature_name']).reset_index(drop=True)
            g_df.to_parquet(os.path.join(args.out_dir, "graph_features.parquet"))
            print(f"Saved {len(g_df)} graph features.")
            
        print("Feature extraction completed.")

    elif args.mode == "run-m3":
        import os as _os
        m3_out = _os.path.join(args.out_dir, "m3")
        pipeline = M3Pipeline(
            confirmed_threshold=args.confirmed_threshold,
            random_state=42,
        )
        manifest = pipeline.run(input_dir=args.out_dir, output_dir=m3_out)
        print(f"[M3] Pipeline completed. Manifest: {manifest}")




if __name__ == "__main__":
    main()
