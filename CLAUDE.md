# CLAUDE.md — ai-optimizer (working name: Spotter)

A personal trainer for how NLW works with AI. It watches real work, judges it, and **intervenes while the work is
happening**. Intervention in the moment is the product; reports after the fact are secondary. NLW, Nov 11: "Who the
hell cares if 5 days from now a feed tells me I could have done it differently. It needs to intervene."

Python 3, standard library only for the core. Data stays on the machine in `~/.spotter`.

## Working agreements (NLW's standing instructions)
- **Ship it.** Commit and push to `main` when a piece works. Do not leave draft PRs waiting for the word "merge".
- **Show the thing first.** Start every report with how to see it running (the command, a screenshot, the link).
- **Build software he can test**, not analysis. Each step ends with something he can try in under a minute.
- **Plain copy.** No AI-isms, no clever-over-clear, no caveat sections. Notes to him are one or two sentences.
- One agent, one pass. No subagent fan-outs unless he asks.
- Never store or read a model's private reasoning. Strip secrets before anything is written (`spotter/redact.py`).

## What exists (state as of Nov 11)
| Piece | File | State |
|---|---|---|
| Rules that decide what is worth saying | `spotter/live.py` (`notes_for`) + `profiles/default.json` | Tested on sample prompts against a real session log |
| In-session hook for Claude Code (note opens the reply) | `spotter/live.py`, `install.sh` | Pipe-tested; **never fired in a live session** |
| Background watcher for Claude Code + Codex logs | `spotter/watch.py` | Tested on simulated logs on Linux; **never run on macOS** |
| History read (ingest, metrics, findings page) | `spotter/adapters`, `measure.py`, `verify.py`, `render.py` | Works on 49 real cloud sessions |
| Codex log format | `spotter/adapters/codex.py`, `watch.py` | **Written from memory of the format; unverified** |

## The Mac build (do this next, on NLW's laptop)

Goal: a menu bar app that is always there, watches the AI tools he uses on this Mac, and notifies him at the moment
something should change. Target apps for the test period: the Claude desktop app (chat and Code) and the ChatGPT
desktop app (chat and Codex).

Build in this order. Stop and show him after each step.

1. **Watcher live on this Mac.** Run `python3 -m spotter.watch`. Open a real `~/.codex/sessions/**/rollout-*.jsonl`
   and a real `~/.claude/projects/*/*.jsonl`, fix the parsers to match what is actually there, and confirm a
   notification appears within two seconds of him sending "is it live?" in a local Claude Code session and a quick
   question in Codex. Notifications currently go through `osascript`; keep that until step 2 replaces it.
2. **Menu bar app.** An icon that shows quiet vs. has-something. The dropdown lists today's notes (from
   `~/.spotter/notes.jsonl`), the tool, model, effort and context size of the session he is in, a mute switch, and
   Quit. Start at login (launchd agent). Python with `rumps`/`pyobjc` in a venv is fine for the test period; say so
   if Swift is clearly the better call on this machine and why. Notifications should be native and clickable.
3. **Read the desktop apps (spike first, one hour).** Most of his Claude Code sessions run in the cloud, and plain
   chat in both apps leaves no log on disk, so logs alone miss most of his day. Use the macOS Accessibility API to
   read the frontmost Claude or ChatGPT window: the model picker, the effort setting if shown, and the text in the
   composer. Report plainly what is and is not readable in each app before building on it. Electron apps may need
   `AXManualAccessibility` set. Only ever read these two apps, and only while they are frontmost.
4. **Intervene before send.** If step 3 can read the composer, run the same rules on the draft while he types
   (debounced) and notify before he hits send: a pasted key, a quick question at max effort, a one-line design ask
   with no success criterion. This is the capability the hook cannot provide.
5. **Make it a rule.** A note that proposes a rule gets a button; clicking it writes the rule into the right
   instruction file (`~/.claude/CLAUDE.md` or the repo's) and shows him the diff.

Rules for notes: at most one per message, each kind once per session, silent when there is nothing worth saying.
A coach that nags gets turned off. When in doubt, say nothing.

Not now: Vercel/Supabase sync (approved by NLW, only needed once the profile must reach cloud sessions), browser
extensions, replay against other models.

## Commands
```
python3 -m spotter.watch --seconds 30      # watcher, prints notes off macOS, notifies on macOS
./install.sh                               # register the in-session hook in ~/.claude/settings.json
python3 -m spotter ingest --claude-home ~/.claude --codex-home ~/.codex && python3 -m spotter measure
```
