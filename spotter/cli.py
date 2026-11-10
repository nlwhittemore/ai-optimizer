"""spotter — command line.

  spotter ingest   [--cloud DIR] [--claude-home DIR] [--codex-home DIR] [--chatgpt-export FILE] [--claude-export FILE]
  spotter measure
  spotter condense SESSION_ID
  spotter verify   FINDINGS.json
  spotter render   [--out FILE]
  spotter apply    FINDING_ID --repo-dir DIR

Data lives in $SPOTTER_DATA (default ~/.spotter). It never leaves the machine unless you move it.
"""
from __future__ import annotations
import argparse, glob, json, os, sys


def data_dir() -> str:
    d = os.environ.get("SPOTTER_DATA") or os.path.expanduser("~/.spotter")
    os.makedirs(d, exist_ok=True)
    return d


def load_sessions() -> list[dict]:
    path = os.path.join(data_dir(), "sessions.jsonl")
    if not os.path.exists(path):
        sys.exit("No sessions yet. Run `spotter ingest` first.")
    return [json.loads(line) for line in open(path)]


def cmd_ingest(a):
    sessions = []
    if a.cloud:
        from .adapters import claude_cloud
        for d in sorted(glob.glob(os.path.join(a.cloud, "session_*"))):
            sessions.append(claude_cloud.build_session(d).to_dict())
    if a.claude_home:
        from .adapters import claude_code
        sessions += [s.to_dict() for s in claude_code.load_all(a.claude_home)]
    if a.codex_home:
        from .adapters import codex
        sessions += [s.to_dict() for s in codex.load_all(a.codex_home)]
    if a.chatgpt_export:
        from .adapters import chat_export
        sessions += [s.to_dict() for s in chat_export.load_chatgpt(a.chatgpt_export)]
    if a.claude_export:
        from .adapters import chat_export
        sessions += [s.to_dict() for s in chat_export.load_claude(a.claude_export)]
    sessions = [s for s in sessions if s["turns"]]
    with open(os.path.join(data_dir(), "sessions.jsonl"), "w") as f:
        for s in sessions:
            f.write(json.dumps(s) + "\n")
    turns = sum(len(s["turns"]) for s in sessions)
    print(f"ingested {len(sessions)} sessions, {turns} turns -> {data_dir()}/sessions.jsonl")


def cmd_measure(a):
    from .measure import measure
    m = measure(load_sessions())
    json.dump(m, open(os.path.join(data_dir(), "metrics.json"), "w"), indent=1)
    print(json.dumps(m["overview"], indent=1))


def cmd_condense(a):
    from .condense import condense
    for s in load_sessions():
        if s["id"] == a.session_id or s["id"].endswith(a.session_id):
            print(condense(s))
            return
    sys.exit("session not found")


def cmd_verify(a):
    from .verify import verify_file
    sys.exit(verify_file(a.findings, load_sessions(), fix=a.fix))


def cmd_render(a):
    from .render import render
    out = a.out or os.path.join(data_dir(), "spotter.html")
    render(data_dir(), out)
    print(out)


def cmd_apply(a):
    from .apply import apply
    branch = apply(a.findings or os.path.join(data_dir(), "findings.json"), a.finding_id, a.repo_dir)
    print(f"committed on branch {branch}; review it, then push and merge")


def main(argv=None):
    p = argparse.ArgumentParser(prog="spotter", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("ingest"); i.set_defaults(fn=cmd_ingest)
    i.add_argument("--cloud"); i.add_argument("--claude-home"); i.add_argument("--codex-home")
    i.add_argument("--chatgpt-export"); i.add_argument("--claude-export")
    sub.add_parser("measure").set_defaults(fn=cmd_measure)
    c = sub.add_parser("condense"); c.add_argument("session_id"); c.set_defaults(fn=cmd_condense)
    v = sub.add_parser("verify"); v.add_argument("findings"); v.add_argument("--fix", action="store_true"); v.set_defaults(fn=cmd_verify)
    r = sub.add_parser("render"); r.add_argument("--out"); r.set_defaults(fn=cmd_render)
    ap = sub.add_parser("apply"); ap.add_argument("finding_id"); ap.add_argument("--repo-dir", required=True)
    ap.add_argument("--findings"); ap.set_defaults(fn=cmd_apply)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
