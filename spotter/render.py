"""Render the record, findings and metrics as one self-contained page."""
from __future__ import annotations
import json, os
from html import escape as e

CSS = """
/* layout: one reading column; findings are rows with a fixed left rail for kind + dimension, never a card grid */
:root{--bg:#F4F6F7;--surface:#FFFFFF;--ink:#14202B;--muted:#5A6A78;--line:#D5DCE2;--accent:#1F4FD8;--accent-soft:#E6ECFC;
--crit:#B93228;--warn:#9A5B00;--good:#1B7448;--quote:#EEF1F3;
--display:"Archivo","Arial Narrow",Arial,sans-serif;--body:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;--mono:"IBM Plex Mono",ui-monospace,Menlo,monospace}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#10171D;--surface:#18222B;--ink:#E8EEF2;--muted:#9AA9B5;--line:#2C3A46;--accent:#8FA9FF;--accent-soft:#1E2B4A;--crit:#FF8A7E;--warn:#F0B35A;--good:#6FD3A0;--quote:#1E2A34;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#10171D;--surface:#18222B;--ink:#E8EEF2;--muted:#9AA9B5;--line:#2C3A46;--accent:#8FA9FF;--accent-soft:#1E2B4A;--crit:#FF8A7E;--warn:#F0B35A;--good:#6FD3A0;--quote:#1E2A34;color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:var(--body);font-size:16px;line-height:1.55;margin:0}
.wrap{max-width:980px;margin:0 auto;padding-block:36px 72px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));display:flex;flex-direction:column;gap:44px}
h1,h2,h3{font-family:var(--display);text-wrap:balance;margin:0;letter-spacing:-.01em}
h1{font-size:clamp(2rem,5vw,3rem);font-weight:800;font-stretch:88%;line-height:1.02}
h2{font-size:1.5rem;font-weight:700;font-stretch:90%}
h3{font-size:1.2rem;font-weight:700;line-height:1.25}
p{margin:0;max-width:68ch}
.label{font-family:var(--mono);font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.muted{color:var(--muted)} .mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
header{display:flex;flex-direction:column;gap:14px}
.lede{font-size:1.1rem}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:0;border-block:2px solid var(--ink)}
.stat{padding:16px 16px 16px 0;display:flex;flex-direction:column;gap:4px;min-width:0}
.stat+.stat{padding-left:16px;border-left:1px solid var(--line)}
.stat b{font-family:var(--display);font-size:2.1rem;font-weight:800;font-stretch:85%;line-height:1;font-variant-numeric:tabular-nums}
.stat span{font-size:.86rem;color:var(--muted)}
section{display:flex;flex-direction:column;gap:18px}
.finding{display:grid;grid-template-columns:150px minmax(0,1fr);gap:8px 24px;padding-block:26px;border-top:1px solid var(--line)}
.finding:first-of-type{border-top:2px solid var(--ink)}
.rail{display:flex;flex-direction:column;gap:8px;align-items:flex-start}
.chip{font-family:var(--mono);font-size:.7rem;letter-spacing:.06em;text-transform:uppercase;padding:3px 8px;border-radius:3px;border:1px solid currentColor}
.k-fix.s-high{color:var(--crit)} .k-fix.s-medium{color:var(--warn)} .k-test{color:var(--accent)} .k-strength{color:var(--good)} .k-watch{color:var(--muted)}
.fbody{display:flex;flex-direction:column;gap:14px;min-width:0}
.quotes{display:flex;flex-direction:column;gap:6px;margin:0;padding:0;list-style:none}
.quotes li{background:var(--quote);padding:8px 12px;border-radius:4px;font-size:.93rem;overflow-wrap:anywhere}
.quotes q{quotes:none} .quotes small{display:block;color:var(--muted);font-family:var(--mono);font-size:.7rem;margin-top:2px}
.nums{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
.num b{font-family:var(--display);font-size:1.45rem;font-weight:700;font-variant-numeric:tabular-nums;display:block;line-height:1.1}
.num span{font-size:.84rem;color:var(--muted)}
.action{background:var(--accent-soft);border-radius:6px;padding:14px 16px;display:flex;flex-direction:column;gap:8px}
.action .label{color:var(--accent)}
details summary{cursor:pointer;font-size:.9rem;color:var(--accent)} details summary:focus-visible,button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
pre{font-family:var(--mono);font-size:.78rem;line-height:1.5;background:var(--surface);border:1px solid var(--line);border-radius:4px;padding:12px;margin:8px 0 0;overflow-x:auto;white-space:pre-wrap;overflow-wrap:anywhere}
button.copy{font:inherit;font-size:.82rem;background:var(--accent);color:var(--surface);border:0;border-radius:4px;padding:6px 12px;cursor:pointer;align-self:flex-start}
.tablewrap{overflow-x:auto;background:var(--surface);border:1px solid var(--line);border-radius:6px}
table{border-collapse:collapse;width:100%;font-size:.9rem} th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-family:var(--mono);font-size:.7rem;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:500;white-space:nowrap}
td.n,th.n{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums;white-space:nowrap} tr:last-child td{border-bottom:0}
.levels{display:grid;grid-template-columns:minmax(0,220px) 130px minmax(0,1fr);gap:10px 20px;align-items:baseline}
.pips{display:flex;gap:4px;align-items:center} .pip{width:22px;height:8px;border-radius:2px;background:var(--line)} .pip.on{background:var(--ink)}
.pips em{font-style:normal;font-family:var(--mono);font-size:.72rem;margin-left:6px;color:var(--muted)}
.chart{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:16px} .chart svg{display:block;width:100%;height:auto}
.two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px} .two>div{display:flex;flex-direction:column;gap:8px;min-width:0}
ul.plain{margin:0;padding-left:1.1em;display:flex;flex-direction:column;gap:4px}
@media (max-width:720px){.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.stat:nth-child(3){padding-left:0;border-left:0}.stat:nth-child(n+3){border-top:1px solid var(--line)}
.finding{grid-template-columns:minmax(0,1fr)}.rail{flex-direction:row;flex-wrap:wrap;align-items:center}.levels{grid-template-columns:minmax(0,1fr)}.levels>*{margin:0}.levels p{margin-bottom:10px}.two{grid-template-columns:minmax(0,1fr)}}
"""
KIND = {"fix": "Fix", "test": "Test", "strength": "Keep", "watch": "Watch"}
LEVELS = {"Weak": 1, "Uneven": 2, "Solid": 3, "Strong": 4}


