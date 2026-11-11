"""Live coach. Runs inside a Claude Code session as a hook and intervenes while you work.

  python3 -m spotter.live prompt   <- UserPromptSubmit: look at the ask before the model does
  python3 -m spotter.live stop     <- Stop: log the finished turn

Reads the hook payload on stdin and the session's own transcript. Fast (no model call, no network).
At most one note per ask, each kind at most once per session, silent when there is nothing worth saying.
Type "coach off" / "coach on" in any message to mute or unmute it for the session.
"""
from __future__ import annotations
import json, os, re, sys, time
from .redact import redact
from .timeutil import parse_ts

HOME = os.environ.get("SPOTTER_DATA") or os.path.expanduser("~/.spotter")
PROFILE = os.environ.get("SPOTTER_PROFILE") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "profiles", "default.json")
CACHE_MINUTES = 60          # idle time after which a large context is re-read at full price
QUICK_WORDS = 14
QUESTION = re.compile(r"^(is|are|was|were|do|does|did|can|could|should|would|will|where|what|when|why|how|which|who)\b|\?\s*$", re.I)
CORRECTION = re.compile(
    r"\b(that'?s not|not what i|wrong|i (said|told you|asked)|why did you|why didn'?t you|you didn'?t|you (missed|forgot|ignored)|"
    r"still (not|broken|wrong)|stop doing|never do|wtf|fuck|shit|dead wrong|you'?re focusing on)\b|\bno[,.!] ", re.I)

BRIEF = (
    "A live coach is attached to this session at the user's request. Its job is to improve how the user works with AI "
    "while they are doing it. Two duties, both brief:\n"
    "1. If a COACH NOTE appears below, open your reply with it on its own line, starting with '**Coach:**', in one or two "
    "plain sentences. Keep its facts and numbers; you may tighten the wording. Then do the work as asked.\n"
    "2. Whether or not there is a note: if this ask is missing something you would otherwise have to guess (what done looks "
    "like, who it is for, where the output goes, what must not change), or it would clearly be better served by a different "
    "effort level, a different model, or a fresh session, say so in one '**Coach:**' line at the top and say what you are "
    "assuming. Do this only when it would change the result. Most asks need no comment; say nothing then. Never lecture, "
    "never repeat a point already made in this session."
)


def _load(path, default):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def session_facts(transcript_path: str) -> dict:
    f = {"context": None, "model": None, "effort": None, "last_activity": None, "human_asks": 0, "prior": []}
    try:
        lines = open(transcript_path, errors="replace")
    except OSError:
        return f
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("isSidechain"):
            continue
        msg = d.get("message") or {}
        if d.get("type") == "assistant":
            u = msg.get("usage") or {}
            ctx = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
            if ctx:
                f["context"] = ctx
            f["model"] = msg.get("model") or f["model"]
            f["effort"] = d.get("perTurnEffort") or d.get("effort") or f["effort"]
            f["last_activity"] = d.get("timestamp") or f["last_activity"]
        elif d.get("type") == "user" and isinstance(msg.get("content"), str):
            text = msg["content"].strip()
            if text and not text.startswith(("<", "[")):
                f["human_asks"] += 1
                f["prior"].append(text[:400])
    return f


