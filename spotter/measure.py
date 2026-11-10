"""Deterministic metrics and detectors. No model calls: everything here is counted."""
from __future__ import annotations
import re, statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from .timeutil import parse_ts as _ts

APPROVAL = re.compile(
    r"^\W*(go|go ahead|yes|yep|yeah|ok|okay|do it|merge|merge it|ship it|proceed|continue|approved?|"
    r"sounds good|looks good|lgtm|perfect|great|yes please|please do|go for it|let'?s do it|run it|"
    r"yes,? (go|merge|do it|proceed)[\w ]*|ok(ay)?,? (go|merge|do it|proceed)[\w ]*)\W*$", re.I)
CORRECTION = re.compile(
    r"\b(that'?s not|not what i|isn'?t what|wrong|i (said|told you|asked)|why did you|why didn'?t you|you didn'?t|"
    r"you (missed|forgot|ignored|broke)|still (not|broken|wrong|doesn'?t|isn'?t|see|have|getting)|doesn'?t work|not working|"
    r"didn'?t work|broken|undo|revert|again\b|never do|stop doing|wtf|fuck|shit|bullshit|terrible|awful|"
    r"no[,.!] |nope|not right|incorrect|try again)\b", re.I)




def size_class(t: dict) -> str:
    steps = t.get("steps") or len(t.get("tools") or [])
    if steps <= 3:
        return "trivial"
    if steps <= 15:
        return "small"
    if steps <= 60:
        return "medium"
    return "large"


def project_of(s: dict) -> str:
    repos = s.get("repos") or []
    return repos[0] if repos else "(no repo)"


def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    return sorted_vals[min(len(sorted_vals) - 1, int(q * len(sorted_vals)))]


def _shingles(text: str, k: int = 3) -> set:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {" ".join(words[i:i + k]) for i in range(max(0, len(words) - k + 1))}


def repeated_prompts(sessions, min_words=5, max_words=80, threshold=0.5, min_sessions=3):
    items = []
    for s in sessions:
        for t in s["turns"]:
            if t["origin"] != "human":
                continue
            n = len(t["prompt"].split())
            if min_words <= n <= max_words:
                sh = _shingles(t["prompt"])
                if sh:
                    items.append((s["id"], t["idx"], t["prompt"], sh))
    clusters, used = [], set()
    for i, (sid, idx, text, sh) in enumerate(items):
        if i in used:
            continue
        group = [(sid, idx, text)]
        for j in range(i + 1, len(items)):
            if j in used:
                continue
            other = items[j][3]
            inter = len(sh & other)
            if inter and inter / len(sh | other) >= threshold:
                group.append(items[j][:3])
                used.add(j)
        if len({g[0] for g in group}) >= min_sessions:
            clusters.append({"count": len(group), "sessions": len({g[0] for g in group}),
                             "examples": [{"session": g[0], "turn": g[1], "text": g[2][:300]} for g in group[:4]]})
    clusters.sort(key=lambda c: -c["count"])
    return clusters[:25]


