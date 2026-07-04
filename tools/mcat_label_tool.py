#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Generate a self-contained HTML tool to HUMAN-label the MCAT judge set (7f).

Why: the eval's judge is measured against ``judge_labels.jsonl``. Those labels
were AI-drafted (circular). This builds a pool of candidate cards from the fixed
Enzymes source -- the existing judge candidates (labels stripped) + the offline
Draft + the baseline, deduped -- and emits an HTML page where a human assigns
each card exactly one of: correct-useful / wrong / correct-but-bad-teaching.
Export downloads ``judge_labels.jsonl`` in the schema ``mcat_eval.py`` consumes.

Non-circular by construction: the candidate cards may be machine-generated, but
the LABELS are the human's, which is exactly what makes the judge accuracy honest.

Run:   out/pyenv/bin/python tools/mcat_label_tool.py [N]
Then:  open tools/mcat-label-tool.html  (a browser; no server needed)
Finally: drop the exported judge_labels.jsonl into qt/aqt/mcat_data/ and re-run
         the eval:  OPENAI_API_KEY=... out/pyenv/bin/python qt/aqt/mcat_eval.py --live
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
AQT = HERE.parent / "qt" / "aqt"
sys.path.insert(0, str(AQT))

import mcat_ai  # noqa: E402


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _span_of(card: dict) -> str:
    return str(card.get("source_span") or card.get("span") or "").strip()


def build_candidates(target: int = 50) -> tuple[str, list[dict]]:
    """Candidate pool from the fixed Enzymes source: existing judge candidates
    (labels stripped) first (they carry a deliberate mix of good/wrong/bad), then
    offline Draft, then the baseline. Deduped by normalized front, capped."""
    topic, spans = mcat_ai.load_source()  # default = Enzymes
    span_text = {s["id"]: s["text"] for s in spans}

    pool: list[dict] = []
    seen: set[str] = set()

    def add(front: str, back: str, span_id: str) -> None:
        front, back = (front or "").strip(), (back or "").strip()
        key = _norm(front)
        if not front or not back or key in seen:
            return
        seen.add(key)
        pool.append({
            "front": front, "back": back, "source_span": span_id,
            "span_text": span_text.get(span_id, ""),
        })

    jl = mcat_ai.DATA_DIR / "judge_labels.jsonl"
    if jl.exists():
        for line in jl.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                add(d.get("front"), d.get("back"), _span_of(d))

    for c in mcat_ai.draft_cards(spans, topic, live=False):
        add(c.get("front"), c.get("back"), _span_of(c))
    for c in mcat_ai.baseline_cards(spans, topic):
        add(c.get("front"), c.get("back"), _span_of(c))

    pool = pool[:target]
    for i, c in enumerate(pool, 1):
        c["id"] = f"J{i:02d}"
    return topic, pool


