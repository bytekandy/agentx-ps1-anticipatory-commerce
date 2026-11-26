"use strict";
const $ = id => document.getElementById(id);
const SLOTS = [["category", "Category"], ["colour", "Colour"], ["size", "Size"], ["brand", "Brand"], ["max_price", "Budget"]];
const api = {base: location.protocol === "file:" ? "http://127.0.0.1:8765" : location.origin, ws: null, es: null};
let state = null, sent = "", info = {break_even_risk: 0.0387};

const key = () => $("key").value.trim();
const url = (path, params = {}) => {
  const q = new URLSearchParams(params); if (key()) q.set("api_key", key());
  return api.base + path + (q.toString() ? "?" + q : "");
};
const wsUrl = (path, params) => url(path, params).replace(/^http/, "ws");     // an absolute ws:// URL
const rupees = n => "Rs. " + Number(n).toLocaleString("en-IN");
const say = (msg = "") => { $("status").textContent = msg; };

function reset() {
  if (api.ws) { api.ws.onclose = null; api.ws.close(); api.ws = null; }
  if (api.es) { api.es.close(); api.es = null; }
  state = {words: 0, committedAt: null}; sent = "";
  $("text").value = ""; $("text").disabled = false; $("finish").disabled = false;
  $("chips").innerHTML = ""; $("conf").style.width = "0"; $("confnum").textContent = "0.00";
  $("flags").innerHTML = ""; $("reason").textContent = ""; $("risk").textContent = "";
  $("slots").innerHTML = SLOTS.map(([k, label]) => `<div class="slot none" id="slot-${k}"><span>${label}</span><b>not mentioned</b></div>`).join("");
  setCard("commit", null, "");
  setCard("final", null, "");
  $("evaluation").classList.add("hidden"); say();
  document.querySelector("#tab-live .thread").classList.add("fresh");
}

function setCard(id, product, empty, extra = "", cls = "") {
  const el = $(id); el.className = "card " + (product ? cls : "empty");
  el.innerHTML = product
    ? `<h3>${esc(product.title)}</h3><div class="meta">${esc(product.brand)} · ${esc(product.colour)}${product.size ? " · size " + esc(product.size) : ""} · ${rupees(product.price)} · ${esc(product.product_id)}</div>${extra}`
    : esc(empty);
}
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c])); }

function showWord(e) {
  const t = e.trace; state.words = e.seq;
  document.querySelector("#tab-live .thread").classList.remove("fresh");
  const chip = document.createElement("span");
  chip.className = "chip" + (e.commit ? " commit" : t.settled ? "" : " hold");
  chip.innerHTML = esc(e.word) + (e.commit ? "<small>commit</small>" : "");
  chip.title = t.reason; $("chips").appendChild(chip);
  for (const [k] of SLOTS) {
    const v = t.filters[k], el = $("slot-" + k);
    el.className = "slot" + (v == null ? " none" : "");
    el.querySelector("b").textContent = v == null ? "not mentioned" : (k === "max_price" ? "up to " + rupees(v) : v);
  }
  $("conf").style.width = Math.round(t.confidence * 100) + "%"; $("confnum").textContent = t.confidence.toFixed(2);
  const flags = [];
  flags.push(t.settled ? ["settled", "ok"] : ["still changing", "warn"]);
  if (t.correction_pending) flags.push(["correction on its way", "warn"]);
  for (const s of t.pending_slots) flags.push(["number growing: " + s, "warn"]);
  for (const u of t.unresolved) flags.push(["not understood: " + u, "bad"]);
  if (t.searched) flags.push([`searched: ${t.n_candidates} match${t.n_candidates === 1 ? "" : "es"}`, "ok"]);
  $("flags").innerHTML = flags.map(([text, c]) => `<span class="flag ${c}">${esc(text)}</span>`).join("");
  $("reason").textContent = t.reason;
  $("risk").textContent = t.risk == null ? "" : `chance a commit is wrong: ${(t.risk * 100).toFixed(1)}% (commits when below ${(info.break_even_risk * 100).toFixed(1)}%)`;
  if (e.commit) {
    state.committedAt = e.seq;
    setCard("commit", e.commit.product, "", `<div class="meta">committed after word ${e.seq}</div>`, "good");
  }
}

function showFinal(f) {
  const same = f.commit && f.commit.product_id === f.final_product_id;
  setCard("final", f.product, "Nothing matched.",
    `<div class="meta">${f.commit ? (same ? "same as the early commit" : "different from the early commit") : "no early commit"} · ${f.searches} search${f.searches === 1 ? "" : "es"}</div>`, "good");
  if (f.evaluation) {
    const e = f.evaluation, ok = e.correct && e.wrong_commits === 0;
    const el = $("evaluation"); el.className = "card " + (ok ? "good" : "bad");
    el.innerHTML = `<h3>${e.correct ? "Right answer" : "Wrong answer"}${e.wrong_commits ? ", " + e.wrong_commits + " wrong commit" : ""}</h3>
      <div class="meta">score ${e.score.toFixed(3)} · ${e.early_words} word${e.early_words === 1 ? "" : "s"} early (best possible ${Math.round(e.oracle_share * f.words)}) · target ${esc(e.target_product ? e.target_product.title : e.target)}</div>`;
  }
  $("text").disabled = true; $("finish").disabled = true;
}