def measure(sessions: list[dict], now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    human_turns = [(s, t) for s in sessions for t in s["turns"] if t["origin"] == "human"]
    all_turns = [(s, t) for s in sessions for t in s["turns"]]
    m: dict = {}

    dates = sorted(d for d in (_ts(s.get("created_at")) for s in sessions) if d)
    turn_cost = sum(t["cost_usd"] for _, t in all_turns)
    m["overview"] = {
        "sessions": len(sessions), "human_turns": len(human_turns), "all_turns": len(all_turns),
        "first": dates[0].isoformat() if dates else None, "last": dates[-1].isoformat() if dates else None,
        "list_price_cost_usd": round(turn_cost, 2),
        "vendor_reported_cost_usd": round(sum(s.get("reported_cost_usd") or 0 for s in sessions), 2),
        "agent_work_hours": round(sum((t.get("duration_ms") or 0) for _, t in all_turns) / 3.6e6, 1),
        "by_source": dict(Counter(s["source"] for s in sessions)),
        "by_surface": dict(Counter(s.get("surface") or "?" for s in sessions)),
    }

    # --- model and effort ------------------------------------------------
    by_model = defaultdict(lambda: {"cost_usd": 0.0, "output_tokens": 0, "turns": 0})
    for _, t in all_turns:
        for model, u in t["usage"].items():
            b = by_model[model]
            b["cost_usd"] += u["cost_usd"]; b["output_tokens"] += u["output"]; b["turns"] += 1
    m["by_model"] = {k: {**v, "cost_usd": round(v["cost_usd"], 2)} for k, v in
                     sorted(by_model.items(), key=lambda kv: -kv[1]["cost_usd"])}

    combo = defaultdict(lambda: {"sessions": 0, "human_turns": 0, "cost_usd": 0.0, "sizes": Counter(), "durations": defaultdict(list)})
    for s in sessions:
        key = f"{s.get('model') or '?'} @ {s.get('effort') or '?'}"
        c = combo[key]
        c["sessions"] += 1
        for t in s["turns"]:
            c["cost_usd"] += t["cost_usd"]
            if t["origin"] == "human":
                c["human_turns"] += 1
                sc = size_class(t)
                c["sizes"][sc] += 1
                if t.get("duration_ms"):
                    c["durations"][sc].append(t["duration_ms"])
    m["model_effort"] = {}
    for key, c in sorted(combo.items(), key=lambda kv: -kv[1]["cost_usd"]):
        m["model_effort"][key] = {
            "sessions": c["sessions"], "human_turns": c["human_turns"], "cost_usd": round(c["cost_usd"], 2),
            "turn_sizes": dict(c["sizes"]),
            "median_seconds_by_size": {k: round(statistics.median(v) / 1000, 1) for k, v in c["durations"].items()},
        }
    sizes = Counter(size_class(t) for _, t in human_turns)
    m["turn_sizes"] = dict(sizes)
    cost_by_size = defaultdict(float)
    for _, t in human_turns:
        cost_by_size[size_class(t)] += t["cost_usd"]
    m["cost_by_turn_size"] = {k: round(v, 2) for k, v in cost_by_size.items()}

    # --- approvals and waiting -------------------------------------------
    approvals = [(s, t) for s, t in human_turns if APPROVAL.match(t["prompt"].strip()) and len(t["prompt"]) < 60]
    waits = sorted((t["gap_before_ms"] or 0) for _, t in approvals if t["gap_before_ms"])
    m["approvals"] = {
        "count": len(approvals), "share_of_human_turns": round(len(approvals) / max(1, len(human_turns)), 3),
        "median_wait_minutes": round(statistics.median(waits) / 60000, 1) if waits else None,
        "total_wait_hours": round(sum(waits) / 3.6e6, 1),
        "phrases": dict(Counter(t["prompt"].strip().lower().rstrip(".!") for _, t in approvals).most_common(12)),
        "by_project": dict(Counter(project_of(s) for s, _ in approvals).most_common(8)),
    }
    durs = sorted(t["duration_ms"] for _, t in human_turns if t.get("duration_ms"))
    m["turn_duration"] = {
        "median_seconds": round(_pct(durs, 0.5) / 1000, 1) if durs else None,
        "p90_minutes": round(_pct(durs, 0.9) / 60000, 1) if durs else None,
        "max_hours": round(durs[-1] / 3.6e6, 2) if durs else None,
        "over_30_min": sum(1 for d in durs if d > 1.8e6), "over_2_hours": sum(1 for d in durs if d > 7.2e6),
    }
    gaps = sorted(t["gap_before_ms"] for _, t in human_turns if t.get("gap_before_ms") and t["gap_before_ms"] > 0)
    m["human_response_gap"] = {
        "median_minutes": round(_pct(gaps, 0.5) / 60000, 1) if gaps else None,
        "under_2_min_share": round(sum(1 for g in gaps if g < 120000) / max(1, len(gaps)), 3),
        "over_1_hour_share": round(sum(1 for g in gaps if g > 3.6e6) / max(1, len(gaps)), 3),
    }

    # --- context ----------------------------------------------------------
    ctx = sorted(t["context_tokens_at_start"] for _, t in all_turns if t.get("context_tokens_at_start"))
    heavy = defaultdict(lambda: {"turns_over_300k": 0, "cost_over_300k": 0.0, "peak": 0, "title": ""})
    for s, t in all_turns:
        c = t.get("context_tokens_at_start") or 0
        h = heavy[s["id"]]
        h["title"] = s.get("title", "")
        h["peak"] = max(h["peak"], c)
        if c > 300_000:
            h["turns_over_300k"] += 1; h["cost_over_300k"] += t["cost_usd"]
    cost_over = sum(h["cost_over_300k"] for h in heavy.values())
    spans = []
    for s in sessions:
        a, b = _ts(s.get("created_at")), _ts(s.get("updated_at"))
        if a and b:
            spans.append({"id": s["id"], "title": s.get("title", ""), "days": round((b - a).total_seconds() / 86400, 1),
                          "turns": len(s["turns"]), "peak_context": heavy[s["id"]]["peak"],
                          "cost_usd": round(sum(t["cost_usd"] for t in s["turns"]), 2)})
    m["context"] = {
        "median_tokens_at_turn_start": _pct(ctx, 0.5), "p90_tokens_at_turn_start": _pct(ctx, 0.9),
        "turns_starting_over_300k": sum(1 for c in ctx if c > 300_000),
        "share_of_turns_over_300k": round(sum(1 for c in ctx if c > 300_000) / max(1, len(ctx)), 3),
        "cost_usd_of_turns_over_300k": round(cost_over, 2),
        "share_of_cost_over_300k": round(cost_over / max(0.01, turn_cost), 3),
        "compactions": sum(t.get("compactions", 0) for _, t in all_turns),
        "heaviest_sessions": sorted(
            ({"id": k, "title": v["title"], "peak": v["peak"], "turns_over_300k": v["turns_over_300k"],
              "cost_over_300k": round(v["cost_over_300k"], 2)} for k, v in heavy.items() if v["turns_over_300k"]),
            key=lambda x: -x["cost_over_300k"])[:12],
        "longest_lived_sessions": sorted(spans, key=lambda x: -x["days"])[:12],
    }

    # --- friction ---------------------------------------------------------
    corr = [(s, t) for s, t in human_turns if t["idx"] > 0 and CORRECTION.search(t["prompt"][:600])]
    by_sess = Counter(s["id"] for s, _ in corr)
    m["friction"] = {
        "correction_candidates": len(corr),
        "share_of_human_turns": round(len(corr) / max(1, len(human_turns)), 3),
        "mid_turn_interjections": sum(len(t["interjections"]) for _, t in all_turns),
        "turns_errored": sum(1 for _, t in all_turns if t["status"] == "error"),
        "user_interruptions": sum(t.get("interrupted_by_user", 0) for _, t in all_turns),
        "tool_calls": sum(len(t["tools"]) for _, t in all_turns),
        "tool_errors": sum(1 for _, t in all_turns for tc in t["tools"] if tc["is_error"]),
        "permission_denials": sum(t.get("permission_denials", 0) for _, t in all_turns),
        "sessions_with_most_corrections": [
            {"id": sid, "count": n, "title": next(s.get("title", "") for s in sessions if s["id"] == sid)}
            for sid, n in by_sess.most_common(8)],
        "examples": [{"session": s["id"], "turn": t["idx"], "text": t["prompt"][:240]} for s, t in corr[:40]],
    }

    # --- delegation -------------------------------------------------------
    tools = Counter(tc["name"] for _, t in all_turns for tc in t["tools"] if not tc["in_subagent"])
    mcp = Counter(n.split("__")[1] for n in tools.elements() if n.startswith("mcp__") and n.count("__") >= 2)
    fan = sorted(({"session": s["id"], "title": s.get("title", ""), "turn": t["idx"], "spawned": t["subagents_spawned"],
                   "cost_usd": round(t["cost_usd"], 2), "types": t["subagent_types"]}
                  for s, t in all_turns if t["subagents_spawned"]), key=lambda x: -x["spawned"])
    m["delegation"] = {
        "top_tools": dict(tools.most_common(20)), "connectors_used": dict(mcp.most_common(12)),
        "skills_invoked": dict(Counter(tc["summary"] for _, t in all_turns for tc in t["tools"] if tc["name"] == "Skill").most_common(12)),
        "subagents_spawned": sum(t["subagents_spawned"] for _, t in all_turns),
        "turns_with_subagents": len(fan), "cost_usd_of_turns_with_subagents": round(sum(f["cost_usd"] for f in fan), 2),
        "largest_fanouts": fan[:10],
        "workflow_runs": tools.get("Workflow", 0),
        "permission_modes": dict(Counter(s.get("permission_mode") or "?" for s in sessions)),
        "child_sessions": sum(1 for s in sessions if s.get("parent_id")),
    }

    # --- cold turns: a big context left idle past the cache window is re-read in full on the next message ----
    cold = [(s, t) for s, t in human_turns if (t.get("gap_before_ms") or 0) > 3.6e6 and (t.get("context_tokens_at_start") or 0) > 300_000]
    quick_cold = [(s, t) for s, t in cold if size_class(t) in ("trivial", "small")]
    m["cold_turns"] = {
        "count": len(cold), "cost_usd": round(sum(t["cost_usd"] for _, t in cold), 2),
        "quick_asks": len(quick_cold), "quick_asks_cost_usd": round(sum(t["cost_usd"] for _, t in quick_cold), 2),
        "examples": sorted(({"session": s["id"], "title": s.get("title", ""), "turn": t["idx"],
                             "idle_hours": round(t["gap_before_ms"] / 3.6e6, 1), "context": t["context_tokens_at_start"],
                             "cost_usd": round(t["cost_usd"], 2), "steps": t.get("steps"), "prompt": t["prompt"][:140]}
                            for s, t in quick_cold), key=lambda x: -x["cost_usd"])[:10]}
    m["secrets_pasted"] = [{"session": s["id"], "title": s.get("title", ""), "turn": t["idx"], "at": t["started_at"][:10],
                            "count": t["secrets_pasted"]} for s, t in all_turns if t.get("secrets_pasted")]
    sched = defaultdict(int)
    for s, t in all_turns:
        n = sum(1 for tc in t["tools"] if tc["name"].endswith("send_later"))
        if n:
            sched[t["started_at"][:7]] += n
    m["self_scheduled_checkins_by_month"] = dict(sorted(sched.items()))

    # --- wake-up loops: work that kept resuming on a timer or event after the human left ----
    loops = []
    for s, t in all_turns:
        if t.get("continuations", 0) >= 5:
            a, b = _ts(t["started_at"]), _ts(t.get("ended_at"))
            loops.append({"session": s["id"], "title": s.get("title", ""), "turn": t["idx"], "wakeups": t["continuations"],
                          "span_hours": round((b - a).total_seconds() / 3600, 1) if a and b else None,
                          "cost_usd": round(t["cost_usd"], 2), "model": s.get("model"), "effort": s.get("effort"),
                          "context_peak": t.get("context_tokens_peak"), "prompt": t["prompt"][:160]})
    m["wakeup_loops"] = {"count": len(loops), "wakeups": sum(l["wakeups"] for l in loops),
                         "cost_usd": round(sum(l["cost_usd"] for l in loops), 2),
                         "items": sorted(loops, key=lambda l: -l["wakeups"])[:12]}
    m["unreconciled_cost"] = [
        {"id": s["id"], "title": s.get("title", ""), "per_turn_sum": round(sum(t["cost_usd"] for t in s["turns"]), 2),
         "vendor_total": round(s["reported_cost_usd"], 2), "partial_export": bool(s.get("meta", {}).get("partial"))}
        for s in sessions if s.get("reported_cost_usd") and
        abs(s["reported_cost_usd"] - sum(t["cost_usd"] for t in s["turns"])) > max(5, 0.15 * s["reported_cost_usd"])]

    # --- open loops ---------------------------------------------------------
    stale = []
    for s in sessions:
        if s.get("status") == "blocked" and s.get("needs_action"):
            u = _ts(s.get("updated_at"))
            stale.append({"id": s["id"], "title": s.get("title", ""), "needs_action": s["needs_action"][:200],
                          "days_waiting": round((now - u).total_seconds() / 86400, 1) if u else None})
    m["open_loops"] = sorted(stale, key=lambda x: -(x["days_waiting"] or 0))

    # --- projects and timeline -------------------------------------------
    proj = defaultdict(lambda: {"sessions": 0, "human_turns": 0, "cost_usd": 0.0, "hours": 0.0})
    for s in sessions:
        p = proj[project_of(s)]
        p["sessions"] += 1
        for t in s["turns"]:
            p["cost_usd"] += t["cost_usd"]; p["hours"] += (t.get("duration_ms") or 0) / 3.6e6
            p["human_turns"] += t["origin"] == "human"
    m["projects"] = {k: {**v, "cost_usd": round(v["cost_usd"], 2), "hours": round(v["hours"], 1)}
                     for k, v in sorted(proj.items(), key=lambda kv: -kv[1]["cost_usd"])}
    weeks = defaultdict(lambda: {"human_turns": 0, "cost_usd": 0.0, "hours": 0.0, "sessions": set()})
    for s, t in all_turns:
        d = _ts(t["started_at"])
        if not d:
            continue
        iso = d.isocalendar()
        w = weeks[f"{iso[0]}-W{iso[1]:02d}"]
        w["human_turns"] += t["origin"] == "human"; w["cost_usd"] += t["cost_usd"]
        w["hours"] += (t.get("duration_ms") or 0) / 3.6e6; w["sessions"].add(s["id"])
    m["weekly"] = {k: {"human_turns": v["human_turns"], "cost_usd": round(v["cost_usd"], 2),
                       "hours": round(v["hours"], 1), "sessions": len(v["sessions"])} for k, v in sorted(weeks.items())}
    peaks = defaultdict(float)
    for s in sessions:
        for w, u in (s.get("meta", {}).get("limit_utilization_peak") or {}).items():
            peaks[w] = max(peaks[w], u)
    m["limits"] = {"peak_utilization": dict(peaks), "sessions_using_overage": sum(1 for s in sessions if s.get("meta", {}).get("used_overage"))}
    m["repeated_prompts"] = repeated_prompts(sessions)
    m["prompt_length_words"] = {
        "median": _pct(sorted(len(t["prompt"].split()) for _, t in human_turns), 0.5),
        "p90": _pct(sorted(len(t["prompt"].split()) for _, t in human_turns), 0.9),
        "under_10_words_share": round(sum(1 for _, t in human_turns if len(t["prompt"].split()) < 10) / max(1, len(human_turns)), 3),
    }
    return m
