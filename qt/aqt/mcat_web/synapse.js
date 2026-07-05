"use strict";
// MCAT Speedrun — Synapse canvas logic. Runs inside AnkiWebView; talks to Python
// via Anki's pycmd bridge ("synapse:<verb>[:<json>]") and receives pushes through
// the window.* callbacks below (called by mcat_synapse.py via view.eval).
// Data model matches mcat_program.py: concepts=[{id,parent,label}], links=[{src,dst,label}].

const nodes = new vis.DataSet([]);
const edges = new vis.DataSet([]);
const container = document.getElementById("net");
const NODE_STYLE = { shape: "box", margin: 10, widthConstraint: { maximum: 160 },
  color: { background: "#ffffff", border: "#4b56d2", highlight: { background: "#eef0fb", border: "#4b56d2" } },
  font: { color: "#1a1a1a", size: 14 }, borderWidth: 1.5, shapeProperties: { borderRadius: 8 } };
const options = {
  nodes: NODE_STYLE,
  edges: { arrows: "to", color: { color: "#9aa0c7", highlight: "#4b56d2" },
    font: { size: 12, color: "#4b56d2", strokeWidth: 3, strokeColor: "#fff", align: "middle" }, smooth: { type: "cubicBezier" } },
  physics: { enabled: true, barnesHut: { springLength: 130, gravitationalConstant: -6000 }, stabilization: { iterations: 120 } },
  interaction: { hover: true, multiselect: true, navigationButtons: false },
  manipulation: {
    enabled: false,
    addNode: (data, cb) => { data.label = "concept"; cb(data); setTimeout(() => editLabel(data.id), 30); },
    addEdge: (data, cb) => {
      if (data.from === data.to) { cb(null); return; }
      openModal("Name the relationship", (label) => { if (label == null) { cb(null); return; } data.label = label; data.arrows = "to"; cb(data); relint(); });
    },
  },
};
const network = new vis.Network(container, { nodes, edges }, options);

// After nodes/edges change programmatically (load or AI), let physics settle
// then frame everything so freshly-added nodes are actually in view.
function refit() {
  if (!nodes.length) return;
  try {
    network.once("stabilized", () => { try { network.fit({ animation: { duration: 300 } }); } catch (e) {} });
    network.stabilize();
  } catch (e) { try { network.fit(); } catch (e2) {} }
}

/* ---- Python bridge (Anki pycmd) ---- */
function send(cmd) { if (window.pycmd) { pycmd(cmd); return true; } return false; }
function status(t) { document.getElementById("status").textContent = t || ""; }
function busy(on) { document.body.classList.toggle("spin", !!on); }

