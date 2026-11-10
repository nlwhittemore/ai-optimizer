"""Turn an approved finding into a change: append its proposed text to the target file on a new branch."""
from __future__ import annotations
import json, os, subprocess, sys


def apply(findings_path: str, finding_id: str, repo_dir: str) -> str:
    doc = json.load(open(findings_path))
    if not doc.get("verified"):
        sys.exit("Refusing to apply: findings file has not passed `spotter verify`.")
    f = next((x for x in doc["findings"] if x["id"] == finding_id), None)
    if f is None or not (f.get("action") or {}).get("patch"):
        sys.exit("No such finding, or it has no proposed text.")
    a = f["action"]
    target = os.path.join(repo_dir, a["file"])
    heading = a["patch"].strip().splitlines()[0]
    current = open(target).read() if os.path.exists(target) else ""
    if heading in current:
        sys.exit(f"{a['file']} already has a section titled {heading!r}; edit it by hand.")
    branch = f"spotter/{finding_id}"
    run = lambda *cmd: subprocess.run(cmd, cwd=repo_dir, check=True)
    run("git", "checkout", "-b", branch)
    with open(target, "a") as fh:
        fh.write(("" if current.endswith("\n") else "\n") + "\n" + a["patch"].strip() + "\n")
    run("git", "add", a["file"])
    run("git", "commit", "-m", f"{f['title'].rstrip('.')[:68]}\n\n{f['claim']}\n\nProposed by Spotter from session evidence ({len(f.get('evidence', []))} citations).")
    return branch
