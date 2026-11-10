"""Claude Code run locally: ~/.claude/projects/<project>/<session>.jsonl (one JSON object per line)."""
from __future__ import annotations
import glob, json, os
from ..schema import Session, Turn, ToolCall
from ..timeutil import parse_ts
from ..redact import redact
from .claude_cloud import _human_text, _tool_summary, _classify_origin

SOURCE = "claude-code-local"


def build_session(path: str) -> Session:
    s = Session(id=os.path.splitext(os.path.basename(path))[0], source=SOURCE, surface="cli")
    turn, last_end, pending, seen_msgs = None, None, {}, set()
    for line in open(path, errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        kind, at = d.get("type"), d.get("timestamp")
        if d.get("isSidechain"):
            continue
        if kind == "cost-state":
            s.reported_cost_usd = d.get("totalCostUSD")
            continue
        if kind not in ("user", "assistant") or not at:
            continue
        s.created_at = s.created_at or at
        s.updated_at = at
        if d.get("cwd") and not s.repos:
            s.repos = [d["cwd"]]
        msg = d.get("message") or {}
        if kind == "user":
            text = _human_text(msg)
            if text is None:
                for b in msg.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        tc = pending.pop(b.get("tool_use_id"), None)
                        if tc is not None and b.get("is_error"):
                            tc.is_error = True
                continue
            if d.get("isMeta") or text.strip().startswith("[Request interrupted"):
                if turn is not None and text.strip().startswith("[Request interrupted"):
                    turn.interrupted_by_user += 1
                continue
            origin = _classify_origin(text, d)
            if origin != "human" and turn is not None:
                turn.continuations += 1
                continue
            text, n = redact(text)
            turn = Turn(idx=len(s.turns), started_at=at, prompt=text, origin=origin, secrets_pasted=n)
            a, b = parse_ts(at), last_end
            if a and b:
                turn.gap_before_ms = int((a - b).total_seconds() * 1000)
            s.turns.append(turn)
        else:
            if turn is None:
                turn = Turn(idx=len(s.turns), started_at=at, prompt="", origin="system")
                s.turns.append(turn)
            model = msg.get("model")
            s.model = s.model or model
            eff = d.get("perTurnEffort") or d.get("effort")
            if eff:
                turn.effort = eff
                s.effort = s.effort or eff
            if msg.get("id") and msg["id"] not in seen_msgs and model:
                seen_msgs.add(msg["id"])
                u = msg.get("usage") or {}
                acc = turn.usage.setdefault(model, {"input": 0, "output": 0, "thinking": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 0.0})
                acc["input"] += u.get("input_tokens", 0); acc["output"] += u.get("output_tokens", 0)
                acc["cache_read"] += u.get("cache_read_input_tokens", 0); acc["cache_write"] += u.get("cache_creation_input_tokens", 0)
                turn.steps = (turn.steps or 0) + 1
                if turn.context_tokens_at_start is None:
                    turn.context_tokens_at_start = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
            for b in msg.get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    tc = ToolCall(name=b.get("name", "?"), summary=redact(_tool_summary(b.get("name", ""), b.get("input") or {}))[0])
                    turn.tools.append(tc); pending[b.get("id")] = tc
                elif b.get("type") == "text":
                    turn.final_text = redact(b.get("text", ""))[0]
            turn.ended_at = at
            turn.status = "success"
            a, b = parse_ts(turn.started_at), parse_ts(at)
            if a and b:
                turn.duration_ms = int((b - a).total_seconds() * 1000)
            last_end = parse_ts(at)
    return s


def load_all(claude_home: str) -> list[Session]:
    paths = glob.glob(os.path.join(os.path.expanduser(claude_home), "projects", "*", "*.jsonl"))
    return [build_session(p) for p in sorted(paths)]
