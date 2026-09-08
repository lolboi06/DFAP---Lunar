# Author: Sam Roger X
# Component: DFAP WP1 - Data & Entity Research

import json
import os
import pandas as pd
from datetime import datetime, timedelta


def generate_sample_datasets(output_dir: str = "./data/raw"):
    """
    Generates synthetic adversarial test datasets across CDR, IPDR, BANK, SOCIAL domains.
    Includes positive matches, negative matches (shared household IP/device), noisy names,
    duplicate rows, and malformed records for row validation testing.
    """
    os.makedirs(output_dir, exist_ok=True)
    base_time = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc if hasattr(datetime, 'timezone') else None)

    # 1. CDR Dataset (CSV) - Positive matches & invalid records
    cdr_data = [
        # Entity 1: Sam Roger X
        {
            "call_id": "CDR_1001",
            "timestamp": "2026-09-01T10:05:00Z",
            "caller_num": "+1-555-0101",
            "receiver_num": "+1-555-0199",
            "duration_sec": 180,
            "tower_id": "TWR_NYC_01",
            "caller_name": "Sam Roger X",
            "ip_subnet": "192.168.10.0/24"
        },
        # Entity 2: Marcus Wright
        {
            "call_id": "CDR_1002",
            "timestamp": "2026-09-01T10:12:00Z",
            "caller_num": "+1-555-0202",
            "receiver_num": "+1-555-0101",
            "duration_sec": 45,
            "tower_id": "TWR_NYC_04",
            "caller_name": "Marcus Wright",
            "ip_subnet": "10.200.5.0/24"
        },
        # Entity 3: Household Person A (sharing household IP with Person B)
        {
            "call_id": "CDR_1003",
            "timestamp": "2026-09-01T10:20:00Z",
            "caller_num": "+1-555-0303",
            "receiver_num": "+1-555-0800",
            "duration_sec": 300,
            "tower_id": "TWR_BOS_02",
            "caller_name": "Alice Household-A",
            "ip_subnet": "172.16.50.0/24"
        },
        # Malformed record 1: Negative call duration (Should be rejected)
        {
            "call_id": "CDR_BAD_1",
            "timestamp": "2026-09-01T10:25:00Z",
            "caller_num": "+1-555-0999",
            "receiver_num": "+1-555-0888",
            "duration_sec": -120,
            "tower_id": "TWR_BAD",
            "caller_name": "Invalid Duration",
            "ip_subnet": "192.168.1.0/24"
        },
        # Malformed record 2: Missing caller_num (Should be rejected)
        {
            "call_id": "CDR_BAD_2",
            "timestamp": "2026-09-01T10:30:00Z",
            "caller_num": "",
            "receiver_num": "+1-555-0888",
            "duration_sec": 60,
            "tower_id": "TWR_BAD",
            "caller_name": "Missing Actor",
            "ip_subnet": "192.168.1.0/24"
        }
    ]
    pd.DataFrame(cdr_data).to_csv(os.path.join(output_dir, "cdr_records.csv"), index=False)

    # 2. IPDR Dataset (CSV) - Shared IP/Device Negative Example
    ipdr_data = [
        # Entity 1: Sam Roger X
        {
            "session_id": "IPDR_5001",
            "timestamp": "2026-09-01T10:07:00Z",
            "src_ip": "192.168.10.45",
            "dst_ip": "172.217.14.206",
            "ip_subnet": "192.168.10.0/24",
            "bytes_sent": 1048576,
            "user_id": "usr_sroger",
            "actor_name": "Sam R. X"
        },
        # Entity 4: Household Person B (Shares IP subnet 172.16.50.0/24 with Alice, but different person!)
        {
            "session_id": "IPDR_5002",
            "timestamp": "2026-09-01T10:22:00Z",
            "src_ip": "172.16.50.18",
            "dst_ip": "142.250.190.46",
            "ip_subnet": "172.16.50.0/24",
            "bytes_sent": 512000,
            "user_id": "usr_bob_b",
            "actor_name": "Bob Household-B"
        },
        # Malformed Record: Invalid IP format (Should be rejected)
        {
            "session_id": "IPDR_BAD_1",
            "timestamp": "2026-09-01T10:35:00Z",
            "src_ip": "999.888.777.666",
            "dst_ip": "142.250.190.46",
            "ip_subnet": "invalid_subnet",
            "bytes_sent": 100,
            "user_id": "usr_bad_ip",
            "actor_name": "Bad IP Format"
        }
    ]
    pd.DataFrame(ipdr_data).to_csv(os.path.join(output_dir, "ipdr_records.csv"), index=False)

    # 3. Banking Dataset (CSV) - Positive match with Sam Roger X
    banking_data = [
        # Entity 1: S Roger (Same phone + same name variation as Sam Roger X)
        {
            "txn_id": "BNK_9001",
            "timestamp": "2026-09-01T10:10:00Z",
            "sender_acc": "ACC-1001",
            "beneficiary_acc": "ACC-9999",
            "amount": 2500.00,
            "currency": "USD",
            "sender_name": "S Roger",
            "phone_number": "+1-555-0101",
            "ip_subnet": "192.168.10.0/24"
        },
        # Entity 2: Marcus Wright
        {
            "txn_id": "BNK_9002",
            "timestamp": "2026-09-01T10:30:00Z",
            "sender_acc": "ACC-2002",
            "beneficiary_acc": "ACC-8888",
            "amount": 10000.00,
            "currency": "USD",
            "sender_name": "Marc Wright",
            "phone_number": "+1-555-0202",
            "ip_subnet": "10.200.5.0/24"
        },
        # Malformed Record: Negative amount (Should be rejected)
        {
            "txn_id": "BNK_BAD_1",
            "timestamp": "2026-09-01T10:40:00Z",
            "sender_acc": "ACC-BAD",
            "beneficiary_acc": "ACC-8888",
            "amount": -500.00,
            "currency": "USD",
            "sender_name": "Negative Money",
            "phone_number": "+1-555-0000",
            "ip_subnet": "10.0.0.0/24"
        }
    ]
    pd.DataFrame(banking_data).to_csv(os.path.join(output_dir, "bank_records.csv"), index=False)

    # 4. Social Dataset (JSON) - Positive match with samroger_x
    social_data = [
        # Entity 1: samroger_x
        {
            "post_id": "SOC_7001",
            "timestamp": "2026-09-01T10:02:00Z",
            "user_handle": "@samroger_x",
            "target_handle": "@tech_news",
            "platform": "X/Twitter",
            "actor_name": "Sam Roger X",
            "phone_number": "+1-555-0101",
            "ip_subnet": "192.168.10.0/24",
            "device_id": "DEV_SAM_PHONE"
        },
        # Entity 2: Marcus Wright
        {
            "post_id": "SOC_7002",
            "timestamp": "2026-09-01T10:18:00Z",
            "user_handle": "@mwright_sec",
            "target_handle": "@cyber_daily",
            "platform": "LinkedIn",
            "actor_name": "Marcus Wright",
            "phone_number": "+1-555-0202",
            "ip_subnet": "10.200.5.0/24",
            "device_id": "DEV_MARCUS_LAPTOP"
        }
    ]
    with open(os.path.join(output_dir, "social_records.json"), "w", encoding="utf-8") as fh:
        json.dump(social_data, fh, indent=2)

    print(f"Synthetic adversarial datasets generated successfully in: {output_dir}")


if __name__ == "__main__":
    generate_sample_datasets()
