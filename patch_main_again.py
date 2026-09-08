with open('dfap/wp4/cli.py', 'r') as f:
    content = f.read()

old_patch = """    if args and args[0] in _M13_TOP_COMMANDS:
        cmd_line = shlex.join(args)
    
        result = handle_m13_command(m13_backend, cmd_line)"""

new_patch = """    if args and args[0] in _M13_TOP_COMMANDS:
        cmd_line = shlex.join(args)
        m13_backend = _make_m13_backend()
        result = handle_m13_command(m13_backend, cmd_line)"""

content = content.replace(old_patch, new_patch)
with open('dfap/wp4/cli.py', 'w') as f:
    f.write(content)
