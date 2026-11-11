#!/usr/bin/env bash
# Install the live coach for Claude Code on this machine.
# Registers two hooks in ~/.claude/settings.json (backing the file up first). Re-run to update.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 - "$DIR" <<'PY'
import json, os, shutil, sys, time
repo = sys.argv[1]
path = os.path.expanduser("~/.claude/settings.json")
os.makedirs(os.path.dirname(path), exist_ok=True)
settings = {}
if os.path.exists(path):
    settings = json.load(open(path))
    shutil.copy(path, f"{path}.bak-{int(time.time())}")
hooks = settings.setdefault("hooks", {})
for event, arg in (("UserPromptSubmit", "prompt"), ("Stop", "stop")):
    cmd = f'cd "{repo}" && python3 -m spotter.live {arg}'
    groups = [g for g in hooks.get(event, []) if not any("spotter.live" in h.get("command", "") for h in g.get("hooks", []))]
    groups.append({"hooks": [{"type": "command", "command": cmd, "timeout": 10}]})
    hooks[event] = groups
json.dump(settings, open(path, "w"), indent=2)
print(f"Live coach registered in {path}. Start a new Claude Code session to use it.")
PY
