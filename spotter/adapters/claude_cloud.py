"""Claude Code cloud sessions (claude.ai/code and the Claude app's Code tab).

Input: a directory per session holding exported event pages
(`{"data": [event, ...], "first_id": ..., "has_more": ...}`) and, optionally,
`_session.json` with the session record. Output: a normalized Session.
"""
from __future__ import annotations
import glob, json, os
from datetime import datetime
from ..schema import Session, Turn, ToolCall
from ..timeutil import parse_ts as _ts
from ..redact import redact

SOURCE = "claude-code-cloud"




def _unwrap(ev: dict) -> tuple[str, dict, str | None]:
    kind = next((k for k in ev if k != "created_at"), "")
    body = ev.get(kind) or {}
    if kind == "internal_anthropic_catchall":
        return "other", body, body.get("uuid")
    payload = body.get("internal_anthropic_catchall", body) if isinstance(body, dict) else {}
    return kind, payload, (body.get("uuid") if isinstance(body, dict) else None) or payload.get("uuid")


def load_events(session_dir: str) -> list[dict]:
    seen, out = set(), []
    for path in glob.glob(os.path.join(session_dir, "*.json")):
        if os.path.basename(path).startswith("_"):
            continue
        try:
            page = json.load(open(path))
        except (OSError, ValueError):
            continue
        for ev in page.get("data", []):
            kind, payload, uuid = _unwrap(ev)
            key = uuid or (kind, ev.get("created_at"), json.dumps(payload, sort_keys=True)[:200])
            if key in seen:
                continue
            seen.add(key)
            out.append({"at": ev.get("created_at"), "kind": kind, "p": payload})
    out.sort(key=lambda e: e["at"] or "")
    return out


