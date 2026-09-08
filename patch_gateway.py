with open('dfap/ldrm/gateway.py', 'r') as f:
    content = f.read()

patch = """        module.service.provider_registry.verify_provider(p_bank.id, "admin-001", "Auto-verified")
        module.service.provider_registry.verify_destination(p_bank.id, "dst-bank", "admin-001")"""

content = content.replace('        module.service.provider_registry.verify_provider(p_bank.id, "admin-001", "Auto-verified")', patch)

patch2 = """        module.service.provider_registry.verify_provider(p_telecom.id, "admin-001", "Auto-verified")
        module.service.provider_registry.verify_destination(p_telecom.id, "dst-telco", "admin-001")"""

content = content.replace('        module.service.provider_registry.verify_provider(p_telecom.id, "admin-001", "Auto-verified")', patch2)

with open('dfap/ldrm/gateway.py', 'w') as f:
    f.write(content)