function onMessage(msg) {
  const e = JSON.parse(msg.data);
  if (e.type === "word") showWord(e);
  else if (e.type === "final") showFinal(e);
  else if (e.type === "error") say(e.error.message);
}

/* live: one WebSocket, a word goes out each time a space is typed */
function connect() {
  if (api.ws) return Promise.resolve(api.ws);
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl("/api/ws", {agent: $("agent").value}));
    ws.onmessage = onMessage;
    ws.onopen = () => { api.ws = ws; resolve(ws); };
    ws.onerror = () => { say("Cannot connect. Is the server running (python -m server)? A wrong API key is refused too."); reject(); };
    ws.onclose = () => { api.ws = null; };
  });
}
async function sendWord(w) { (await connect()).send(JSON.stringify({word: w})); }

$("text").addEventListener("input", async () => {
  const box = $("text");
  if (!box.value.startsWith(sent)) { box.value = sent; say("That word was already sent. Start a new request to change it."); return; }
  say();
  const tail = box.value.slice(sent.length), m = tail.match(/^\s*(\S+)\s/);
  if (!m) return;
  const word = m[1]; sent += m[0];
  try { await sendWord(word); } catch (_) {}
  box.dispatchEvent(new Event("input"));                  // several words at once (a paste)
});

async function finish() {
  const rest = $("text").value.slice(sent.length).trim();
  try {
    for (const w of rest.split(/\s+/).filter(Boolean)) await sendWord(w);
    sent = $("text").value;
    if (!state.words && !rest) { say("Type something first."); return; }
    (await connect()).send(JSON.stringify({finish: true}));
  } catch (_) {}
}
$("finish").addEventListener("click", finish);
$("text").addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); finish(); } });
$("reset").addEventListener("click", reset);
$("agent").addEventListener("change", reset);

/* replay: the server paces a whole request as server-sent events */
function replay() {
  const id = $("example").value, text = $("text").value.trim();
  if (!id && !text) { say("Pick a dev request, or type one, then press Replay."); return; }
  reset(); if (!id) $("text").value = text;
  $("text").disabled = true;
  const es = new EventSource(url("/api/replay", id ? {example: id, agent: $("agent").value, delay_ms: $("delay").value}
                                                   : {text, agent: $("agent").value, delay_ms: $("delay").value}));
  api.es = es;
  es.addEventListener("start", e => { const s = JSON.parse(e.data); if (s.text) $("text").value = s.text; });
  es.addEventListener("word", onMessage); es.addEventListener("final", onMessage);
  es.addEventListener("done", () => es.close());
  es.onerror = () => { if (es.readyState === EventSource.CLOSED) return; es.close(); say("Replay failed (server not running, or a wrong API key)."); };
}
$("replay").addEventListener("click", replay);

async function loadExamples() {
  try {
    const q = k => fetch(url("/api/examples", {set: "dev", tag: k, limit: 6})).then(r => r.json());
    const groups = await Promise.all([["plain", "plain"], ["correction", "with a correction"], ["late_constraint", "late constraint"], ["code_mixed", "Hindi-English"]]
      .map(async ([k, label]) => [label, (await q(k)).items]));
    $("example").innerHTML = '<option value="">Pick a dev request...</option>' + groups.filter(([, items]) => items)
      .map(([label, items]) => `<optgroup label="${label}">${items.map(i => `<option value="${i.id}">${esc(i.text.slice(0, 70))}</option>`).join("")}</optgroup>`).join("");
  } catch (_) {}
}

/* results tab */
async function loadResults() {
  const box = $("results");
  try {
    const r = await (await fetch(url("/api/results/" + $("set").value))).json(), s = r.summary, b = r.baseline;
    const row = (name, x, y) => `<tr><td>${name}</td><td>${x}</td><td>${y}</td></tr>`;
    box.innerHTML = `<table><tr><th></th><th>our agent</th><th>kit baseline</th></tr>
      ${row("requests", s.requests, b.requests)}${row("score", "<b>" + s.score.toFixed(1) + "</b>", b.score.toFixed(1))}
      ${row("accuracy", s.accuracy.toFixed(3), b.accuracy.toFixed(3))}${row("wrong early commits", s.wrong_commits, b.wrong_commits)}
      ${row("earliness", (s.early_share * 100).toFixed(1) + "%", (b.early_share * 100).toFixed(1) + "%")}${row("searches per request", s.searches.toFixed(2), b.searches.toFixed(2))}</table>
      <table><tr><th>by tag</th><th>requests</th><th>score</th><th>wrong commits</th></tr>
      ${Object.entries(r.by_tag).map(([t, x]) => `<tr><td>${t}</td><td>${x.requests}</td><td>${x.score.toFixed(1)}</td><td>${x.wrong_commits}</td></tr>`).join("")}</table>`;
  } catch (_) { box.textContent = "Could not load results (is the server running?)."; }
}
$("set").addEventListener("change", loadResults);

document.querySelectorAll("nav button").forEach(b => b.addEventListener("click", () => {
  document.querySelectorAll("nav button").forEach(x => x.classList.toggle("on", x === b));
  for (const t of ["live", "results"]) $("tab-" + t).classList.toggle("hidden", t !== b.dataset.tab);
  if (b.dataset.tab === "results") loadResults();
}));

reset(); loadExamples();
fetch(url("/api/info")).then(r => r.json()).then(i => { info = i; }).catch(() => {});
