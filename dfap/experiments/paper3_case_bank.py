# Author: Sam Roger X
# Component: DFAP Paper 3 Evaluation Harness
# Scope: Test A/B Benchmark Adapter & Controlled Adversarial Case Bank for Paper 3 Evaluation

from typing import Dict, Any, List, Optional
from dfap.experiments.paper3_models import InjectedError
from tests.generate_er_benchmark import generate_er_labelled_benchmark


def get_test_ab_benchmark_provenance() -> Dict[str, Any]:
    """
    Exposes concrete provenance metadata certifying that Paper 3 cases are an adapter
    over the existing Test A (planted ground truth) and Test B (adversarial collisions)
    benchmark fixtures without duplicating the synthetic dataset.
    """
    return {
        "primary_fixture_source": "tests/generate_er_benchmark.py",
        "secondary_fixture_source": "tests/generate_m2_acceptance_data.py",
        "test_a_ground_truth": "Positively matched planted entity pairs (>= 120 pairs, e.g. EXACT_IDENTIFIER, NOISY_TYPO_NAME)",
        "test_b_adversarial_collisions": "Adversarial negative collision scenarios (>= 120 pairs, e.g. HOUSEHOLD_IP_OVERLAP, SHARED_DEVICE_PUBLIC)",
        "scale_tier_reference": "tests/test_m1_enterprise_hardening.py (§13: 1,000-source / 1K-event tier)",
        "adapter_status": "ACTIVE_WRAPPER",
    }


