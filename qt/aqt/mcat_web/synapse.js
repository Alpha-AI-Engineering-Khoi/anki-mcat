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
    links: edges.get().map((e) => ({ src: Number(e.from), dst: Number(e.to), label: (e.label || "").trim() })),
  };
}
// Python -> JS: replace the whole map (initial load or AI auto-build).
window.loadMap = function (json) {
  const m = typeof json === "string" ? JSON.parse(json) : json;
  nodes.clear(); edges.clear();
  nodes.add((m.concepts || []).map((c) => ({ id: c.id, label: c.label, parent: c.parent ?? null })));
  edges.add((m.links || []).map((l, i) => ({ id: "e" + i, from: l.src, to: l.dst, label: l.label || "", arrows: "to" })));
  relint(); busy(false); status("Loaded " + (m.concepts || []).length + " concepts"); refit();
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
    if (s != null && d != null && s !== d) { edges.add({ id: "a" + (base + n++), from: s, to: d, label: l.label || "", arrows: "to" }); }
  });
  relint(); busy(false); status("AI proposed " + n + " arrows"); refit();
};
window.chatReply = function (text) { addChat("ai", text); busy(false); };

/* ---- linter (mirrors mcat_program.lint_concepts, non-blocking) ---- */
function relint() {
  const box = document.getElementById("warn"); box.innerHTML = "";
  const cs = nodes.get(), es = edges.get();
  const indeg = {}, outdeg = {}; cs.forEach((c) => { indeg[c.id] = 0; outdeg[c.id] = 0; });
  es.forEach((e) => { if (outdeg[e.from] != null) outdeg[e.from]++; if (indeg[e.to] != null) indeg[e.to]++; });
  cs.forEach((c) => { if (indeg[c.id] === 1 && outdeg[c.id] === 1)
    box.innerHTML += `<div>\u201c${c.label}\u201d is a lone one-in/one-out concept \u2014 merge or re-chunk.</div>`; });
}

/* ---- label modal (chips + free-text) ---- */
let modalCb = null, chosen = "";
function openModal(title, cb) {
  document.getElementById("modalTitle").textContent = title || "Name the relationship";
  chosen = ""; modalCb = cb;
  document.querySelectorAll(".chip").forEach((c) => c.classList.remove("sel"));
  const t = document.getElementById("relText"); t.value = "";
  document.getElementById("modal").classList.remove("hidden"); t.focus();
}
function closeModal() { document.getElementById("modal").classList.add("hidden"); modalCb = null; }
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

/* ---- node rename ---- */
function editLabel(id) {
  const n = nodes.get(id); if (!n) return;
  const v = window.prompt("Concept name:", n.label || ""); if (v != null) { nodes.update({ id, label: v.trim() }); relint(); }
}
network.on("doubleClick", (p) => { if (p.nodes && p.nodes.length) editLabel(p.nodes[0]); });

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
