with open('dfap/wp4/cli.py', 'r') as f:
    content = f.read()

bad_patch = """    m13_backend = _make_m13_backend()
    
    if args and args[0] == "ldrm":
        from dfap.ldrm.cli import handle_ldrm_command
        print(handle_ldrm_command(m13_backend, args[1:]))
        return
"""
content = content.replace(bad_patch, "")

with open('dfap/wp4/cli.py', 'w') as f:
    f.write(content)
