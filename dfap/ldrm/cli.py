from dfap.ldrm.gateway import initialize_ldrm
from dfap.ldrm_subsystem.api.cli import LDRMConsoleCLI
import argparse

def handle_ldrm_command(m13_backend, args):
    module = initialize_ldrm(m13_backend)
    cli = LDRMConsoleCLI(module.service, "inv-001")
    
    if not args:
        return "Usage: dfap-cli ldrm <command>"
        
    cmd = args[0]
    
    if cmd == "request" and len(args) > 1 and args[1] == "create":
        # request create <case_id> <provider_id> <dataset_type> <target_type> <target_value>
        if len(args) < 7:
            return "Usage: request create <case_id> <provider_id> <dataset_type> <target_type> <target_value>"
        return cli.cmd_create_request(
            case_id=args[2],
            provider_id=args[3],
            dataset_type_str=args[4],
            target_type_str=args[5],
            target_value=args[6],
            start_time="2026-01-01T00:00:00Z",
            end_time="2026-12-31T23:59:59Z",
            categories=["all"],
            justification="Investigation"
        )
        
    elif cmd == "authorize":
        if len(args) < 3:
            return "Usage: authorize <request_id> <hash>"
        return cli.cmd_authorize(
            request_id=args[1],
            authority_type="COURT_ORDER",
            authority_reference="WARRANT-123",
            issuing_authority="DISTRICT_COURT",
            approved_scope_summary="Approved",
            expected_version=1,
            expected_hash=args[2]
        )
        
    elif cmd == "dispatch":
        if len(args) < 3:
            return "Usage: dispatch <request_id> <hash>"
        return cli.cmd_sign_and_dispatch(
            request_id=args[1],
            expected_hash=args[2]
        )
        
    elif cmd == "status":
        reqs = module.repository.connection.execute("SELECT id, status FROM lawful_requests").fetchall()
        return "\n".join(f"{r['id']} - {r['status']}" for r in reqs)
        
    elif cmd == "providers":
        return cli.cmd_list_providers()
        
    return f"Unknown LDRM command: {cmd}"
