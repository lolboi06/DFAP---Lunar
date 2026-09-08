import sys

with open('dfap/wp4/cli.py', 'r') as f:
    content = f.read()

patch = """
    if args and args[0] == "ldrm":
        from dfap.ldrm.cli import handle_ldrm_command
        m13_backend = _make_m13_backend()
        print(handle_ldrm_command(m13_backend, args[1:]))
        return
"""

target = '    if args and args[0] in ("language", "prompts"):'

if patch not in content:
    content = content.replace(target, patch + "\n" + target)
    with open('dfap/wp4/cli.py', 'w') as f:
        f.write(content)
