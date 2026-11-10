"""Turn a normalized session into a compact transcript a reviewer can read end to end."""
from __future__ import annotations
from collections import Counter


def _clip(text: str, n: int) -> str:
    text = (text or "").strip()
    if len(text) <= n:
        return text
    head = int(n * 0.7)
    return f"{text[:head]}\n[... {len(text) - n} chars omitted ...]\n{text[-(n - head):]}"


def _dur(ms) -> str:
    if ms is None:
        return "?"
    s = ms / 1000
    if s < 90:
        return f"{s:.0f}s"
    if s < 5400:
        return f"{s / 60:.0f}m"
    if s < 172800:
        return f"{s / 3600:.1f}h"
    return f"{s / 86400:.1f}d"


def condense(s: dict, prompt_chars: int = 2500, reply_chars: int = 1200) -> str:
    out = [f"# {s.get('title') or s['id']}",
           f"id: {s['id']} · source: {s['source']} · surface: {s.get('surface')}",
           f"model: {s.get('model')} · effort: {s.get('effort')} · permission mode: {s.get('permission_mode')}",
           f"repos: {', '.join(s.get('repos') or []) or '-'}",
           f"span: {s.get('created_at')} → {s.get('updated_at')} · turns: {len(s['turns'])}"
           f" · reported cost: {s.get('reported_cost_usd')} · context now: {s.get('reported_context_tokens')}",
           f"last state: {s.get('status')} · needs action: {s.get('needs_action') or '-'}", ""]
    for t in s["turns"]:
        tools = Counter(tc["name"] for tc in t["tools"])
        errs = sum(1 for tc in t["tools"] if tc["is_error"])
        models = ", ".join(f"{m} ${u['cost_usd']:.2f}" for m, u in t["usage"].items())
        out.append(f"## Turn {t['idx']} · {t['started_at'][:16]} · origin={t['origin']} · idle before={_dur(t['gap_before_ms'])}"
                   f" · worked={_dur(t['duration_ms'])} · steps={t['steps']} · status={t['status']}"
                   f" · context={t['context_tokens_at_start']} · {models or 'no usage'}")
        out.append(f"USER: {_clip(t['prompt'], prompt_chars)}")
        if tools:
            top = ", ".join(f"{n}×{c}" for n, c in tools.most_common(8))
            out.append(f"TOOLS ({sum(tools.values())}, {errs} errors): {top}")
        agents = [tc["summary"] for tc in t["tools"] if tc["name"] in ("Agent", "Task", "Workflow") and not tc["in_subagent"]]
        if agents:
            out.append("SUBAGENTS: " + " || ".join(agents[:12]) + (f" (+{len(agents) - 12} more)" if len(agents) > 12 else ""))
        for msg in t["interjections"]:
            out.append(f"USER (mid-turn): {_clip(msg, 600)}")
        if t["final_text"]:
            out.append(f"ASSISTANT (final): {_clip(t['final_text'], reply_chars)}")
        out.append("")
    return "\n".join(out)