def notes_for(prompt: str, facts: dict, profile: dict, shown: set) -> list[tuple[str, str]]:
    """Return candidate (id, note) pairs, highest priority first."""
    out = []
    words = len(prompt.split())
    ctx = facts.get("context") or 0
    last = parse_ts(facts.get("last_activity"))
    idle_min = (time.time() - last.timestamp()) / 60 if last else 0
    quick = words <= QUICK_WORDS
    effort = (facts.get("effort") or "").lower()

    _, secrets = redact(prompt)
    if secrets:
        out.append(("secret", "That message contains what looks like an API key or token. It is now stored in this conversation. "
                              "Rotate it when you are done, and next time ask for the credential form so the value never enters the chat."))
    for rule in profile.get("standing_instructions", []):
        if re.search(rule["pattern"], prompt, re.I) and words <= rule.get("max_words", 12):
            out.append(("rule:" + rule["id"], rule["note"]))
    if CORRECTION.search(prompt[:500]) and facts["human_asks"] >= 1:
        out.append(("correction", "This reads as a correction. Before fixing it, state in one line which instruction was missing or ignored, "
                                  "then offer the one-line rule that would have prevented it and where it should be saved (CLAUDE.md or a brief) "
                                  "so the next session starts with it."))
    if ctx > 300_000 and idle_min > CACHE_MINUTES:
        hrs = idle_min / 60
        out.append(("cold", f"This conversation holds about {ctx // 1000}k tokens and has been idle for {hrs:.0f} hour{'s' if hrs >= 1.5 else ''}, "
                            "so this message re-reads all of it at full price and full latency. If this is a new piece of work, "
                            "a fresh session started from a short brief will be faster and sharper."))
    elif ctx > 500_000:
        out.append(("heavy", f"This conversation is at about {ctx // 1000}k tokens. Instructions from early on are now competing with recent ones. "
                             "Consider writing the current state to a file and continuing in a fresh session."))
    if quick and effort in ("xhigh", "max") and (QUESTION.search(prompt.strip()) or words <= 5):
        out.append(("effort-high", f"Quick ask at {effort} effort. For questions and one-step asks like this, a lower effort setting answers "
                                   "in a fraction of the time with no visible difference; keep the top setting for builds."))
    if words >= 120 and effort in ("low", "medium"):
        out.append(("effort-low", f"This is a substantial ask and the session is at {effort} effort. Raise it before sending work like this."))
    return [(i, n) for i, n in out if i not in shown]


def on_prompt(payload: dict) -> dict | None:
    prompt = payload.get("prompt") or ""
    sid = payload.get("session_id") or "unknown"
    os.makedirs(HOME, exist_ok=True)
    state_path = os.path.join(HOME, f"live-{sid}.json")
    state = _load(state_path, {"shown": [], "muted": False})
    low = prompt.lower()
    if "coach off" in low:
        state["muted"] = True
    elif "coach on" in low:
        state["muted"] = False
    facts = session_facts(payload.get("transcript_path") or "")
    profile = _load(PROFILE, {})
    picked = None
    if not state["muted"] and not prompt.lstrip().startswith(("<", "/")):
        cands = notes_for(prompt, facts, profile, set(state["shown"]))
        if cands:
            picked = cands[0]
            if picked[0] != "secret":
                state["shown"].append(picked[0])
    json.dump(state, open(state_path, "w"))
    with open(os.path.join(HOME, "live.jsonl"), "a") as log:
        log.write(json.dumps({"at": time.time(), "event": "prompt", "session": sid, "words": len(prompt.split()),
                              "context": facts["context"], "model": facts["model"], "effort": facts["effort"],
                              "note": picked[0] if picked else None, "muted": state["muted"]}) + "\n")
    if state["muted"]:
        return None
    context = BRIEF + (f"\n\nCOACH NOTE: {picked[1]}" if picked else "\n\n(No coach note for this ask.)")
    facts_line = f"\nSession facts: model={facts['model']}, effort={facts['effort']}, context≈{(facts['context'] or 0) // 1000}k tokens, asks so far={facts['human_asks']}."
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context + facts_line}}


def on_stop(payload: dict) -> None:
    os.makedirs(HOME, exist_ok=True)
    facts = session_facts(payload.get("transcript_path") or "")
    with open(os.path.join(HOME, "live.jsonl"), "a") as log:
        log.write(json.dumps({"at": time.time(), "event": "stop", "session": payload.get("session_id"),
                              "context": facts["context"], "model": facts["model"], "effort": facts["effort"]}) + "\n")


def main():
    event = sys.argv[1] if len(sys.argv) > 1 else "prompt"
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    try:
        if event == "prompt":
            out = on_prompt(payload)
            if out:
                print(json.dumps(out))
        else:
            on_stop(payload)
    except Exception as exc:          # a coach must never break the session it is watching
        try:
            with open(os.path.join(HOME, "live-errors.log"), "a") as fh:
                fh.write(f"{time.time()} {event} {exc!r}\n")
        except OSError:
            pass
    sys.exit(0)


if __name__ == "__main__":
    main()
