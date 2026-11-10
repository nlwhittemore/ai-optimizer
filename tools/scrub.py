#!/usr/bin/env python3
"""Remove model reasoning (thinking blocks and their signatures) from stored event pages.
Spotter evaluates what was asked, what was done and what came back — never the model's private reasoning."""
import glob, json, os, sys
DATA = os.environ.get("SPOTTER_DATA", "/home/user/spotter-data")
n = 0
for path in glob.glob(os.path.join(DATA, "corpus", "*", "*.json")):
    if os.path.basename(path).startswith("_"):
        continue
    try:
        page = json.load(open(path))
    except ValueError:
        continue
    changed = False
    for ev in page.get("data", []):
        a = ev.get("assistant")
        if not isinstance(a, dict):
            continue
        msg = (a.get("internal_anthropic_catchall") or a).get("message") or {}
        content = msg.get("content")
        if isinstance(content, list):
            kept = [b for b in content if not (isinstance(b, dict) and b.get("type") in ("thinking", "redacted_thinking"))]
            if len(kept) != len(content):
                msg["content"] = kept; changed = True; n += len(content) - len(kept)
    if changed:
        json.dump(page, open(path, "w"))
print(f"removed {n} reasoning blocks")
