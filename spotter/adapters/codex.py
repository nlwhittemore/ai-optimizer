"""OpenAI Codex (CLI and desktop app): ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl.

UNVERIFIED: written from the published rollout format, not yet run against a real file.
Each line is {"timestamp", "type", "payload"}; types used here: session_meta, turn_context,
response_item (message / function_call / function_call_output), event_msg (token_count).
"""
from __future__ import annotations
import glob, json, os
from ..schema import Session, Turn, ToolCall
from ..timeutil import parse_ts
from ..redact import redact

SOURCE = "codex"


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") in ("input_text", "output_text", "text"))


def build_session(path: str) -> Session:
    s = Session(id=os.path.splitext(os.path.basename(path))[0], source=SOURCE, surface="codex")
    turn, last_end = None, None
    for line in open(path, errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        at, kind, p = d.get("timestamp"), d.get("type"), d.get("payload") or {}
        s.created_at = s.created_at or at
        s.updated_at = at or s.updated_at
        if kind == "session_meta":
            s.repos = [p.get("cwd")] if p.get("cwd") else []
            s.meta["cli_version"] = p.get("cli_version")
        elif kind == "turn_context":
            s.model = p.get("model") or s.model
            s.effort = p.get("effort") or p.get("reasoning_effort") or s.effort
            if turn is not None:
                turn.effort = s.effort
        elif kind == "response_item":
            t = p.get("type")
            if t == "message" and p.get("role") == "user":
                text = _text(p.get("content"))
                if not text.strip() or text.lstrip().startswith(("<environment_context", "<user_instructions")):
                    continue
                text, n = redact(text)
                turn = Turn(idx=len(s.turns), started_at=at, prompt=text, effort=s.effort, secrets_pasted=n)
                a = parse_ts(at)
                if a and last_end:
                    turn.gap_before_ms = int((a - last_end).total_seconds() * 1000)
                s.turns.append(turn)
            elif turn is not None and t == "message" and p.get("role") == "assistant":
                turn.final_text = redact(_text(p.get("content")))[0]
                turn.ended_at, turn.status = at, "success"
                turn.steps = (turn.steps or 0) + 1
                a, b = parse_ts(turn.started_at), parse_ts(at)
                if a and b:
                    turn.duration_ms = int((b - a).total_seconds() * 1000)
                last_end = b
            elif turn is not None and t in ("function_call", "local_shell_call", "custom_tool_call"):
                turn.tools.append(ToolCall(name=p.get("name") or t, summary=redact(str(p.get("arguments") or p.get("action") or ""))[0][:160]))
        elif kind == "event_msg" and p.get("type") == "token_count" and turn is not None:
            info = (p.get("info") or {}).get("last_token_usage") or {}
            if info and s.model:
                acc = turn.usage.setdefault(s.model, {"input": 0, "output": 0, "thinking": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 0.0})
                acc["input"] += info.get("input_tokens", 0); acc["output"] += info.get("output_tokens", 0)
                acc["thinking"] += info.get("reasoning_output_tokens", 0); acc["cache_read"] += info.get("cached_input_tokens", 0)
                if turn.context_tokens_at_start is None:
                    turn.context_tokens_at_start = info.get("input_tokens", 0)
    return s


def load_all(codex_home: str) -> list[Session]:
    paths = glob.glob(os.path.join(os.path.expanduser(codex_home), "sessions", "**", "rollout-*.jsonl"), recursive=True)
    return [build_session(p) for p in sorted(paths)]
