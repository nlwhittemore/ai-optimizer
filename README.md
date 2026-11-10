# Spotter

Watches how you actually work with AI, evaluates it from the transcripts, and proposes concrete
changes to your setup. No tests, no courses: the record of your work is the evaluation, and the
output is a change you can apply.

Working name. Local-first: your record lives in `$SPOTTER_DATA` (default `~/.spotter`) and is yours.

## The loop

```
ingest  ->  measure  ->  coach  ->  verify  ->  render  ->  apply
```

| Step | What it does | Uses a model? |
|---|---|---|
| `spotter ingest` | Adapters turn each tool's logs into one vendor-neutral record (`spotter/schema.py`): sessions made of asks, with timing, model, effort, context size, cost, tools, corrections. Secrets are stripped; model reasoning is never kept. | No |
| `spotter measure` | Counts: model and effort mix, context load, cold re-reads, approvals and waiting, check-in loops, open loops, friction. | No |
| coach | A reviewer reads `spotter condense <session>` plus the metrics and writes `findings.json` to the schema in `coach/BRIEF.md`. | Yes |
| `spotter verify` | Rejects any finding whose quote is not verbatim in the record or whose number disagrees with the metrics. | No |
| `spotter render` | One page: findings, proposed changes, the working record. | No |
| `spotter apply` | Commits a finding's proposed text to the target repo on a branch. Refuses unverified findings. | No |

## Sources

| Source | Adapter | State |
|---|---|---|
| Claude Code cloud sessions | `adapters/claude_cloud.py` | Working, run on 49 real sessions |
| Claude Code on your machine (`~/.claude/projects`) | `adapters/claude_code.py` | Working, run on one real log |
| Codex CLI and app (`~/.codex/sessions`) | `adapters/codex.py` | Written from the format; not yet run on a real file |
| ChatGPT and Claude chat (data export `conversations.json`) | `adapters/chat_export.py` | Written from the format; not yet run on a real export |

## Run it

```bash
python3 -m spotter ingest --claude-home ~/.claude --codex-home ~/.codex
python3 -m spotter measure
python3 -m spotter verify ~/.spotter/findings.json
python3 -m spotter render --out spotter-log.html
```

Python 3.10+, standard library only.

## Not built yet

- **Replay**: re-run a past ask on another model or effort level and compare. This is what turns
  "try a different model" from advice into evidence, and what makes a new model release actionable.
- **Coach as a command**: in the first pass the coach step was done by hand in a Claude Code session.
- **Always-on**: `hooks/claude-settings.example.json` re-ingests when a Claude Code session ends; untested.
- **Chat apps live** (no export step), and anything outside AI tools.
- `tools/` holds the one-off scripts used to export cloud sessions for the first read.