_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MCAT Card Check &mdash; human labeling</title>
<style>
:root{--bg:#0f1115;--card:#1a1d24;--fg:#e6e8ee;--muted:#9aa3b2;--line:#2a2f3a;
--good:#2ecc71;--bad:#e74c3c;--meh:#f39c12;--accent:#4f8cff;}
*{box-sizing:border-box;}
body{margin:0;font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--fg);}
.wrap{max-width:820px;margin:0 auto;padding:20px;}
header{border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg);z-index:5;}
h1{margin:0 0 4px;font-size:18px;}
.sub{color:var(--muted);font-size:13px;}
code{background:#222634;padding:1px 5px;border-radius:5px;}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin:10px 0 0;font-size:12.5px;color:var(--muted);}
.legend b{color:var(--fg);}
.progress{height:8px;background:var(--line);border-radius:6px;overflow:hidden;margin-top:12px;}
.progress>div{height:100%;background:var(--accent);width:0;transition:width .2s;}
.counts{font-size:12.5px;color:var(--muted);margin-top:6px;display:flex;gap:14px;flex-wrap:wrap;}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;margin-top:16px;}
.qid{color:var(--muted);font-size:12px;letter-spacing:.04em;}
.tag{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.05em;margin-top:14px;}
.front{font-size:18px;font-weight:600;margin:6px 0;}
.back{font-size:16px;}
.src{margin-top:14px;border-top:1px dashed var(--line);padding-top:12px;color:var(--muted);font-size:13.5px;white-space:pre-wrap;}
.btns{display:flex;gap:10px;margin-top:18px;flex-wrap:wrap;}
button.lab{flex:1;min-width:150px;padding:12px 14px;border-radius:10px;border:1px solid var(--line);background:#222634;color:var(--fg);cursor:pointer;font-size:14px;}
button.lab:hover{border-color:var(--accent);}
button.lab.sel-good{background:rgba(46,204,113,.18);border-color:var(--good);}
button.lab.sel-bad{background:rgba(231,76,60,.18);border-color:var(--bad);}
button.lab.sel-meh{background:rgba(243,156,18,.18);border-color:var(--meh);}
.nav{display:flex;justify-content:space-between;margin-top:16px;}
.nav button,.tool button{padding:9px 14px;border-radius:9px;border:1px solid var(--line);background:#222634;color:var(--fg);cursor:pointer;}
.tool{display:flex;gap:10px;margin-top:18px;}
.tool .exp{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600;}
kbd{background:#222634;border:1px solid var(--line);border-radius:5px;padding:1px 6px;font-size:11.5px;}
</style></head><body>
<header><div class="wrap" style="padding-top:14px;padding-bottom:14px;">
<h1>MCAT Card Check &mdash; human labeling</h1>
<div class="sub">Source: <b>__TOPIC__</b> &middot; <b>__COUNT__</b> candidate cards &middot; exports <code>judge_labels.jsonl</code></div>
<div class="legend">
<span><b>1 &middot; correct-useful</b> accurate &amp; one clear idea</span>
<span><b>2 &middot; wrong</b> factually incorrect / unsupported by source</span>
<span><b>3 &middot; bad-teaching</b> accurate but vague, overloaded, trivial, or a dupe</span>
<span><b>S</b> skip</span>
</div>
<div class="progress"><div id="bar"></div></div>
<div class="counts" id="counts"></div>
</div></header>
<div class="wrap">
<div class="card" id="card"></div>
<div class="nav"><button onclick="go(-1)">&larr; Prev <kbd>&larr;</kbd></button>
<button onclick="go(1)">Next <kbd>&rarr;</kbd></button></div>
<div class="tool"><button class="exp" onclick="exportJsonl()">&darr; Export judge_labels.jsonl</button>
<button onclick="resetAll()">Reset labels</button></div>
<p class="sub" style="margin-top:14px">Label with <kbd>1</kbd>/<kbd>2</kbd>/<kbd>3</kbd>, skip with <kbd>S</kbd>, move with <kbd>&larr;</kbd>/<kbd>&rarr;</kbd>. Progress auto-saves in this browser. When done, put the exported file at <code>qt/aqt/mcat_data/judge_labels.jsonl</code> and re-run <code>mcat_eval.py --live</code>.</p>
</div>
<script>
const CANDIDATES = __CANDIDATES_JSON__;
const KEY = "mcat_labels_v1";
let idx = 0;
let store = JSON.parse(localStorage.getItem(KEY) || "{}");
function save(){localStorage.setItem(KEY, JSON.stringify(store));}
function esc(s){return (s||"").replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function render(){
  const c = CANDIDATES[idx], lab = store[c.id];
  document.getElementById("card").innerHTML =
   `<div class="qid">${c.id} &middot; ${idx+1} / ${CANDIDATES.length}</div>`+
   `<div class="tag">Front</div><div class="front">${esc(c.front)}</div>`+
   `<div class="tag">Back</div><div class="back">${esc(c.back)}</div>`+
   (c.span_text?`<div class="src"><b>Cited source [${esc(c.source_span)}]:</b>\n${esc(c.span_text)}</div>`:"")+
   `<div class="btns">`+
   `<button class="lab ${lab==='correct-useful'?'sel-good':''}" onclick="setL('correct-useful')">1 &middot; correct-useful</button>`+
   `<button class="lab ${lab==='wrong'?'sel-bad':''}" onclick="setL('wrong')">2 &middot; wrong</button>`+
   `<button class="lab ${lab==='correct-but-bad-teaching'?'sel-meh':''}" onclick="setL('correct-but-bad-teaching')">3 &middot; bad-teaching</button>`+
   `</div>`;
  updateCounts();
}
function setL(l){store[CANDIDATES[idx].id]=l;save();if(idx<CANDIDATES.length-1)idx++;render();}
function go(d){idx=Math.max(0,Math.min(CANDIDATES.length-1,idx+d));render();}
function updateCounts(){
  let done=0,cu=0,w=0,bt=0;
  for(const c of CANDIDATES){const l=store[c.id];if(l){done++;if(l==='correct-useful')cu++;else if(l==='wrong')w++;else bt++;}}
  document.getElementById("bar").style.width=(100*done/CANDIDATES.length)+"%";
  document.getElementById("counts").innerHTML=
   `<span>labeled <b>${done}/${CANDIDATES.length}</b></span>`+
   `<span style="color:var(--good)">correct-useful ${cu}</span>`+
   `<span style="color:var(--bad)">wrong ${w}</span>`+
   `<span style="color:var(--meh)">bad-teaching ${bt}</span>`;
}
function exportJsonl(){
  const lines=[];
  for(const c of CANDIDATES){const l=store[c.id];if(!l)continue;
    lines.push(JSON.stringify({id:c.id,front:c.front,back:c.back,source_span:c.source_span,label:l}));}
  if(!lines.length){alert("Label at least one card first.");return;}
  const blob=new Blob([lines.join("\n")+"\n"],{type:"application/x-ndjson"});
  const a=document.createElement("a");a.href=URL.createObjectURL(blob);
  a.download="judge_labels.jsonl";a.click();
}
function resetAll(){if(confirm("Clear all your labels?")){store={};save();idx=0;render();}}
document.addEventListener("keydown",e=>{
  if(e.target.tagName==="INPUT")return;
  if(e.key==="1")setL("correct-useful");
  else if(e.key==="2")setL("wrong");
  else if(e.key==="3")setL("correct-but-bad-teaching");
  else if(e.key.toLowerCase()==="s"){if(idx<CANDIDATES.length-1)idx++;render();}
  else if(e.key==="ArrowLeft")go(-1);
  else if(e.key==="ArrowRight")go(1);
});
render();
</script></body></html>
"""


def main() -> None:
    target = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 50
    topic, pool = build_candidates(target)
    candidates_json = json.dumps(pool, ensure_ascii=False).replace("</", "<\\/")
    html = (_HTML
            .replace("__CANDIDATES_JSON__", candidates_json)
            .replace("__TOPIC__", topic)
            .replace("__COUNT__", str(len(pool))))
    out = HERE / "mcat-label-tool.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}")
    print(f"  topic: {topic}   candidates: {len(pool)}")
    print("  open it in a browser, label every card, then Export -> "
          "qt/aqt/mcat_data/judge_labels.jsonl")


if __name__ == "__main__":
    main()