def _fmt(n):
    v, unit = n["value"], n.get("unit")
    if unit == "usd":
        return f"${v:,.2f}"
    if unit == "share":
        return f"{v * 100:.0f}%"
    if unit == "tokens":
        return f"{v:,.0f}"
    return f"{v:,}" if isinstance(v, int) else f"{v}"


def _histogram(sessions):
    edges = list(range(0, 800_000, 100_000))
    counts = [0] * len(edges)
    for s in sessions:
        for t in s["turns"]:
            c = t.get("context_tokens_at_start")
            if t["origin"] == "human" and c:
                counts[min(len(edges) - 1, c // 100_000)] += 1
    W, H, L, B, T = 640, 230, 36, 34, 14
    top = max(counts) or 1
    step = 10 if top <= 50 else 20
    ymax = (top // step + 1) * step
    bw = (W - L - 8) / len(edges)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Asks by context size when sent">']
    for y in range(0, ymax + 1, step):
        py = T + (H - T - B) * (1 - y / ymax)
        out.append(f'<line x1="{L}" x2="{W - 8}" y1="{py:.1f}" y2="{py:.1f}" stroke="var(--line)" stroke-width="1"/>'
                   f'<text x="{L - 6}" y="{py + 4:.1f}" text-anchor="end" font-size="11" fill="var(--muted)" font-family="var(--mono)">{y}</text>')
    for i, c in enumerate(counts):
        h = (H - T - B) * c / ymax
        x = L + i * bw
        fill = "var(--crit)" if edges[i] >= 300_000 else "var(--ink)"
        out.append(f'<rect x="{x + 3:.1f}" y="{H - B - h:.1f}" width="{bw - 6:.1f}" height="{h:.1f}" fill="{fill}" rx="2"/>'
                   f'<text x="{x + bw / 2:.1f}" y="{H - B - h - 4:.1f}" text-anchor="middle" font-size="11" fill="var(--ink)" font-family="var(--mono)">{c}</text>')
        lab = f"{edges[i] // 1000}k+" if i == len(edges) - 1 else f"{edges[i] // 1000}–{edges[i] // 1000 + 100}k"
        out.append(f'<text x="{x + bw / 2:.1f}" y="{H - B + 15}" text-anchor="middle" font-size="11" fill="var(--muted)" font-family="var(--mono)">{lab}</text>')
    out.append(f'<text x="{L}" y="{H - 3}" font-size="11" fill="var(--muted)" font-family="var(--body)">tokens already in context when the ask was sent (red: above 300k)</text></svg>')
    return "".join(out), sum(counts)


def render(data_dir: str, out_path: str):
    doc = json.load(open(os.path.join(data_dir, "findings.json")))
    m = json.load(open(os.path.join(data_dir, "metrics.json")))
    sessions = [json.loads(line) for line in open(os.path.join(data_dir, "sessions.jsonl"))]
    cov, o = doc["coverage"], m["overview"]
    h = []
    h.append('<meta name="claude:viewport-fit-sides" content="cover"><title>Spotter Log</title>'
             '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@75..100,500..800&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">'
             f"<style>{CSS}</style><div class=\"wrap\">")
    h.append(f'<header><span class="label">Spotter · first read · {e(cov["period"])}</span>'
             f'<h1>How {e(doc["subject"])} works with AI, and what to change</h1>'
             f'<p class="lede">Read from {cov["sessions_in_record"]} of your {cov["sessions_listed"]} Claude Code cloud sessions. '
             f'Every quote below is checked against what you typed; every number is counted from the transcripts. '
             f'Nothing here comes from a test.</p></header>')
    ctx = m["context"]
    h.append('<div class="stats">'
             f'<div class="stat"><b>{o["human_turns"]}</b><span>asks you made</span></div>'
             f'<div class="stat"><b>{o["agent_work_hours"]:.0f} h</b><span>of agent work they started</span></div>'
             f'<div class="stat"><b>{ctx["share_of_turns_over_300k"] * 100:.0f}%</b><span>of asks sent into 300k+ tokens of context</span></div>'
             f'<div class="stat"><b>{len(m["open_loops"])}</b><span>sessions still waiting on you</span></div></div>')
    # findings
    h.append('<section><h2>Findings</h2><p class="muted">Ordered by what I would change first. Fix = change now. Test = run a comparison before deciding. Keep = working. Watch = already improving.</p><div>')
    for f in doc["findings"]:
        cls = f'k-{f["kind"]} s-{f["severity"]}'
        h.append(f'<article class="finding" id="{e(f["id"])}"><div class="rail"><span class="chip {cls}">{KIND[f["kind"]]}</span>'
                 f'<span class="label">{e(f["dimension"])}</span></div><div class="fbody"><h3>{e(f["title"])}</h3><p>{e(f["claim"])}</p><p class="muted">{e(f["why"])}</p>')
        if f.get("numbers"):
            h.append('<div class="nums">' + "".join(
                f'<div class="num"><b>{e(_fmt(n))}</b><span>{e(n["label"])}{(" · " + e(n["note"])) if n.get("note") else ""}</span></div>' for n in f["numbers"]) + "</div>")
        if f.get("evidence"):
            h.append('<ul class="quotes">' + "".join(
                f'<li><q>{e(ev["quote"])}</q><small>{e(ev.get("date", ""))} · {e(ev.get("title", ""))}</small></li>' for ev in f["evidence"]) + "</ul>")
        if f["id"] == "open-loops":
            rows = "".join(f'<tr><td>{e(x["title"])}</td><td>{e(x["needs_action"])}</td><td class="n">{x["days_waiting"]:.0f} d</td></tr>' for x in m["open_loops"])
            h.append(f'<div class="tablewrap"><table><tr><th>Session</th><th>Waiting for</th><th class="n">For</th></tr>{rows}</table></div>')
        a = f["action"]
        status = {"ready": "Ready to apply", "needs-repo": "Drafted; needs the repo attached", "not-built": "Needs replay, not built yet",
                  "yours": "Yours to do", "keep": "No change"}[a["status"]]
        h.append(f'<div class="action"><span class="label">{e(status)}</span><p>{e(a["summary"])}</p>')
        if a.get("patch"):
            pid = "patch-" + f["id"]
            h.append(f'<details><summary>Proposed text for {e(a["repo"])} / {e(a["file"])}</summary><pre id="{pid}">{e(a["patch"])}</pre></details>'
                     f'<button class="copy" type="button" id="copy-{pid}" data-copy="{pid}">Copy text</button>')
        h.append(f'<p class="muted" style="font-size:.86rem">How we will know: {e(f["check"])}</p></div></div></article>')
    h.append("</div></section>")
    # record
    h.append('<section><h2>The record</h2><p class="muted">A first, provisional read of seven working habits, each tied to the findings above. This is the part that could one day stand in for a certificate; today it is one tool, six months, and my judgment.</p><div class="levels">')
    for r in doc["record"]:
        n = LEVELS[r["level"]]
        h.append(f'<strong>{e(r["dimension"])}</strong><div class="pips">' + "".join(f'<i class="pip{" on" if i < n else ""}"></i>' for i in range(4))
                 + f'<em>{e(r["level"])}</em></div><p class="muted">{e(r["note"])}</p>')
    h.append("</div></section>")
    # context chart + model table
    svg, n_ctx = _histogram(sessions)
    h.append(f'<section><h2>Context at the moment you hit send</h2><p class="muted">{n_ctx} asks where the platform recorded context size. The window is 1,000,000 tokens; the median ask arrived at {ctx["median_tokens_at_turn_start"]:,}.</p><div class="chart">{svg}</div></section>')
    rows = []
    for key, v in m["model_effort"].items():
        if v["cost_usd"] < 1:
            continue
        quick = v["turn_sizes"].get("trivial", 0)
        wait = v["median_seconds_by_size"].get("trivial")
        rows.append(f'<tr><td class="mono">{e(key.replace(" @ ?", " @ not recorded"))}</td><td class="n">{v["sessions"]}</td><td class="n">{v["human_turns"]}</td>'
                    f'<td class="n">{quick}</td><td class="n">{f"{wait:.0f} s" if wait else "–"}</td><td class="n">${v["cost_usd"]:,.0f}</td></tr>')
    h.append('<section><h2>Models and effort you actually used</h2><p class="muted">Quick asks are those the model finished in three steps or fewer. Cost is list-price equivalent, summed per ask.</p>'
             '<div class="tablewrap"><table><tr><th>Model @ effort</th><th class="n">Sessions</th><th class="n">Asks</th><th class="n">Quick asks</th><th class="n">Median quick wait</th><th class="n">Cost</th></tr>'
             + "".join(rows) + "</table></div></section>")
    # coverage
    h.append('<section><h2>What this read can and cannot see</h2><div class="two"><div><span class="label">In the record</span><ul class="plain">'
             + "".join(f"<li>{e(x)}</li>" for x in cov["seen"])
             + f'<li>{cov["complete"]} sessions complete, {cov["partial"]} partial, {cov["not_exported"]} not exported</li></ul></div>'
             '<div><span class="label">Not yet</span><ul class="plain">' + "".join(f"<li>{e(x)}</li>" for x in cov["not_yet"]) + "</ul></div></div>"
             f'<p class="muted">{e(cov["note"])}</p><p class="muted">{e(cov["cost_note"])}</p>'
             '<p class="muted">Spotter keeps what you asked, what the tool did and what came back. It does not keep the model\'s private reasoning, and it strips keys and tokens at ingest.</p></section>')
    h.append("""</div><script>
document.querySelectorAll('button.copy').forEach(function(b){b.addEventListener('click',function(){
  var el=document.getElementById(b.dataset.copy),t=el.textContent;
  var done=function(){b.textContent='Copied';setTimeout(function(){b.textContent='Copy text'},1600)};
  var fallback=function(){el.closest('details').open=true;var r=document.createRange();r.selectNodeContents(el);var s=getSelection();s.removeAllRanges();s.addRange(r);b.textContent='Selected. Press copy'};
  try{navigator.clipboard.writeText(t).then(done,fallback)}catch(err){fallback()}
})});
</script>""")
    open(out_path, "w").write("".join(h))
