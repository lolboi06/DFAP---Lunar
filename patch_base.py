with open('dfap/ldrm_subsystem/providers/connectors/base.py', 'r') as f:
    content = f.read()

patch = """        if self.method not in provider.submission_methods:
            raise ValueError(f"Method mismatch: {self.method} not in {provider.submission_methods}")
        if transmission.transmission_method != self.method:
            raise ValueError(f"Transmission method mismatch")
"""

target = "        if (package != approved or request.canonical_dict() != stored.canonical_dict()"

content = content.replace(target, patch + target)
with open('dfap/ldrm_subsystem/providers/connectors/base.py', 'w') as f:
    f.write(content)
