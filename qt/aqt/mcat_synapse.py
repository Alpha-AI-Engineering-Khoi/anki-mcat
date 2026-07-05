# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Desktop MCAT "Synapse" canvas: the higher-order encoding map.

An interactive node-graph editor (vis-network) hosted in an ``AnkiWebView``.
The learner lays out concepts and draws *named* relationships between them; AI
only proposes (seed concepts, propose arrows, or draft a whole map to react to)
and coaches via chat. The learner still owns the relationships.

Front-end lives in ``mcat_web/`` (synapse.css / synapse.js + vendored
vis-network.min.js); the static markup is the ``_MARKUP`` constant below so the
Python bridge and the DOM it drives stay in one place. JS <-> Python uses Anki's
``pycmd`` bridge (verbs ``synapse:init|save|seed|arrows|auto|chat``); Python ->
JS pushes call the ``window.*`` callbacks defined in synapse.js.

Data model matches ``mcat_program``: concepts=[{id,parent,label}],
links=[{src,dst,label}]. All AI lives in ``mcat_ai`` and degrades with AI OFF.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Callable

from aqt import mcat_ai as ai
from aqt import mcat_program as prog

_WEB = pathlib.Path(__file__).with_name("mcat_web")

# Static DOM the canvas drives. Kept here (not a separate .html) so the bridge
# verbs and the elements they touch live together. The two <script> blocks
# (vendored vis-network + synapse.js) are appended in ``build_view``.
_MARKUP = """
<div id="bar">
  <span class="brand">Synapse</span>
  <button id="bAdd">+ Concept</button>
  <button id="bLink">Draw arrow</button>
  <button id="bDel">Delete</button>
  <span class="sep"></span>
  <button id="bSeed" class="ai">AI: seed concepts</button>
  <button id="bArrows" class="ai">AI: propose arrows</button>
  <button id="bAuto" class="ai">AI: auto-build</button>
  <span class="sep"></span>
  <button id="bChat" class="ai">Chat</button>
  <span class="grow"></span>
  <span id="status"></span>
  <button id="bSave" class="primary">Save map</button>
</div>
<div id="net"></div>
<div id="warn"></div>
<div id="proposed" class="hidden">
  <span id="proposedText"></span>
  <button id="pKeep" class="primary">Keep all</button>
  <button id="pDiscard">Discard</button>
</div>

<div id="modal" class="hidden">
  <div class="card">
    <div class="mtitle" id="modalTitle">Name the relationship</div>
    <div id="chips">
      <button class="chip" data-v="causes">causes</button>
      <button class="chip" data-v="part of">part of</button>
      <button class="chip" data-v="regulates">regulates</button>
      <button class="chip" data-v="contrast with">contrast with</button>
    </div>
    <input id="relText" placeholder="or type a relationship&hellip;" />
    <div class="mbtns">
      <button id="mDelete">Delete arrow</button>
      <button id="mCancel">Cancel</button>
      <button id="mOk" class="primary">Add</button>
    </div>
  </div>
</div>

<div id="chat" class="hidden">
  <div class="chead"><span>Ask about your map</span><button id="chatClose">&times;</button></div>
  <div id="chatLog"></div>
  <div class="crow">
    <input id="chatInput" placeholder="e.g. have you considered grouping by pathway?" />
    <button id="chatSend" class="primary">Send</button>
  </div>
</div>
"""


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


def _future_result(fut: Any, default: Any) -> Any:
    try:
        return fut.result()
    except Exception:
        return default


def _auto_to_map(m: dict) -> dict:
    """Convert AI auto-build output (label-keyed) into the id-keyed map the
    canvas loads. Concepts get contiguous ids; links resolve labels -> ids."""
    concepts: list[dict] = []
    id_by: dict[str, int] = {}
    for c in (m or {}).get("concepts", []):
        lab = ((c.get("label") if isinstance(c, dict) else str(c)) or "").strip()
        if not lab:
            continue
        cid = len(concepts) + 1
        concepts.append({"id": cid, "parent": None, "label": lab})
        id_by[lab.lower()] = cid
    links: list[dict] = []
    for l in (m or {}).get("links", []):
        s = id_by.get((l.get("src_label") or "").strip().lower())
        d = id_by.get((l.get("dst_label") or "").strip().lower())
        lab = (l.get("label") or "").strip()
        if s and d and s != d:
            links.append({"src": s, "dst": d, "label": lab})
    return {"concepts": concepts, "links": links}


