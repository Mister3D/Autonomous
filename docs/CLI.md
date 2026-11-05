# CLI — Autonomous

```bash
pip install -e .
autonomous init
autonomous serve --host 127.0.0.1 --port 8787
```

All business commands import the **services** (not HTTP), unless stated otherwise.

```text
autonomous init [--password …] [--must-change-password]
autonomous serve [start] [--host 127.0.0.1] [--port 8787] [--dev]
autonomous serve stop
autonomous health [--json]

autonomous bot create <name> [--label] [--internet|--no-internet]
autonomous bot list [--json]
autonomous bot show <name> [--json]
autonomous bot delete <name> [--yes]
autonomous bot set <name> [--internet|--no-internet] [--capability none|screen] [--label]
# --capability terminal is accepted as an alias for screen (one VM, shell + screen)

autonomous chat send <name> <text>
autonomous chat history <name> [--limit N] [--json]
autonomous chat clear <name> [--yes]

autonomous desk create <name>
autonomous desk destroy <name> [--yes]
autonomous desk restart <name>
autonomous desk reset <name> [--yes]
autonomous desk status <name> [--json]

autonomous terminal exec <name> -- <command...>
autonomous terminal log <name> [--limit N] [--json]

autonomous files ls <name> [path]
autonomous files get <name> <path> [-o FILE]
autonomous files rm <name> <path> [--yes]

autonomous job show <id> [--json]
```

Exit codes: `0` OK · `1` error · `2` usage.