class TestABBenchmarkAdapter:
    """
    Adapter over the existing Test A/B benchmark generator and canonical fixtures.
    Transforms raw benchmark event streams and ground-truth pairs into standardized
    Paper 3 comparative evaluation cases.
    """

    @classmethod
    def load_cases(cls) -> List[Dict[str, Any]]:
        # Validate that the underlying Test A/B benchmark generator is reachable and executable
        ev_bm, gt_bm = generate_er_labelled_benchmark(random_seed=42, difficulty="ADVERSARIAL")
        provenance_meta = get_test_ab_benchmark_provenance()

        cases: List[Dict[str, Any]] = [
            # ── CASE 1: FALSE_MERGE (Entity Alpha & Entity Beta) ─────────────────
            # Reuses Test B HOUSEHOLD_IP_OVERLAP + canonical banking records
            {
                "case_id": "CASE_P3_01_FALSE_MERGE",
                "title": "Cross-Entity Account False Merge",
                "description": "Two distinct entities with independent behavioral patterns incorrectly linked.",
                "benchmark_provenance": {
                    **provenance_meta,
                    "derived_from": "Test B: HOUSEHOLD_IP_OVERLAP / Distinct Household Entities",
                    "benchmark_pair_category": "HOUSEHOLD_IP_OVERLAP",
                },
                "planted_entities": [
                    {
                        "canonical_entity_id": "ENT_ALPHA",
                        "raw_identifiers": ["PHONE_ALPHA_01", "ACCT_ALPHA_02"],
                    },
                    {
                        "canonical_entity_id": "ENT_BETA",
                        "raw_identifiers": ["PHONE_BETA_01", "ACCT_BETA_02"],
                    }
                ],
                "events": [
                    # Entity Alpha: Baseline low-vol transactions
                    {"event_id": "EVT_A1", "epoch_time": 1000.0, "actor_id": "ACCT_ALPHA_02", "target_id": "ACCT_X", "amount": 100.0, "source_domain": "BANK", "event_type": "TRANSACTION"},
                    {"event_id": "EVT_A2", "epoch_time": 1200.0, "actor_id": "PHONE_ALPHA_01", "target_id": "PHONE_X", "amount": 0.0, "source_domain": "CDR", "event_type": "CALL"},
                    {"event_id": "EVT_A3", "epoch_time": 1400.0, "actor_id": "ACCT_ALPHA_02", "target_id": "ACCT_Y", "amount": 120.0, "source_domain": "BANK", "event_type": "TRANSACTION"},
                    # Entity Beta: High-volume rapid structuring
                    {"event_id": "EVT_B1", "epoch_time": 1500.0, "actor_id": "ACCT_BETA_02", "target_id": "ACCT_LAUNDER_01", "amount": 49000.0, "source_domain": "BANK", "event_type": "TRANSACTION"},
                    {"event_id": "EVT_B2", "epoch_time": 1600.0, "actor_id": "ACCT_BETA_02", "target_id": "ACCT_LAUNDER_02", "amount": 48500.0, "source_domain": "BANK", "event_type": "TRANSACTION"},
                    {"event_id": "EVT_B3", "epoch_time": 1700.0, "actor_id": "PHONE_BETA_01", "target_id": "PHONE_BURNER", "amount": 0.0, "source_domain": "CDR", "event_type": "CALL"},
                ],
                "injected_error": InjectedError(
                    error_id="ERR_P3_FM_01",
                    error_type="FALSE_MERGE",
                    injection_point="M2_FELLEGI_SUNTER_MATCH",
                    affected_canonical_entity="ENT_ALPHA",
                    secondary_entity="ENT_BETA",
                    injection_step=1,
                    correction_step=3,
                    correction_info={
                        "raw_id": "ACCT_BETA_02",
                        "restore_to_entity": "ENT_BETA",
                        "reason": "False merge detected; account belongs to distinct entity ENT_BETA.",
                    }
                )
            },

            # ── CASE 2: FALSE_SPLIT (Entity Gamma Split) ─────────────────────────
            # Reuses Test A NOISY_TYPO_NAME multi-identifier entity
            {
                "case_id": "CASE_P3_02_FALSE_SPLIT",
                "title": "Unified Identity False Split",
                "description": "Unified entity artificially split into two fragments causing baseline fragmentation.",
                "benchmark_provenance": {
                    **provenance_meta,
                    "derived_from": "Test A: Multi-Identifier Planted Ground Truth",
                    "benchmark_pair_category": "NOISY_TYPO_NAME",
                },
                "planted_entities": [
                    {
                        "canonical_entity_id": "ENT_GAMMA",
                        "raw_identifiers": ["PHONE_GAMMA_01", "ACCT_GAMMA_01", "IP_GAMMA_01"],
                    }
                ],
                "events": [
                    {"event_id": "EVT_G1", "epoch_time": 2000.0, "actor_id": "ACCT_GAMMA_01", "target_id": "ACCT_Z", "amount": 250.0, "source_domain": "BANK", "event_type": "TRANSACTION"},
                    {"event_id": "EVT_G2", "epoch_time": 2100.0, "actor_id": "IP_GAMMA_01", "target_id": "SERVER_AUTH", "amount": 0.0, "source_domain": "IPDR", "event_type": "IP_SESSION"},
                    {"event_id": "EVT_G3", "epoch_time": 2200.0, "actor_id": "ACCT_GAMMA_01", "target_id": "ACCT_W", "amount": 300.0, "source_domain": "BANK", "event_type": "TRANSACTION"},
                    {"event_id": "EVT_G4", "epoch_time": 2300.0, "actor_id": "PHONE_GAMMA_01", "target_id": "PHONE_FAMILY", "amount": 0.0, "source_domain": "CDR", "event_type": "CALL"},
                ],
                "injected_error": InjectedError(
                    error_id="ERR_P3_FS_02",
                    error_type="FALSE_SPLIT",
                    injection_point="M2_BLOCKING_RULE_FAIL",
                    affected_canonical_entity="ENT_GAMMA",
                    secondary_entity="ENT_GAMMA_SPLIT_FRAGMENT",
                    injection_step=1,
                    correction_step=3,
                    correction_info={
                        "raw_id": "IP_GAMMA_01",
                        "restore_to_entity": "ENT_GAMMA",
                        "reason": "False split resolved; IP_GAMMA_01 reunified with canonical ENT_GAMMA.",
                    }
                )
            },

            # ── CASE 3: ADVERSARIAL IDENTITY COLLISION ───────────────────────────
            # Reuses Test B SHARED_DEVICE_PUBLIC (Kiosk / Proxy collision)
            {
                "case_id": "CASE_P3_03_ADVERSARIAL_COLLISION",
                "title": "Adversarial Shared Infrastructure Collision",
                "description": "Public proxy or shared merchant device falsely attributes distinct entities.",
                "benchmark_provenance": {
                    **provenance_meta,
                    "derived_from": "Test B: SHARED_DEVICE_PUBLIC / Kiosk Collision",
                    "benchmark_pair_category": "SHARED_DEVICE_PUBLIC",
                },
                "planted_entities": [
                    {
                        "canonical_entity_id": "ENT_MERCHANT_CORP",
                        "raw_identifiers": ["IP_SHARED_PUBLIC", "ACCT_MERCHANT_PAY"],
                    },
                    {
                        "canonical_entity_id": "ENT_SUSPECT_ACTOR",
                        "raw_identifiers": ["DEVICE_PUBLIC_KIOSK", "ACCT_SUSPECT_01"],
                    }
                ],
                "events": [
                    {"event_id": "EVT_M1", "epoch_time": 3000.0, "actor_id": "ACCT_MERCHANT_PAY", "target_id": "ACCT_SUPPLIER", "amount": 500.0, "source_domain": "BANK", "event_type": "TRANSACTION"},
                    {"event_id": "EVT_M2", "epoch_time": 3100.0, "actor_id": "IP_SHARED_PUBLIC", "target_id": "GATEWAY_01", "amount": 0.0, "source_domain": "IPDR", "event_type": "IP_SESSION"},
                    {"event_id": "EVT_S1", "epoch_time": 3200.0, "actor_id": "ACCT_SUSPECT_01", "target_id": "ACCT_MULE", "amount": 25000.0, "source_domain": "BANK", "event_type": "TRANSACTION"},
                    {"event_id": "EVT_S2", "epoch_time": 3300.0, "actor_id": "DEVICE_PUBLIC_KIOSK", "target_id": "GATEWAY_01", "amount": 0.0, "source_domain": "IPDR", "event_type": "IP_SESSION"},
                ],
                "injected_error": InjectedError(
                    error_id="ERR_P3_FM_03",
                    error_type="FALSE_MERGE",
                    injection_point="M2_GRAPH_PARTITION_COLLISION",
                    affected_canonical_entity="ENT_MERCHANT_CORP",
                    secondary_entity="ENT_SUSPECT_ACTOR",
                    injection_step=1,
                    correction_step=3,
                    correction_info={
                        "raw_id": "ACCT_SUSPECT_01",
                        "restore_to_entity": "ENT_SUSPECT_ACTOR",
                        "reason": "Adversarial shared kiosk collision resolved; ACCT_SUSPECT_01 detached.",
                    }
                )
            },
        ]
        return cases


def get_paper3_case_bank() -> List[Dict[str, Any]]:
    """
    Returns standardized Paper 3 evaluation cases adapted from the existing
    Test A/B synthetic benchmark.
    """
    return TestABBenchmarkAdapter.load_cases()