def _human_text(message: dict) -> str | None:
    """Return the typed text if this user message came from a person, else None."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        parts = []
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif b.get("type") in ("image", "document"):
                parts.append(f"[{b['type']} attached]")
        return "\n".join(parts) if parts else None
    return None


def _tool_summary(name: str, inp: dict) -> str:
    if not isinstance(inp, dict):
        return ""
    if name == "Bash":
        return (inp.get("description") or inp.get("command") or "")[:160]
    if name in ("Read", "Edit", "Write", "NotebookEdit"):
        return str(inp.get("file_path", ""))[-120:]
    if name in ("Grep", "Glob"):
        return str(inp.get("pattern", ""))[:120]
    if name in ("Agent", "Task"):
        bits = [inp.get("subagent_type") or "general", inp.get("model") or "", inp.get("description") or ""]
        return " | ".join(b for b in bits if b)[:160]
    if name == "Skill":
        return str(inp.get("skill", ""))
    if name == "Workflow":
        return str(inp.get("name") or "inline script")
    for k in ("query", "url", "description", "prompt", "title"):
        if inp.get(k):
            return str(inp[k])[:120]
    return ""


def _classify_origin(text: str, payload: dict) -> str:
    t = text.lstrip()
    if t.startswith("<wake") or t.startswith("<event") or "<webhook-payload" in t[:200]:
        return "system"
    if t.startswith(("<task-notification", "<system-reminder", "<github-webhook-activity", "<local-command-stdout",
                     "<local-command-stderr", "<command-name", "<command-message", "<bash-", "[SYSTEM NOTIFICATION")):
        return "system"
    if "scheduled" in str(payload.get("origin", "")).lower() or t.startswith("<scheduled"):
        return "scheduled"
    if t.startswith("<cross-session") or t.startswith("<peer-session") or t.startswith("<session-message"):
        return "peer"
    return "human"


def build_session(session_dir: str, record: dict | None = None) -> Session:
    sid = os.path.basename(session_dir.rstrip("/"))
    rec = record or {}
    meta_path = os.path.join(session_dir, "_session.json")
    if not rec and os.path.exists(meta_path):
        rec = json.load(open(meta_path))
    ctx = rec.get("session_context") or {}
    ext = rec.get("external_metadata") or {}
    pts = rec.get("post_turn_summary") or ext.get("post_turn_summary") or {}
    s = Session(
        id=sid, source=SOURCE,
        title=rec.get("title", ""), surface=rec.get("origin", ""),
        created_at=rec.get("created_at"), updated_at=rec.get("updated_at"),
        repos=[(src.get("git_repository") or {}).get("url", "").replace("https://github.com/", "")
               for src in ctx.get("sources", []) if src.get("git_repository")],
        model=ctx.get("model") or rec.get("configured_model"),
        effort=ctx.get("effort_level"),
        permission_mode=ctx.get("permission_mode"),
        parent_id=rec.get("parent_session_id"),
        status=(rec.get("status_bucket") or "").replace("SESSION_STATUS_BUCKET_", "").lower() or None,
        needs_action=pts.get("needs_action") or None,
        reported_cost_usd=(ext.get("usage") or {}).get("cost_usd"),
        reported_context_tokens=(ext.get("context_usage") or {}).get("used_tokens"),
    )
    s.meta["reported_usage"] = ext.get("usage") or {}
    s.meta["environment_kind"] = rec.get("environment_kind")
    s.meta["tags"] = rec.get("tags") or []

    events = load_events(session_dir)
    s.meta["event_count"] = len(events)
    s.meta["partial"] = not os.path.exists(os.path.join(session_dir, "_complete"))
    turn: Turn | None = None          # the current human ask and all work that followed it
    working = False                   # is the tool mid-run right now?
    last_end: datetime | None = None
    pending_tools: dict[str, ToolCall] = {}
    effort_now = s.effort
    prev_cum: dict[str, dict] | None = None
    first_result = True

    def open_turn(at: str, text: str, origin: str) -> Turn:
        nonlocal turn
        t = Turn(idx=len(s.turns), started_at=at, prompt=text, origin=origin, effort=effort_now)
        start = _ts(at)
        if last_end and start:
            t.gap_before_ms = int((start - last_end).total_seconds() * 1000)
        s.turns.append(t)
        turn = t
        return t

    for ev in events:
        kind, p, at = ev["kind"], ev["p"], ev["at"]
        if kind == "user":
            msg = p.get("message") or {}
            if p.get("parent_tool_use_id"):
                continue  # traffic inside a subagent
            text = _human_text(msg)
            if text is not None:
                if p.get("isSynthetic") or p.get("is_synthetic"):
                    continue
                if text.strip().startswith("[Request interrupted by user"):
                    if turn is not None:
                        turn.interrupted_by_user += 1
                    working = False
                    continue
                origin = _classify_origin(text, p)
                if origin != "human":
                    # background-task notices, PR events, scheduled wake-ups: work continues on the same ask
                    if turn is None:
                        open_turn(at, text, origin)
                    else:
                        turn.continuations += 1
                    working = True
                elif turn is not None and working and turn.origin == "human":
                    turn.interjections.append(text)
                else:
                    open_turn(at, text, origin)
                    working = True
            else:
                for b in msg.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        tc = pending_tools.pop(b.get("tool_use_id"), None)
                        if tc is not None and b.get("is_error"):
                            tc.is_error = True
        elif kind == "assistant":
            msg = p.get("message") or {}
            in_sub = bool(p.get("parent_tool_use_id"))
            if turn is None:
                open_turn(at, "", "system")
            working = True
            for b in msg.get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    tc = ToolCall(name=b.get("name", "?"), summary=_tool_summary(b.get("name", ""), b.get("input") or {}),
                                  in_subagent=in_sub)
                    turn.tools.append(tc)
                    pending_tools[b.get("id")] = tc
                elif b.get("type") == "text" and not in_sub:
                    turn.final_text = b.get("text", "")   # last text block wins
        elif kind == "result":
            if turn is None:
                open_turn(at, "", "system")
            turn.ended_at = at
            sub = p.get("subtype") or ""
            ok = sub == "success" and not p.get("is_error")
            turn.status = "success" if ok else (
                "interrupted" if "interrupt" in str(p.get("terminal_reason", "")) + sub else "error")
            if not ok:
                turn.failed_runs += 1
            turn.duration_ms = (turn.duration_ms or 0) + int(p.get("duration_ms") or 0)
            turn.steps = (turn.steps or 0) + int(p.get("num_turns") or 0)
            if isinstance(p.get("result"), str) and p["result"]:
                turn.final_text = p["result"]
            cum = p.get("modelUsage") or {}
            usage = p.get("model_usage_since_last_result")
            if usage is None:
                if prev_cum is None and s.meta["partial"] and first_result:
                    usage = {}        # history before this page is missing; a delta is not computable
                else:
                    usage = {}
                    for model, u in cum.items():
                        before = (prev_cum or {}).get(model) or {}
                        d = {k: (v - before.get(k, 0)) for k, v in u.items() if isinstance(v, (int, float))}
                        if any(v < -1e-9 for v in d.values()):       # counters restarted; this run's share is unknowable
                            s.meta["cost_gaps"] = s.meta.get("cost_gaps", 0) + 1
                            continue
                        if d.get("costUSD", 0) > 1e-9 or d.get("outputTokens", 0) > 0:
                            usage[model] = d
            prev_cum = cum or prev_cum
            first_result = False
            for model, u in usage.items():
                acc = turn.usage.setdefault(model, {"input": 0, "output": 0, "thinking": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 0.0})
                acc["input"] += u.get("inputTokens", 0); acc["output"] += u.get("outputTokens", 0)
                acc["thinking"] += u.get("thinkingTokens", 0)
                acc["cache_read"] += u.get("cacheReadInputTokens", 0)
                acc["cache_write"] += u.get("cacheCreationInputTokens", 0)
                acc["cost_usd"] += u.get("costUSD", 0.0)
            turn.cost_usd = round(sum(u["cost_usd"] for u in turn.usage.values()), 6)
            fr = p.get("first_request_input_tokens")
            if fr is not None and turn.context_tokens_at_start is None:
                turn.context_tokens_at_start = int(fr)
            if fr is not None:
                turn.context_tokens_peak = max(turn.context_tokens_peak or 0, int(fr))
            ss = p.get("subagent_stats") or {}
            turn.subagents_spawned += int(ss.get("spawned") or 0)
            for k, v in (ss.get("by_type") or {}).items():
                n = v.get("spawned", 0) if isinstance(v, dict) else v
                if isinstance(n, (int, float)):
                    turn.subagent_types[k] = turn.subagent_types.get(k, 0) + int(n)
            turn.permission_denials += len(p.get("permission_denials") or [])
            last_end = _ts(at)
            pending_tools.clear()
            working = False
        elif kind == "system":
            sub = p.get("subtype")
            if sub == "compact_boundary" and turn is not None:
                turn.compactions += 1
            elif sub in ("model_fallback", "model_refusal_fallback"):
                s.meta.setdefault("fallbacks", []).append(
                    {"at": at, "from": p.get("original_model"), "to": p.get("fallback_model"), "kind": sub})
            elif sub == "init":
                if p.get("model"):
                    s.meta.setdefault("models_seen", [])
                    if p["model"] not in s.meta["models_seen"]:
                        s.meta["models_seen"].append(p["model"])
                    if not s.model:
                        s.model = p["model"]
        elif kind == "control_request":
            req = p.get("request") or {}
            if "effort" in str(req.get("subtype", "")) or "effort" in req:
                effort_now = req.get("effort") or req.get("level") or req.get("effort_level") or effort_now
                s.meta.setdefault("effort_changes", []).append({"at": at, "to": effort_now})
            if req.get("subtype") == "set_model" and req.get("model"):
                s.meta.setdefault("model_switches", []).append({"at": at, "to": req["model"]})
        elif kind == "rate_limit_event":
            info = p.get("rate_limit_info") or {}
            for window, w in (info.get("unifiedWindows") or {}).items():
                u = w.get("utilization")
                if isinstance(u, (int, float)):
                    peak = s.meta.setdefault("limit_utilization_peak", {})
                    peak[window] = max(peak.get(window, 0), u)
            if info.get("isUsingOverage"):
                s.meta["used_overage"] = True
        elif kind == "other":
            if p.get("type") == "compaction" and turn is not None:
                turn.compactions += 1

    for t in s.turns:
        t.prompt, n1 = redact(t.prompt)
        t.final_text, n2 = redact(t.final_text)
        cleaned = [redact(x) for x in t.interjections]
        t.interjections = [c[0] for c in cleaned]
        t.secrets_pasted = n1 + sum(c[1] for c in cleaned)
        for tc in t.tools:
            tc.summary = redact(tc.summary)[0]
    if not s.created_at and events:
        s.created_at = events[0]["at"]
    if not s.updated_at and events:
        s.updated_at = events[-1]["at"]
    return s
