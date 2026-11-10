#!/usr/bin/env python3
"""Recover session records and inline event pages from this sandbox's own transcripts.

The export agents call get_session / list_events; small results land inline in a
transcript rather than in a saved file. This walks the main and subagent
transcripts and files those results under the corpus.
"""
import glob, json, os, sys

DATA = os.environ.get("SPOTTER_DATA", "/home/user/spotter-data")
PROJ = glob.glob("/root/.claude/projects/-home-user/*.jsonl")
SUB = glob.glob("/root/.claude/projects/-home-user/*/subagents/*.jsonl")


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def parse_ccr(txt):
    i, j = txt.find('{"ccr"'), txt.rfind("}")
    if i < 0:
        return None
    # the block ends with a closing tag line; find the matching json end
    for end in (j + 1, txt.rfind("}", 0, j) + 1):
        try:
            return json.loads(txt[i:end])["ccr"]
        except ValueError:
            continue
    try:
        return json.JSONDecoder().raw_decode(txt[i:])[0]["ccr"]
    except ValueError:
        return None


def main():
    n_rec = n_pages = n_list = 0
    for path in PROJ + SUB:
        calls = {}
        for line in open(path, errors="replace"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            msg = d.get("message") or {}
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    calls[b.get("id")] = (b.get("name", ""), b.get("input") or {})
                elif b.get("type") == "tool_result":
                    name, inp = calls.get(b.get("tool_use_id"), ("", {}))
                    if "claude-code-remote" not in name:
                        continue
                    ccr = parse_ccr(text_of(b.get("content")))
                    if ccr is None:
                        continue
                    if name.endswith("get_session") and ccr.get("id"):
                        out = os.path.join(DATA, "corpus", ccr["id"])
                        os.makedirs(out, exist_ok=True)
                        prev = {}
                        p = os.path.join(out, "_session.json")
                        if os.path.exists(p):
                            prev = json.load(open(p))
                        prev.update(ccr)
                        json.dump(prev, open(p, "w"))
                        n_rec += 1
                    elif name.endswith("list_sessions"):
                        for rec in ccr.get("data", []):
                            out = os.path.join(DATA, "corpus", rec["id"])
                            os.makedirs(out, exist_ok=True)
                            p = os.path.join(out, "_session.json")
                            prev = json.load(open(p)) if os.path.exists(p) else {}
                            for k, v in rec.items():
                                prev.setdefault(k, v)
                            json.dump(prev, open(p, "w"))
                            n_list += 1
                    elif name.endswith("list_events") and "data" in ccr and inp.get("session_id"):
                        out = os.path.join(DATA, "corpus", inp["session_id"])
                        os.makedirs(out, exist_ok=True)
                        fid = ccr.get("first_id") or f"inline-{n_pages}"
                        p = os.path.join(out, f"{fid}.json")
                        if not os.path.exists(p):
                            json.dump(ccr, open(p, "w"))
                            n_pages += 1
    print(f"session records: {n_rec}  from list: {n_list}  inline pages recovered: {n_pages}")


if __name__ == "__main__":
    main()
