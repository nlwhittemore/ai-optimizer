"""Background watcher: follows AI tool logs on this machine and raises a note the moment you send something.

  python3 -m spotter.watch            # run until stopped
  python3 -m spotter.watch --seconds 5

Watches Claude Code (~/.claude/projects) and Codex (~/.codex/sessions). Each new message you send is checked
with the same rules as the in-session hook; a note becomes a macOS notification and a line in ~/.spotter/notes.jsonl
(the menu bar app reads that file). No model calls, no network.
"""
from __future__ import annotations
import argparse, glob, json, os, subprocess, sys, time
from .live import HOME, PROFILE, _load, notes_for, session_facts

ROOTS = {
    "claude-code": os.path.expanduser(os.environ.get("SPOTTER_CLAUDE_HOME", "~/.claude") + "/projects"),
    "codex": os.path.expanduser(os.environ.get("SPOTTER_CODEX_HOME", "~/.codex") + "/sessions"),
}
RECENT_SECONDS = 6 * 3600


def notify(title: str, text: str) -> None:
    os.makedirs(HOME, exist_ok=True)
    with open(os.path.join(HOME, "notes.jsonl"), "a") as fh:
        fh.write(json.dumps({"at": time.time(), "title": title, "text": text}) + "\n")
    if sys.platform == "darwin":
        script = f'display notification {json.dumps(text)} with title {json.dumps(title)}'
        subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
    else:
        print(f"[{title}] {text}", flush=True)


def _human_prompt(source: str, d: dict) -> str | None:
    """Return the text if this log line is a message the person just sent."""
    if source == "claude-code":
        if d.get("type") != "user" or d.get("isSidechain") or d.get("isMeta"):
            return None
        content = (d.get("message") or {}).get("content")
        if isinstance(content, str) and content.strip() and not content.lstrip().startswith(("<", "[")):
            return content
        return None
    p = d.get("payload") or {}                       # codex rollout line (format unverified on a real file)
    if d.get("type") == "response_item" and p.get("type") == "message" and p.get("role") == "user":
        text = "\n".join(b.get("text", "") for b in p.get("content") or [] if isinstance(b, dict))
        if text.strip() and not text.lstrip().startswith("<"):
            return text
    return None


def _codex_facts(path: str) -> dict:
    f = {"context": None, "model": None, "effort": None, "last_activity": None, "human_asks": 0, "prior": []}
    for line in open(path, errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        p = d.get("payload") or {}
        if d.get("type") == "turn_context":
            f["model"] = p.get("model") or f["model"]
            f["effort"] = p.get("effort") or p.get("reasoning_effort") or f["effort"]
        elif d.get("type") == "event_msg" and p.get("type") == "token_count":
            f["context"] = ((p.get("info") or {}).get("last_token_usage") or {}).get("input_tokens") or f["context"]
        elif _human_prompt("codex", d):
            f["human_asks"] += 1
        if d.get("type") == "response_item" and p.get("role") == "assistant":
            f["last_activity"] = d.get("timestamp")
    return f


class Watcher:
    def __init__(self):
        self.offsets: dict[str, int] = {}
        self.shown: dict[str, set] = {}
        self.muted = False

    def files(self):
        now = time.time()
        for source, root in ROOTS.items():
            pattern = os.path.join(root, "*", "*.jsonl") if source == "claude-code" else os.path.join(root, "**", "rollout-*.jsonl")
            for path in glob.glob(pattern, recursive=True):
                try:
                    if now - os.path.getmtime(path) < RECENT_SECONDS:
                        yield source, path
                except OSError:
                    continue

    def prime(self):
        """Start from the end of every existing log so old messages do not fire notes."""
        for _, path in self.files():
            self.offsets[path] = os.path.getsize(path)

    def poll(self) -> int:
        fired = 0
        for source, path in self.files():
            size = os.path.getsize(path)
            start = self.offsets.get(path, 0)
            if size <= start:
                self.offsets[path] = size
                continue
            with open(path, errors="replace") as fh:
                fh.seek(start)
                chunk = fh.read()
            if not chunk.endswith("\n"):                 # a line is still being written
                chunk = chunk[: chunk.rfind("\n") + 1]
            self.offsets[path] = start + len(chunk.encode("utf-8", "replace"))
            for line in chunk.splitlines():
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                prompt = _human_prompt(source, d)
                if prompt is None:
                    continue
                low = prompt.lower()
                if "coach off" in low or "coach on" in low:
                    self.muted = "coach off" in low
                    continue
                if self.muted:
                    continue
                facts = session_facts(path) if source == "claude-code" else _codex_facts(path)
                facts["human_asks"] = max(0, facts["human_asks"] - 1)      # the message just sent is not "prior"
                shown = self.shown.setdefault(path, set())
                cands = notes_for(prompt, facts, _load(PROFILE, {}), shown)
                if cands:
                    note_id, text = cands[0]
                    if note_id != "secret":
                        shown.add(note_id)
                    tool = "Claude Code" if source == "claude-code" else "Codex"
                    notify(f"Coach · {tool}", text)
                    fired += 1
        return fired


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=0, help="stop after this long (0 = run forever)")
    ap.add_argument("--interval", type=float, default=1.0)
    a = ap.parse_args()
    w = Watcher()
    w.prime()
    end = time.time() + a.seconds if a.seconds else None
    while end is None or time.time() < end:
        w.poll()
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
