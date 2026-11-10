"""Plain chat apps, from each vendor's own data export (Settings -> export data -> conversations.json).

UNVERIFIED: written from the documented export shapes, not yet run against a real export.
Chat exports carry no cost or effort data; ChatGPT's carries the model per message, Claude's does not.
"""
from __future__ import annotations
import json
from ..schema import Session, Turn
from ..timeutil import parse_ts
from ..redact import redact


def _finish(s: Session, pairs: list[tuple]) -> Session:
    """pairs: (role, text, timestamp, model) in order."""
    turn, last_end = None, None
    for role, text, at, model in pairs:
        iso = parse_ts(at).isoformat() if parse_ts(at) else None
        if role == "user":
            text, n = redact(text)
            turn = Turn(idx=len(s.turns), started_at=iso or "", prompt=text, secrets_pasted=n)
            if last_end and parse_ts(at):
                turn.gap_before_ms = int((parse_ts(at) - last_end).total_seconds() * 1000)
            s.turns.append(turn)
        elif role == "assistant" and turn is not None:
            turn.final_text = redact(text)[0]
            turn.ended_at, turn.status, turn.steps = iso, "success", (turn.steps or 0) + 1
            if model:
                s.model = s.model or model
                turn.usage.setdefault(model, {"input": 0, "output": 0, "thinking": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 0.0})
            a, b = parse_ts(turn.started_at), parse_ts(at)
            if a and b:
                turn.duration_ms = int((b - a).total_seconds() * 1000)
                last_end = b
    return s


def load_chatgpt(path: str) -> list[Session]:
    out = []
    for c in json.load(open(path)):
        s = Session(id=str(c.get("conversation_id") or c.get("id")), source="chatgpt", title=c.get("title") or "", surface="chatgpt")
        t0, t1 = parse_ts(c.get("create_time")), parse_ts(c.get("update_time"))
        s.created_at, s.updated_at = (t0.isoformat() if t0 else None), (t1.isoformat() if t1 else None)
        mapping = c.get("mapping") or {}
        node, chain = c.get("current_node"), []
        while node and node in mapping:                     # walk the live branch from leaf to root
            chain.append(mapping[node]); node = mapping[node].get("parent")
        pairs = []
        for n in reversed(chain):
            msg = n.get("message") or {}
            role = (msg.get("author") or {}).get("role")
            parts = (msg.get("content") or {}).get("parts") or []
            text = "\n".join(p if isinstance(p, str) else "[attachment]" for p in parts)
            if role in ("user", "assistant") and text.strip():
                pairs.append((role, text, msg.get("create_time"), (msg.get("metadata") or {}).get("model_slug")))
        out.append(_finish(s, pairs))
    return out


def load_claude(path: str) -> list[Session]:
    out = []
    for c in json.load(open(path)):
        s = Session(id=str(c.get("uuid")), source="claude-chat", title=c.get("name") or "", surface="claude.ai",
                    created_at=c.get("created_at"), updated_at=c.get("updated_at"))
        pairs = [("user" if m.get("sender") == "human" else "assistant", m.get("text") or "", m.get("created_at"), None)
                 for m in c.get("chat_messages") or [] if (m.get("text") or "").strip()]
        out.append(_finish(s, pairs))
    return out