/* ---- data <-> model ---- */
function nextId() { const ids = nodes.getIds().map(Number).filter((n) => !isNaN(n)); return (ids.length ? Math.max(...ids) : 0) + 1; }
function collect() {
  return {
    concepts: nodes.get().map((n) => ({ id: Number(n.id), parent: (n.parent ?? null), label: (n.label || "").trim() })),
    // pending AI proposals are NOT saved until the learner accepts them
    links: edges.get().filter((e) => !e.pending).map((e) => ({ src: Number(e.from), dst: Number(e.to), label: (e.label || "").trim() })),
  };
}
function pendingEdges() { return edges.get().filter((e) => e.pending); }
function showProposed() {
  const c = pendingEdges().length;
  const box = document.getElementById("proposed");
  if (c > 0) {
    document.getElementById("proposedText").textContent =
      "AI proposed " + c + " arrow" + (c > 1 ? "s" : "") +
      " (dashed) \u2014 double-click one to keep it, select + Delete to drop it, or:";
    box.classList.remove("hidden");
  } else {
    box.classList.add("hidden");
  }
}
function acceptEdge(id) {
  const e = edges.get(id);
  if (!e || !e.pending) return;
  edges.update({ id, pending: false, dashes: false, color: { color: "#9aa0c7", highlight: "#4b56d2" } });
  showProposed(); relint();
}
// Python -> JS: replace the whole map (initial load or AI auto-build).
window.loadMap = function (json) {
  const m = typeof json === "string" ? JSON.parse(json) : json;
  nodes.clear(); edges.clear();
  nodes.add((m.concepts || []).map((c) => ({ id: c.id, label: c.label, parent: c.parent ?? null })));
  edges.add((m.links || []).map((l, i) => ({ id: "e" + i, from: l.src, to: l.dst, label: l.label || "", arrows: "to" })));
  relint(); busy(false); status("Loaded " + (m.concepts || []).length + " concepts"); showProposed(); refit();
};
// Python -> JS: add fresh concept nodes (auto-ids), keeping the current map.
window.applyNodes = function (json) {
  const arr = typeof json === "string" ? JSON.parse(json) : json;
  let id = nextId();
  arr.forEach((c) => { const label = (c.label || c).toString(); nodes.add({ id, label }); id++; });
  relint(); busy(false); status("AI added " + arr.length + " concepts"); refit();
};
// Python -> JS: add labeled arrows between existing nodes (matched by label).
window.applyLinks = function (json) {
  const arr = typeof json === "string" ? JSON.parse(json) : json;
  const byLabel = {}; nodes.get().forEach((n) => (byLabel[(n.label || "").trim().toLowerCase()] = n.id));
  let base = edges.length, n = 0;
  arr.forEach((l) => {
    const s = byLabel[(l.src_label || "").trim().toLowerCase()], d = byLabel[(l.dst_label || "").trim().toLowerCase()];
    if (s != null && d != null && s !== d) {
      // proposed arrows land as PENDING (dashed amber): the learner accepts or rejects
      edges.add({ id: "p" + (base + n++), from: s, to: d, label: l.label || "", arrows: "to",
                  pending: true, dashes: true, color: { color: "#f0a500", highlight: "#e08a00" } });
    }
  });
  busy(false); status("AI proposed " + n + " arrow" + (n !== 1 ? "s" : "") + " \u2014 review below"); showProposed(); refit();
};
window.chatReply = function (text) { addChat("ai", text); busy(false); };
// Python -> JS: apply a batch of edits from the chat assistant (add concepts,
// add/remove labeled arrows). Matches endpoints to node labels case-insensitively.
window.applyOps = function (json) {
  const o = typeof json === "string" ? JSON.parse(json) : json;
  let id = nextId();
  (o.add_concepts || []).forEach((c) => {
    const label = (c.label || c).toString().trim();
    if (label) { nodes.add({ id, label }); id++; }
  });
  const byLabel = {}; nodes.get().forEach((n) => (byLabel[(n.label || "").trim().toLowerCase()] = n.id));
  (o.remove_links || []).forEach((l) => {
    const s = byLabel[(l.src_label || "").trim().toLowerCase()], d = byLabel[(l.dst_label || "").trim().toLowerCase()];
    if (s != null && d != null) { edges.get().forEach((e) => { if (e.from === s && e.to === d) edges.remove(e.id); }); }
  });
  let base = edges.length, n = 0;
  (o.add_links || []).forEach((l) => {
    const s = byLabel[(l.src_label || "").trim().toLowerCase()], d = byLabel[(l.dst_label || "").trim().toLowerCase()];
    if (s != null && d != null && s !== d) { edges.add({ id: "c" + (base + n++), from: s, to: d, label: l.label || "", arrows: "to" }); }
  });
  const parts = [];
  if ((o.add_concepts || []).length) parts.push("+" + o.add_concepts.length + " concepts");
  if (n) parts.push("+" + n + " arrows");
  if ((o.remove_links || []).length) parts.push("\u2212 arrows");
  relint(); status(parts.length ? "Applied " + parts.join(", ") : ""); refit();
};

/* ---- linter (mirrors mcat_program.lint_concepts, non-blocking) ---- */
function relint() {
  const box = document.getElementById("warn"); box.innerHTML = "";
  const cs = nodes.get(), es = edges.get().filter((e) => !e.pending);
  const indeg = {}, outdeg = {}; cs.forEach((c) => { indeg[c.id] = 0; outdeg[c.id] = 0; });
  es.forEach((e) => { if (outdeg[e.from] != null) outdeg[e.from]++; if (indeg[e.to] != null) indeg[e.to]++; });
  cs.forEach((c) => { if (indeg[c.id] === 1 && outdeg[c.id] === 1)
    box.innerHTML += `<div>\u201c${c.label}\u201d is a lone one-in/one-out concept \u2014 merge or re-chunk.</div>`; });
}

/* ---- label modal (chips + free-text; optional prefill + delete) ---- */
let modalCb = null, modalDelete = null, chosen = "";
function openModal(title, cb, opts) {
  opts = opts || {};
  document.getElementById("modalTitle").textContent = title || "Name the relationship";
  chosen = ""; modalCb = cb; modalDelete = opts.onDelete || null;
  document.querySelectorAll(".chip").forEach((c) => c.classList.remove("sel"));
  const t = document.getElementById("relText"); t.value = opts.value || "";
  const del = document.getElementById("mDelete");
  if (del) del.style.display = modalDelete ? "" : "none";
  document.getElementById("mOk").textContent = opts.okText || "Add";
  document.getElementById("modal").classList.remove("hidden"); t.focus(); t.select();
}
function closeModal() { document.getElementById("modal").classList.add("hidden"); modalCb = null; modalDelete = null; }
document.querySelectorAll(".chip").forEach((c) => c.onclick = () => {
  document.querySelectorAll(".chip").forEach((x) => x.classList.remove("sel"));
  c.classList.add("sel"); chosen = c.dataset.v; document.getElementById("relText").value = "";
});
document.getElementById("relText").oninput = () => { chosen = ""; document.querySelectorAll(".chip").forEach((x) => x.classList.remove("sel")); };
document.getElementById("mCancel").onclick = () => { const cb = modalCb; closeModal(); if (cb) cb(null); };
document.getElementById("mOk").onclick = () => {
  const label = (chosen || document.getElementById("relText").value || "related to").trim();
  const cb = modalCb; closeModal(); if (cb) cb(label);
};
document.getElementById("mDelete").onclick = () => { const d = modalDelete; closeModal(); if (d) d(); };

