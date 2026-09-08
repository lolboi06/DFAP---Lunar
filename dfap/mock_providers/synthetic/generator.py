"""
Synthetic Data Generator for Mock Provider Subsystem.
Generates realistic fictional payloads for BANK, IPDR, CDR, and SOCIAL datasets.
Correlates synthetic identifiers for DEMO entity PERSON-DEMO-001.
"""
import json
import uuid
from typing import Dict, Any, List


class SyntheticDataGenerator:
    """Generates synthetic response payloads for mock providers."""

    CANONICAL_ENTITY_ID = "PERSON-DEMO-001"
    DEMO_EMAIL = "demo.person@example.test"
    DEMO_PHONE = "+919876543210"
    DEMO_BANK_ACC = "ACC-9988776655"
    DEMO_IP = "104.28.14.99"
    DEMO_SOCIAL_HANDLE = "@demouser001"

    @classmethod
    def generate_bank_response(cls, target_acc: str = DEMO_BANK_ACC, scenario: str = "VALID") -> bytes:
        if scenario == "MALFORMED":
            return b"{invalid_json_corrupted_payload"
        elif scenario == "EMPTY":
            payload = {"dataset_type": "BANK", "target": target_acc, "records": []}
            return json.dumps(payload, indent=2).encode("utf-8")
        elif scenario == "PARTIAL":
            records = [
                {
                    "txn_id": "TXN-DEMO-8801",
                    "account_number": target_acc,
                    "counterparty_account": "ACC-5544332211",
                    "amount": 25000.00,
                    "currency": "INR",
                    "txn_type": "NEFT_CREDIT",
                    "timestamp": "2026-08-10T10:30:00Z",
                    "narration": "CONSULTING FEE REF 492",
                    "linked_email": cls.DEMO_EMAIL,
                }
            ]
        else:
            records = [
                {
                    "txn_id": "TXN-DEMO-8801",
                    "account_number": target_acc,
                    "counterparty_account": "ACC-5544332211",
                    "amount": 25000.00,
                    "currency": "INR",
                    "txn_type": "NEFT_CREDIT",
                    "timestamp": "2026-08-10T10:30:00Z",
                    "narration": "CONSULTING FEE REF 492",
                    "linked_email": cls.DEMO_EMAIL,
                },
                {
                    "txn_id": "TXN-DEMO-8802",
                    "account_number": target_acc,
                    "counterparty_account": "ACC-1122334455",
                    "amount": 75000.00,
                    "currency": "INR",
                    "txn_type": "IMPS_DEBIT",
                    "timestamp": "2026-08-12T14:15:00Z",
                    "narration": "VENDOR PAYMENT DEMO",
                    "linked_phone": cls.DEMO_PHONE,
                },
            ]
        payload = {
            "dataset_type": "BANK",
            "provider_name": "Example National Bank",
            "target": target_acc,
            "entity_reference": cls.CANONICAL_ENTITY_ID,
            "records": records,
        }
        return json.dumps(payload, indent=2).encode("utf-8")

    @classmethod
    def generate_ipdr_response(cls, target_ip: str = DEMO_IP, scenario: str = "VALID") -> bytes:
        if scenario == "MALFORMED":
            return b"CORRUPTED_BINARY_STREAM_BYTE_ERROR"
        elif scenario == "EMPTY":
            payload = {"dataset_type": "IPDR", "target": target_ip, "records": []}
            return json.dumps(payload, indent=2).encode("utf-8")
        else:
            records = [
                {
                    "session_id": "SESS-ISP-4001",
                    "subscriber_id": "SUBSCRIBER-DEMO-001",
                    "source_ip": target_ip,
                    "destination_ip": "104.244.42.1",
                    "protocol": "TCP",
                    "source_port": 54321,
                    "destination_port": 443,
                    "bytes_up": 1420,
                    "bytes_down": 8940,
                    "start_time": "2026-08-10T08:00:00Z",
                    "end_time": "2026-08-10T08:12:00Z",
                    "assigned_email": cls.DEMO_EMAIL,
                    "msisdn": cls.DEMO_PHONE,
                }
            ]
            if scenario == "PARTIAL":
                records = records[:1]
        payload = {
            "dataset_type": "IPDR",
            "provider_name": "ExampleNet ISP",
            "target": target_ip,
            "entity_reference": cls.CANONICAL_ENTITY_ID,
            "records": records,
        }
        return json.dumps(payload, indent=2).encode("utf-8")

    @classmethod
    def generate_cdr_response(cls, target_phone: str = DEMO_PHONE, scenario: str = "VALID") -> bytes:
        if scenario == "MALFORMED":
            return b"<<INVALID_XML_CONTAINER>>"
        elif scenario == "EMPTY":
            payload = {"dataset_type": "CDR", "target": target_phone, "records": []}
            return json.dumps(payload, indent=2).encode("utf-8")
        else:
            records = [
                {
                    "call_id": "CALL-TEL-9001",
                    "calling_number": target_phone,
                    "called_number": "+919811223344",
                    "timestamp": "2026-08-10T09:00:00Z",
                    "duration_seconds": 180,
                    "call_type": "OUTGOING_VOICE",
                    "cell_tower_id": "TOWER-DEL-101",
                    "imsi": "404450123456789",
                    "imei": "864201041234567",
                    "linked_account": cls.DEMO_BANK_ACC,
                },
                {
                    "call_id": "CALL-TEL-9002",
                    "calling_number": "+919811223344",
                    "called_number": target_phone,
                    "timestamp": "2026-08-11T11:45:00Z",
                    "duration_seconds": 65,
                    "call_type": "INCOMING_VOICE",
                    "cell_tower_id": "TOWER-DEL-102",
                    "imsi": "404450123456789",
                    "imei": "864201041234567",
                    "linked_email": cls.DEMO_EMAIL,
                },
            ]
            if scenario == "PARTIAL":
                records = records[:1]
        payload = {
            "dataset_type": "CDR",
            "provider_name": "Example Telecom",
            "target": target_phone,
            "entity_reference": cls.CANONICAL_ENTITY_ID,
            "records": records,
        }
        return json.dumps(payload, indent=2).encode("utf-8")

    @classmethod
    def generate_social_response(cls, target_handle: str = DEMO_SOCIAL_HANDLE, scenario: str = "VALID") -> bytes:
        if scenario == "MALFORMED":
            return b"--- INVALID SOCIAL STREAM ---"
        elif scenario == "EMPTY":
            payload = {"dataset_type": "SOCIAL", "target": target_handle, "records": []}
            return json.dumps(payload, indent=2).encode("utf-8")
        else:
            records = [
                {
                    "post_id": "POST-SOC-7001",
                    "handle": target_handle,
                    "registered_email": cls.DEMO_EMAIL,
                    "registered_phone": cls.DEMO_PHONE,
                    "action": "POST_STATUS",
                    "timestamp": "2026-08-10T16:00:00Z",
                    "login_ip": cls.DEMO_IP,
                    "content_summary": "Meeting confirmed for tonight.",
                }
            ]
            if scenario == "PARTIAL":
                records = records[:1]
        payload = {
            "dataset_type": "SOCIAL",
            "provider_name": "Example Social",
            "target": target_handle,
            "entity_reference": cls.CANONICAL_ENTITY_ID,
            "records": records,
        }
        return json.dumps(payload, indent=2).encode("utf-8")
