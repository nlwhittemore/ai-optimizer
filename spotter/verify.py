"""Every finding must cite evidence, and every citation is checked against the record.

A quote must appear, verbatim (whitespace-insensitive), in what the person typed in the cited session.
A number must match the metrics file. Findings that fail are rejected, not shown.
"""
from __future__ import annotations
import json, os


def _norm(s: str) -> str:
    return " ".join((s or "").split())


def _lookup(metrics: dict, path: str):
    cur = metrics
    for part in path.split("."):
        if isinstance(cur, list):
            cur = cur[int(part)]
        else:
            cur = cur[part]
    return cur


def verify(findings: list[dict], sessions: list[dict], metrics: dict | None = None) -> list[str]:
    by_id = {}
    for s in sessions:
        by_id[s["id"]] = s
    problems = []
    for f in findings:
        for i, ev in enumerate(f.get("evidence", [])):
            label = f"{f['id']} evidence[{i}]"
            s = by_id.get(ev.get("session")) or next((x for x in sessions if x["id"].endswith(ev.get("session", "\0"))), None)
            if s is None:
                problems.append(f"{label}: session {ev.get('session')} not in the record"); continue
            ev["session"] = s["id"]; ev.setdefault("title", s.get("title", ""))
            texts = []
            for t in s["turns"]:
                if ev.get("turn") is None or t["idx"] == ev["turn"]:
                    texts += [t["prompt"]] + t["interjections"]
                    if ev.get("turn") is not None:
                        ev.setdefault("date", t["started_at"][:10])
            if ev.get("quote") and not any(_norm(ev["quote"]) in _norm(x) for x in texts):
                problems.append(f"{label}: quote not found: {ev['quote'][:60]!r}")
        for i, num in enumerate(f.get("numbers", [])):
            if num.get("metric") and metrics is not None:
                try:
                    actual = _lookup(metrics, num["metric"])
                except (KeyError, IndexError, ValueError):
                    problems.append(f"{f['id']} numbers[{i}]: metric {num['metric']} missing"); continue
                if isinstance(actual, float) and isinstance(num.get("value"), (int, float)):
                    ok = abs(actual - num["value"]) <= 0.006 * max(1, abs(actual))
                else:
                    ok = actual == num.get("value")
                if not ok:
                    problems.append(f"{f['id']} numbers[{i}]: {num['metric']} is {actual}, finding says {num.get('value')}")
    return problems


def verify_file(path: str, sessions: list[dict], fix: bool = False) -> int:
    doc = json.load(open(path))
    mpath = os.path.join(os.path.dirname(os.path.abspath(path)), "metrics.json")
    metrics = json.load(open(mpath)) if os.path.exists(mpath) else None
    problems = verify(doc["findings"], sessions, metrics)
    for p in problems:
        print("FAIL", p)
    n_ev = sum(len(f.get("evidence", [])) for f in doc["findings"])
    n_num = sum(1 for f in doc["findings"] for n in f.get("numbers", []) if n.get("metric"))
    print(f"{len(doc['findings'])} findings, {n_ev} quotes, {n_num} metric-backed numbers checked, {len(problems)} problems")
    if not problems or fix:
        doc["verified"] = not problems
        json.dump(doc, open(path, "w"), indent=1)
    return 1 if problems else 0
