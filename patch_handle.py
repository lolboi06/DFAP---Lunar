with open('dfap/wp4/cli.py', 'r') as f:
    content = f.read()

old_patch = """        if cmd == "ldrm":
        from dfap.ldrm.cli import handle_ldrm_command
        return handle_ldrm_command(m13_backend, parts[1:])"""

new_patch = """        if cmd == "ldrm":
            from dfap.ldrm.cli import handle_ldrm_command
            return handle_ldrm_command(m13_backend, parts[1:])"""

content = content.replace(old_patch, new_patch)

with open('dfap/wp4/cli.py', 'w') as f:
    f.write(content)