/* ---- node rename ---- */
function editLabel(id) {
  const n = nodes.get(id); if (!n) return;
  const v = window.prompt("Concept name:", n.label || ""); if (v != null) { nodes.update({ id, label: v.trim() }); relint(); }
}
network.on("doubleClick", (p) => {
  if (p.nodes && p.nodes.length) { editLabel(p.nodes[0]); return; }
  if (p.edges && p.edges.length) acceptEdge(p.edges[0]);  // double-click a pending arrow to keep it
});

/* ---- click an arrow to relabel or delete it ---- */
function editEdge(id) {
  const e = edges.get(id); if (!e) return;
  openModal("Edit the arrow", (label) => {
    if (label == null) return;               // Cancel
    edges.update({ id, label: label });
    relint(); status("Arrow relabeled");
  }, {
    value: e.label || "",
    okText: "Save",
    onDelete: () => { edges.remove(id); showProposed(); relint(); status("Arrow deleted"); },
  });
}
network.on("click", (p) => {
  if (p.nodes && p.nodes.length) return;                 // node click — ignore
  if (!p.edges || !p.edges.length) return;               // empty space — ignore
  const e = edges.get(p.edges[0]);
  if (!e || e.pending) return;                           // pending arrows use the accept/discard flow
  editEdge(p.edges[0]);
});
// proposed-arrows review banner
document.getElementById("pKeep").onclick = () => { pendingEdges().forEach((e) => acceptEdge(e.id)); status("Kept all proposed arrows"); };
document.getElementById("pDiscard").onclick = () => {
  const ids = pendingEdges().map((e) => e.id);
  edges.remove(ids); showProposed(); relint(); status("Discarded " + ids.length + " proposed arrows");
};

/* ---- toolbar ---- */
document.getElementById("bAdd").onclick = () => network.addNodeMode();
document.getElementById("bLink").onclick = () => network.addEdgeMode();
document.getElementById("bDel").onclick = () => { network.deleteSelected(); relint(); };
document.getElementById("bSave").onclick = () => {
  const m = collect();
  if (send("synapse:save:" + JSON.stringify(m))) status("Saved \u00b7 " + m.concepts.length + " concepts, " + m.links.length + " links");
  else status("(preview) " + m.concepts.length + " concepts, " + m.links.length + " links");
};
document.getElementById("bSeed").onclick = () => { busy(true); status("AI seeding\u2026"); if (!send("synapse:seed")) { busy(false); status("(no engine)"); } };
document.getElementById("bArrows").onclick = () => { busy(true); status("AI proposing arrows\u2026"); if (!send("synapse:arrows:" + JSON.stringify(collect()))) { busy(false); status("(no engine)"); } };
document.getElementById("bAuto").onclick = () => { busy(true); status("AI building the whole map\u2026"); if (!send("synapse:auto")) { busy(false); status("(no engine)"); } };

/* ---- chat ---- */
document.getElementById("bChat").onclick = () => document.getElementById("chat").classList.toggle("hidden");
document.getElementById("chatClose").onclick = () => document.getElementById("chat").classList.add("hidden");
function addChat(who, text) {
  const log = document.getElementById("chatLog");
  const d = document.createElement("div"); d.className = "msg";
  d.innerHTML = `<div class="${who}">${who === "me" ? "You" : "Synapse"}</div><div class="${who === "ai" ? "ai" : ""}">${(text || "").replace(/</g, "&lt;")}</div>`;
  log.appendChild(d); log.scrollTop = log.scrollHeight;
}
function sendChat() {
  const inp = document.getElementById("chatInput"); const msg = inp.value.trim(); if (!msg) return;
  addChat("me", msg); inp.value = "";
  busy(true);
  if (!send("synapse:chat:" + JSON.stringify({ msg, map: collect() }))) { busy(false); addChat("ai", "(no engine connected)"); }
}
document.getElementById("chatSend").onclick = sendChat;
document.getElementById("chatInput").addEventListener("keydown", (e) => { if (e.key === "Enter") sendChat(); });

/* Ask Python for the initial map once Anki's pycmd bridge has connected. The
   QWebChannel bootstrap defines pycmd asynchronously at DocumentReady, so poll
   briefly instead of firing once (fallback after ~2s: an empty canvas). */
(function waitForBridge(tries) {
  if (window.pycmd) { send("synapse:init"); }
  else if (tries < 50) { setTimeout(() => waitForBridge(tries + 1), 40); }
})(0);
