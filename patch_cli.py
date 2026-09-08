import sys
with open('dfap/wp4/cli.py', 'r') as f:
    content = f.read()

new_commands = """
    # M13 Commands
    subparsers.add_parser("case", help="Case-level forensic and risk commands")
    subparsers.add_parser("sequence", help="Temporal and sequence commands")
    subparsers.add_parser("agent", help="Agentic investigation commands")
    subparsers.add_parser("graph", help="Graph ML commands")
    subparsers.add_parser("graphml", help="Graph ML benchmark commands")
    subparsers.add_parser("risk", help="Risk triage commands")
    subparsers.add_parser("explain", help="Explainability commands")
    subparsers.add_parser("copilot", help="Copilot commands")
"""

target = '    p_finding = subparsers.add_parser("finding", help="Retrieves finding metadata")'

if new_commands not in content:
    content = content.replace(target, new_commands + "\n" + target)
    with open('dfap/wp4/cli.py', 'w') as f:
        f.write(content)