def build_view(mw, topic, spans, parent=None):  # type: ignore[no-untyped-def]
    """Build the Synapse ``AnkiWebView`` for ``topic``.

    Returns ``(view, cleanup)``; call ``cleanup()`` when the host dialog closes
    so late AI callbacks don't touch a torn-down page."""
    from aqt.webview import AnkiWebView, AnkiWebViewKind

    body = (
        _MARKUP
        + "\n<script>" + _read("vis-network.min.js") + "</script>"
        + "\n<script>" + _read("synapse.js") + "</script>"
    )
    head = "<style>" + _read("synapse.css") + "</style>"

    view = AnkiWebView(parent=parent, kind=AnkiWebViewKind.DEFAULT)
    state = {"alive": True}

    def push(js: str) -> None:
        if state["alive"]:
            view.eval(js)

    def push_map() -> None:
        rec = prog.get_record(mw.col, topic)
        payload = {"concepts": rec.get("concepts", []), "links": rec.get("links", [])}
        push("window.loadMap(%s)" % json.dumps(payload))

    def bg(task: Callable[[], Any], done: Callable[[Any], None]) -> None:
        # AI is network-only, so it must not block the UI thread or the
        # collection lock; on_done runs back on main (safe for view.eval).
        mw.taskman.run_in_background(task, done, uses_collection=False)

    def apply_chat(res: dict) -> None:
        """Apply the chat assistant's edits (if any), then show its reply."""
        res = res or {}
        if res.get("add_concepts") or res.get("add_links") or res.get("remove_links"):
            push("window.applyOps(%s)" % json.dumps({
                "add_concepts": res.get("add_concepts") or [],
                "add_links": res.get("add_links") or [],
                "remove_links": res.get("remove_links") or [],
            }))
        push("window.chatReply(%s)" % json.dumps(res.get("reply", "")))

    def on_cmd(msg: str) -> Any:
        if not isinstance(msg, str) or not msg.startswith("synapse:"):
            return None
        parts = msg.split(":", 2)
        verb = parts[1] if len(parts) > 1 else ""
        payload = parts[2] if len(parts) > 2 else ""

        if verb == "init":
            push_map()
        elif verb == "save":
            try:
                data = json.loads(payload)
            except Exception:
                return None
            prog.save_build(
                mw.col, topic, data.get("concepts", []), data.get("links", [])
            )
        elif verb == "seed":
            bg(
                lambda: ai.concept_candidates(spans, topic.name),
                lambda fut: push(
                    "window.applyNodes(%s)" % json.dumps(_future_result(fut, []))
                ),
            )
        elif verb == "arrows":
            try:
                cur = json.loads(payload)
            except Exception:
                cur = {"concepts": []}
            bg(
                lambda: ai.propose_arrows(cur.get("concepts", []), topic.name, spans),
                lambda fut: push(
                    "window.applyLinks(%s)" % json.dumps(_future_result(fut, []))
                ),
            )
        elif verb == "auto":
            bg(
                lambda: ai.autobuild_map(topic.name, spans),
                lambda fut: push(
                    "window.loadMap(%s)"
                    % json.dumps(_auto_to_map(_future_result(fut, {})))
                ),
            )
        elif verb == "chat":
            try:
                d = json.loads(payload)
            except Exception:
                d = {"msg": "", "map": {}}
            bg(
                lambda: ai.map_chat(
                    d.get("msg", ""), d.get("map", {}), topic.name, spans
                ),
                lambda fut: apply_chat(_future_result(fut, {})),
            )
        return None

    view.set_bridge_command(on_cmd, view)
    # default_css off: this is a full custom page; we only need Anki's bridge
    # (js/webview.js provides pycmd). Assets are inlined because a stdHtml page
    # is served from the media server, where relative asset URLs won't resolve.
    view.stdHtml(body, head=head, js=["js/webview.js"], default_css=False, context=view)

    def cleanup() -> None:
        state["alive"] = False
        try:
            view.cleanup()
        except Exception:
            pass

    return view, cleanup
