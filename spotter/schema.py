"""The normalized record every adapter produces.

A Session is one conversation with an AI tool. A Turn is one human ask and
everything the tool did until it stopped. Adapters for different vendors all
emit this shape, so everything downstream (metrics, coaching, the record) is
vendor-neutral.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ToolCall:
    name: str
    summary: str = ""          # short, human-readable (command, file, subagent type)
    is_error: bool = False
    in_subagent: bool = False


@dataclass
class Turn:
    idx: int
    started_at: str
    prompt: str                                  # what the human typed
    origin: str = "human"                        # human | scheduled | peer | system
    ended_at: str | None = None
    status: str = "open"                         # success | error | interrupted | open
    duration_ms: int | None = None               # wall time the tool worked
    gap_before_ms: int | None = None             # time since the previous turn ended
    steps: int | None = None                     # model round-trips inside the turn
    cost_usd: float = 0.0                        # list-price equivalent
    usage: dict[str, dict[str, float]] = field(default_factory=dict)   # by model
    context_tokens_at_start: int | None = None
    effort: str | None = None
    tools: list[ToolCall] = field(default_factory=list)
    subagents_spawned: int = 0
    subagent_types: dict[str, int] = field(default_factory=dict)
    permission_denials: int = 0
    interjections: list[str] = field(default_factory=list)   # human messages sent mid-turn
    final_text: str = ""                         # what the tool said when it stopped
    compactions: int = 0
    continuations: int = 0                       # background-task notices / events that resumed work
    failed_runs: int = 0
    interrupted_by_user: int = 0
    secrets_pasted: int = 0                      # count only; the values are removed at ingest
    context_tokens_peak: int | None = None


@dataclass
class Session:
    id: str
    source: str                                  # claude-code-cloud | claude-code-local | codex | chatgpt | claude-chat
    title: str = ""
    surface: str = ""                            # desktop_app | web | ios | cli | ...
    created_at: str | None = None
    updated_at: str | None = None
    repos: list[str] = field(default_factory=list)
    model: str | None = None                     # configured model
    effort: str | None = None                    # configured effort
    permission_mode: str | None = None
    parent_id: str | None = None
    status: str | None = None                    # last known state (completed, blocked, ...)
    needs_action: str | None = None
    reported_cost_usd: float | None = None       # the vendor's own total, when it gives one
    reported_context_tokens: int | None = None
    turns: list[Turn] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
